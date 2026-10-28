import React, { useMemo, useRef, useState } from "react";
import { useWorkerHealth } from "../components/Layout.jsx";
import { Empty, ErrorNote, Modal, PageHead, StatusPill } from "../components/ui.jsx";
import { usePolling, useResource } from "../hooks/useData.js";
import { api } from "../lib/api.js";
import { formatDuration, timeAgo } from "../lib/format.js";

const MIN_STATEMENT = 20;

export default function Voices() {
  const voices = useResource(() => api.voices());
  const engines = useResource(() => api.engines());
  const [cloning, setCloning] = useState(false);
  const [error, setError] = useState(null);

  const all = voices.data || [];
  const mine = all.filter((v) => !v.is_system);
  const system = all.filter((v) => v.is_system);
  const pending = mine.some((v) => v.status === "pending");
  usePolling(voices.reload, 3000, pending); // watch clones until the worker prepares them

  const byEngine = useMemo(() => {
    const map = new Map();
    for (const v of system) map.set(v.engine, [...(map.get(v.engine) || []), v]);
    return [...map.entries()];
  }, [system]);
  const engineInfo = (id) => (engines.data || []).find((e) => e.id === id);
  const cloneEngine = (engines.data || []).find((e) => e.supports_cloning);

  const remove = async (v) => {
    if (!window.confirm(`Delete the voice "${v.name}"? Its reference audio is deleted too.`)) return;
    setError(null);
    try {
      await api.deleteVoice(v.id);
      voices.reload();
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div>
      <PageHead kicker="Voices" title="Your cast">
        <button type="button" className="btn btn--primary" onClick={() => setCloning(true)} disabled={!cloneEngine}>
          Clone a voice
        </button>
      </PageHead>
      <ErrorNote error={error || voices.error} />

      <section className="section">
        <h2 className="section__title">Your cloned voices</h2>
        {mine.length === 0 ? (
          <Empty title="No cloned voices yet">
            <p>Upload 3–60 seconds of clean speech from someone who has given you permission, and VOIX will learn to speak in that voice.</p>
          </Empty>
        ) : (
          <div className="cards">
            {mine.map((v) => (
              <article key={v.id} className="card voice">
                <header className="voice__head">
                  <h3>{v.name}</h3>
                  <StatusPill status={v.status} />
                </header>
                <p className="voice__meta mono">
                  {v.engine} · {v.language} · {v.duration_seconds ? formatDuration(v.duration_seconds) : "—"} · {timeAgo(v.created_at)}
                </p>
                {v.status === "failed" && <p className="notice notice--error">{v.error}</p>}
                {v.status === "pending" && <p className="muted">A worker is standardising the clip…</p>}
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => remove(v)}>
                  Delete
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      {byEngine.map(([engine, list]) => {
        const info = engineInfo(engine);
        return (
          <section className="section" key={engine}>
            <h2 className="section__title">
              {info?.name || engine}
              {info && <span className={`chip ${info.commercial_use ? "chip--ok" : "chip--warn"}`}>{info.license}</span>}
            </h2>
            {info?.notes && <p className="section__note">{info.notes}</p>}
            <div className="cards cards--dense">
              {list.map((v) => (
                <article key={v.id} className="card voice voice--system">
                  <h3>{v.name}</h3>
                  <p className="voice__meta">{v.description}</p>
                  <p className="voice__meta mono">{v.language}</p>
                </article>
              ))}
            </div>
          </section>
        );
      })}

      {cloning && (
        <CloneFlow
          engine={cloneEngine}
          onClose={() => setCloning(false)}
          onCreated={() => {
            setCloning(false);
            voices.reload();
          }}
        />
      )}
    </div>
  );
}

function CloneFlow({ engine, onClose, onCreated }) {
  const health = useWorkerHealth();
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en");
  const [consent, setConsent] = useState(false);
  const [statement, setStatement] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  const pick = (f) => {
    setFile(f);
    if (preview) URL.revokeObjectURL(preview);
    setPreview(f ? URL.createObjectURL(f) : null);
    if (f && !name) setName(f.name.replace(/\.[^.]+$/, "").slice(0, 100));
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.cloneVoice({ name: name.trim(), language, file, consentStatement: statement.trim() });
      onCreated();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  const statementOk = statement.trim().length >= MIN_STATEMENT;
  return (
    <Modal
      title={step === 1 ? "Clone a voice · 1 of 2 · Sample" : "Clone a voice · 2 of 2 · Consent"}
      onClose={onClose}
      footer={
        step === 1 ? (
          <>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn btn--primary" disabled={!file || !name.trim()} onClick={() => setStep(2)}>
              Continue
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setStep(1)} disabled={busy}>
              Back
            </button>
            <button type="button" className="btn btn--primary" disabled={!consent || !statementOk || busy} onClick={submit}>
              {busy ? "Uploading…" : "Clone voice"}
            </button>
          </>
        )
      }
    >
      {step === 1 ? (
        <div className="form">
          <button
            type="button"
            className={`dropzone ${file ? "dropzone--filled" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              pick(e.dataTransfer.files?.[0] || null);
            }}
          >
            {file ? (
              <>
                <strong>{file.name}</strong>
                <span className="muted">{(file.size / 1e6).toFixed(1)} MB · click to replace</span>
              </>
            ) : (
              <>
                <strong>Drop an audio clip here</strong>
                <span className="muted">wav, mp3, flac, ogg or m4a · 3–60 s of one person speaking clearly</span>
              </>
            )}
          </button>
          <input ref={inputRef} type="file" accept=".wav,.mp3,.flac,.ogg,.m4a,audio/*" hidden onChange={(e) => pick(e.target.files?.[0] || null)} />
          {preview && <audio className="form__audio" src={preview} controls />}
          <label className="field">
            <span className="label">Voice name</span>
            <input className="input" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Language</span>
            <select className="select" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {(engine?.languages || ["en"]).map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </label>
          <p className="muted small">
            Cloning uses {engine?.name} ({engine?.license}).
          </p>
        </div>
      ) : (
        <div className="form">
          <div className="consent">
            <p>
              Cloning someone's voice without permission can be used to deceive or harm them. VOIX records your
              statement, the time and your IP address with this voice.
            </p>
          </div>
          <label className="check">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>I am the person in this recording, or I have their explicit permission to clone their voice.</span>
          </label>
          <label className="field">
            <span className="label">Consent statement (in your own words)</span>
            <textarea
              className="input input--area"
              rows={4}
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              placeholder="e.g. This is my own voice, recorded by me on 28 Oct 2026 for my YouTube narration."
            />
            <span className={`small ${statementOk ? "muted" : "warn"}`}>
              {statement.trim().length}/{MIN_STATEMENT} characters minimum
            </span>
          </label>
          {health?.workers_online === 0 && (
            <p className="console__warn">The worker is offline; the voice will be prepared when it reconnects.</p>
          )}
          <ErrorNote error={error} />
        </div>
      )}
    </Modal>
  );
}
