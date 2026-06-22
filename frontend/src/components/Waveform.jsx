import React, { useMemo } from "react";

/**
 * The signature visual element of the app: a bar waveform that idles with
 * a slow ambient breathing motion, and animates actively while speech is
 * being generated or played back. Reused in the hero, the generate button,
 * and the audio player so the "speech as waveform" idea threads through
 * the whole interface.
 */
export default function Waveform({
  active = false,
  bars = 48,
  variant = "default", // "default" | "compact"
  color,
}) {
  const heights = useMemo(() => {
    // Deterministic pseudo-random heights so the idle shape stays stable
    // across re-renders but still looks organic, not a flat row.
    const seedBase = bars * 7919;
    return Array.from({ length: bars }, (_, i) => {
      const seed = Math.sin(seedBase + i * 12.9898) * 43758.5453;
      const frac = seed - Math.floor(seed);
      return 0.18 + frac * 0.82;
    });
  }, [bars]);

  const barWidth = variant === "compact" ? 2 : 3;
  const gap = variant === "compact" ? 2 : 3;
  const maxHeight = variant === "compact" ? 24 : 64;

  return (
    <div
      className={`waveform waveform--${variant} ${active ? "waveform--active" : ""}`}
      style={{ "--bar-color": color }}
      aria-hidden="true"
    >
      {heights.map((h, i) => (
        <span
          key={i}
          className="waveform__bar"
          style={{
            width: `${barWidth}px`,
            marginRight: i === heights.length - 1 ? 0 : `${gap}px`,
            height: `${Math.max(4, h * maxHeight)}px`,
            animationDelay: `${(i % 12) * 0.07}s`,
          }}
        />
      ))}
    </div>
  );
}
