import React from "react";
import Waveform from "./Waveform.jsx";

export default function Header({ health }) {
  const deviceLabel = health
    ? health.device === "cuda"
      ? `GPU · ${health.gpu_name || "CUDA"}`
      : "CPU"
    : "Checking…";

  const ready = health && health.loaded_engines.length > 0;
  const statusTone = health ? (ready ? "ready" : "loading") : "unknown";

  return (
    <header className="header">
      <div className="header__brand">
        <Waveform active bars={14} variant="compact" />
        <span className="header__wordmark">VOIX</span>
      </div>
      <div className="header__meta">
        <span className={`status-pill status-pill--${statusTone}`}>
          <span className="status-pill__dot" />
          {health
            ? ready
              ? `Ready · ${health.loaded_engines.join(" + ")}`
              : "Warming up"
            : "Connecting"}
        </span>
        <span className="header__device">{deviceLabel}</span>
      </div>
    </header>
  );
}
