import React from "react";

const GENDER_COLOR = {
  male: "var(--signal-blue)",
  female: "var(--signal-coral)",
  custom: "var(--signal-violet)",
};

export default function VoiceSelector({ voices, selectedId, onSelect, disabled, onOpenClone }) {
  return (
    <div className="field">
      <div className="field__label-row">
        <label className="field__label">Voice</label>
        <button
          type="button"
          className="link-button"
          onClick={onOpenClone}
          disabled={disabled}
        >
          + Clone a voice
        </button>
      </div>
      <div className="voice-grid">
        {voices.map((voice) => {
          const isSelected = voice.voice_id === selectedId;
          return (
            <button
              key={voice.voice_id}
              type="button"
              className={`voice-card ${isSelected ? "voice-card--selected" : ""}`}
              onClick={() => onSelect(voice.voice_id)}
              disabled={disabled}
              style={{ "--accent": GENDER_COLOR[voice.gender] || "var(--signal-blue)" }}
            >
              <span className="voice-card__avatar">
                {voice.name.trim().charAt(0).toUpperCase()}
              </span>
              <span className="voice-card__info">
                <span className="voice-card__name">{voice.name}</span>
                <span className="voice-card__desc">{voice.description}</span>
              </span>
              {voice.is_custom && <span className="voice-card__badge">Custom</span>}
            </button>
          );
        })}
        {voices.length === 0 && (
          <p className="voice-grid__empty">No voices available yet.</p>
        )}
      </div>
    </div>
  );
}
