import React from "react";

const MAX_LENGTH = 5000;

export default function TextInput({ value, onChange, disabled }) {
  const remaining = MAX_LENGTH - value.length;
  const isNearLimit = remaining < 200;

  return (
    <div className="field">
      <div className="field__label-row">
        <label htmlFor="tts-text" className="field__label">
          Script
        </label>
        <span className={`field__counter ${isNearLimit ? "field__counter--warn" : ""}`}>
          {value.length} / {MAX_LENGTH}
        </span>
      </div>
      <textarea
        id="tts-text"
        className="textarea"
        placeholder="Type or paste what you want spoken. Punctuation shapes the performance — periods and commas become pauses, question marks lift the ending, exclamation points add energy."
        value={value}
        maxLength={MAX_LENGTH}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        rows={9}
      />
      <p className="field__hint">
        Tip: break long passages into short paragraphs — each one gets a natural breath between it and the next.
      </p>
    </div>
  );
}
