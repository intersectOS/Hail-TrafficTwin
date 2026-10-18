import { useEffect, useRef } from "react";
import type { Engine } from "../engine";
import { DAY_S, SPEEDS } from "../config";
import { fmtTime } from "../url";

interface Props {
  engine: Engine | null;
  playing: boolean;
  speed: number;
  span: [number, number];
  onPlaying: (p: boolean) => void;
  onSpeed: (s: number) => void;
  onSeekEnd: (t: number) => void;
}

/** Slider + play/pause + speed. The playhead is written to the DOM by an engine listener (~10 Hz),
 * never through React state, so playback does not re-render the app. */
export function Timeline({ engine, playing, speed, span, onPlaying, onSpeed, onSeekEnd }: Props) {
  const slider = useRef<HTMLInputElement>(null);
  const clock = useRef<HTMLSpanElement>(null);
  const binLabel = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!engine) return;
    return engine.addTickListener((t) => {
      if (slider.current && document.activeElement !== slider.current) slider.current.value = String(Math.round(t));
      if (clock.current) clock.current.textContent = fmtTime(t, true);
      if (binLabel.current) {
        const inSpan = t >= span[0] && t < span[1];
        binLabel.current.textContent = inSpan ? "" : "no data at this time";
      }
    });
  }, [engine, span]);

  const left = (span[0] / DAY_S) * 100;
  const width = ((span[1] - span[0]) / DAY_S) * 100;

  return (
    <div className="timeline">
      <button className="play" onClick={() => onPlaying(!playing)} title={playing ? "Pause" : "Play"}>
        {playing ? "❚❚" : "▶"}
      </button>
      <span className="clock" ref={clock}>
        00:00:00
      </span>
      <div className="slider-wrap">
        <div className="span-bar" style={{ left: `${left}%`, width: `${width}%` }} title="run data span" />
        <input
          ref={slider}
          type="range"
          min={0}
          max={DAY_S}
          step={1}
          defaultValue={0}
          onInput={(e) => engine?.seek(Number((e.target as HTMLInputElement).value))}
          onChange={(e) => onSeekEnd(Number(e.target.value))}
        />
        <div className="ticks">
          {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
            <span key={h} style={{ left: `${(h / 24) * 100}%` }}>
              {String(h).padStart(2, "0")}
            </span>
          ))}
        </div>
      </div>
      <select value={speed} onChange={(e) => onSpeed(Number(e.target.value))} title="sim seconds per second">
        {SPEEDS.map((s) => (
          <option key={s} value={s}>
            {s}x
          </option>
        ))}
      </select>
      <span className="nodata" ref={binLabel} />
    </div>
  );
}
