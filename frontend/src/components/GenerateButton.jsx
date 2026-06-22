import React from "react";
import Waveform from "./Waveform.jsx";

export default function GenerateButton({ onClick, isGenerating, disabled }) {
  return (
    <button
      type="button"
      className="generate-button"
      onClick={onClick}
      disabled={disabled || isGenerating}
    >
      <span className="generate-button__waveform">
        <Waveform active={isGenerating} bars={20} variant="compact" color="currentColor" />
      </span>
      <span className="generate-button__label">
        {isGenerating ? "Generating speech…" : "Generate audio"}
      </span>
    </button>
  );
}
