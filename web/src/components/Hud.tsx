import { useEffect, useRef } from "react";

interface PerfMemory {
  usedJSHeapSize: number;
  jsHeapSizeLimit: number;
}

/** FPS and JS heap readout; updates its own DOM twice a second. */
export function Hud({ extra }: { extra: () => string }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let frames = 0;
    let last = performance.now();
    let raf = 0;
    const loop = (now: number) => {
      frames++;
      if (now - last >= 500) {
        const fps = (frames * 1000) / (now - last);
        frames = 0;
        last = now;
        const mem = (performance as unknown as { memory?: PerfMemory }).memory;
        const heap = mem ? `${(mem.usedJSHeapSize / 1048576).toFixed(0)} MB heap` : "heap n/a";
        if (el.current) el.current.textContent = `${fps.toFixed(0)} fps · ${heap} · ${extra()}`;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [extra]);
  return <div className="hud" ref={el} />;
}
