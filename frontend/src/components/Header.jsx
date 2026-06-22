import React from "react";
import Waveform from "./Waveform.jsx";

export default function Header({ health }) {
  const deviceLabel = health
    ? health.device === "cuda"
      ? `GPU · ${health.gpu_name || "CUDA"}`
      : "CPU"
    : "Checking…";

  const statusTone = health ? (health.model_loaded ? "ready" : "loading") : "unknown";

  return (
    <header className="header">
      <div className="header__brand">
        <Waveform active bars={14} variant="compact" />
        <span className="header__wordmark">NaturalSpeech</span>
      </div>
      <div className="header__meta">
        <span className={`status-pill status-pill--${statusTone}`}>
          <span className="status-pill__dot" />
          {health
            ? health.model_loaded
              ? "Model ready"
              : "Warming up"
            : "Connecting"}
        </span>
        <span className="header__device">{deviceLabel}</span>
      </div>
    </header>
  );
}
