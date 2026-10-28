import React from "react";

const GENDER_COLOR = {
  male: "var(--signal-blue)",
  female: "var(--signal-coral)",
  custom: "var(--signal-violet)",
};

const GROUPS = [
  { engine: "kokoro", title: "Fast voices", note: "Kokoro-82M · Apache-2.0" },
  { engine: "xtts", title: "Cloning voices", note: "XTTS-v2 · non-commercial licence · slower" },
];

function VoiceCard({ voice, selected, onSelect, disabled }) {
  return (
    <button
      type="button"
      className={`voice-card ${selected ? "voice-card--selected" : ""}`}
      onClick={() => onSelect(voice.voice_id)}
      disabled={disabled}
      style={{ "--accent": GENDER_COLOR[voice.gender] || "var(--signal-blue)" }}
    >
      <span className="voice-card__avatar">{voice.name.trim().charAt(0).toUpperCase()}</span>
      <span className="voice-card__info">
        <span className="voice-card__name">{voice.name}</span>
        <span className="voice-card__desc">{voice.description}</span>
      </span>
      {voice.is_custom && <span className="voice-card__badge">Custom</span>}
    </button>
  );
}

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
      {GROUPS.map(({ engine, title, note }) => {
        const list = voices.filter((v) => v.engine === engine);
        if (list.length === 0) return null;
        return (
          <div key={engine} className="voice-group">
            <p className="voice-group__title">
              {title} <span className="voice-group__note">{note}</span>
            </p>
            <div className="voice-grid">
              {list.map((voice) => (
                <VoiceCard
                  key={voice.voice_id}
                  voice={voice}
                  selected={voice.voice_id === selectedId}
                  onSelect={onSelect}
                  disabled={disabled}
                />
              ))}
            </div>
          </div>
        );
      })}
      {voices.length === 0 && <p className="voice-grid__empty">No voices available yet.</p>}
    </div>
  );
}
