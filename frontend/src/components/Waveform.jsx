import React, { useEffect, useRef, useState } from "react";

const BARS = 160;

/** Peak amplitude per bucket from decoded audio (mono mixdown of channel 0). */
async function computePeaks(blob, buckets) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  const ctx = new Ctx();
  try {
    const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
    const data = audio.getChannelData(0);
    const size = Math.max(1, Math.floor(data.length / buckets));
    const peaks = new Float32Array(buckets);
    let max = 0;
    for (let b = 0; b < buckets; b++) {
      let peak = 0;
      const end = Math.min(data.length, (b + 1) * size);
      for (let i = b * size; i < end; i++) {
        const v = Math.abs(data[i]);
        if (v > peak) peak = v;
      }
      peaks[b] = peak;
      if (peak > max) max = peak;
    }
    return max > 0 ? peaks.map((p) => p / max) : peaks;
  } finally {
    ctx.close?.();
  }
}

function cssVar(el, name, fallback) {
  return getComputedStyle(el).getPropertyValue(name).trim() || fallback;
}

/**
 * The real waveform of the rendered audio, drawn on canvas. The played
 * portion is lit; clicking seeks. Falls back to a flat line while decoding.
 */
export default function Waveform({ blob, progress = 0, onSeek, height = 72 }) {
  const canvasRef = useRef(null);
  const [peaks, setPeaks] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setPeaks(null);
    if (blob) computePeaks(blob, BARS).then((p) => !cancelled && setPeaks(p));
    return () => {
      cancelled = true;
    };
  }, [blob]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      const g = canvas.getContext("2d");
      g.scale(dpr, dpr);
      g.clearRect(0, 0, width, height);
      const lit = cssVar(canvas, "--wave-lit", "#ff5a1f");
      const dim = cssVar(canvas, "--wave-dim", "#55524b");
      const step = width / BARS;
      const barW = Math.max(1, step * 0.55);
      const mid = height / 2;
      for (let i = 0; i < BARS; i++) {
        const amp = peaks ? Math.max(0.04, peaks[i]) : 0.04;
        const h = amp * (height - 6);
        g.fillStyle = i / BARS < progress ? lit : dim;
        g.fillRect(i * step, mid - h / 2, barW, h);
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [peaks, progress, height]);

  const handleClick = (e) => {
    if (!onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    onSeek(Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)));
  };

  return (
    <canvas
      ref={canvasRef}
      className="wave"
      style={{ height }}
      onClick={handleClick}
      role="slider"
      aria-label="Seek"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(progress * 100)}
      tabIndex={0}
      onKeyDown={(e) => {
        if (!onSeek) return;
        if (e.key === "ArrowRight") onSeek(Math.min(1, progress + 0.05));
        if (e.key === "ArrowLeft") onSeek(Math.max(0, progress - 0.05));
      }}
    />
  );
}
