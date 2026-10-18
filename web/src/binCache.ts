// LRU cache of 5-minute edge bins keyed by (run, metric, bin index), with in-flight de-duplication
// and prefetch ahead of the playhead.
import { api } from "./api";
import { BIN_CACHE_SIZE } from "./config";

type Key = string;
const key = (run: string, metric: string, i: number): Key => `${run}|${metric}|${i}`;

export class BinCache {
  private lru = new Map<Key, Float32Array>();
  private inflight = new Map<Key, Promise<Float32Array | null>>();
  /** Max entries per (run, metric) group; total cap = size * groups seen. */
  constructor(private readonly perGroup = BIN_CACHE_SIZE) {}
  bytes = 0;

  peek(run: string, metric: string, i: number): Float32Array | undefined {
    const k = key(run, metric, i);
    const v = this.lru.get(k);
    if (v) {
      this.lru.delete(k);
      this.lru.set(k, v);
    }
    return v;
  }

  get(run: string, metric: string, i: number): Promise<Float32Array | null> {
    const hit = this.peek(run, metric, i);
    if (hit) return Promise.resolve(hit);
    const k = key(run, metric, i);
    const pending = this.inflight.get(k);
    if (pending) return pending;
    const p = api
      .bin(run, i, metric)
      .then((arr) => {
        this.put(k, arr);
        return arr;
      })
      .catch((err: unknown) => {
        console.warn("bin fetch failed", k, err);
        return null;
      })
      .finally(() => this.inflight.delete(k));
    this.inflight.set(k, p);
    return p;
  }

  prefetch(run: string, metric: string, from: number, count: number, nBins: number): void {
    for (let j = 0; j < count; j++) {
      const i = from + j;
      if (i < 0 || i >= nBins) continue;
      void this.get(run, metric, i);
    }
  }

  private put(k: Key, arr: Float32Array): void {
    this.lru.set(k, arr);
    this.bytes += arr.byteLength;
    const group = k.slice(0, k.lastIndexOf("|"));
    let inGroup = 0;
    for (const kk of this.lru.keys()) if (kk.startsWith(group + "|")) inGroup++;
    if (inGroup <= this.perGroup) return;
    for (const [kk, v] of this.lru) {
      if (kk.startsWith(group + "|") && kk !== k) {
        this.lru.delete(kk);
        this.bytes -= v.byteLength;
        break;
      }
    }
  }

  get size(): number {
    return this.lru.size;
  }
}
