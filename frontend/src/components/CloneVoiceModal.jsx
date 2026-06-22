import React, { useState } from "react";
import { cloneVoice } from "../services/api.js";

export default function CloneVoiceModal({ open, onClose, onCloned }) {
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("idle"); // idle | uploading | error
  const [error, setError] = useState(null);

  if (!open) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) {
      setError({ message: "Choose an audio file first." });
      return;
    }
    setStatus("uploading");
    setError(null);
    try {
      const result = await cloneVoice(file, name);
      setStatus("idle");
      setFile(null);
      setName("");
      onCloned(result);
    } catch (err) {
      setStatus("error");
      setError(err);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h2>Clone a voice</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="modal__desc">
          Upload 3–60 seconds of clean, single-speaker audio. The clearer the
          recording, the closer the clone — quiet room, minimal background
          noise, natural pace.
        </p>
        <form onSubmit={handleSubmit} className="modal__form">
          <label className="field">
            <span className="field__label">Voice name</span>
            <input
              type="text"
              className="text-input"
              placeholder="e.g. Narrator Voice"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>

          <label className="field">
            <span className="field__label">Reference audio</span>
            <input
              type="file"
              accept=".wav,.mp3,.flac,.ogg,.m4a,audio/*"
              className="file-input"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file && <span className="field__hint">{file.name}</span>}
          </label>

          {error && <p className="form-error">{error.message}</p>}

          <div className="modal__footer">
            <button type="button" className="button button--ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={status === "uploading"}
            >
              {status === "uploading" ? "Cloning…" : "Clone voice"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
