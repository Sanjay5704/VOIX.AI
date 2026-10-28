import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import JobPanel from "../components/JobPanel.jsx";
import { useWorkerHealth } from "../components/Layout.jsx";
import { ErrorNote, Fader, PageHead } from "../components/ui.jsx";
import { useJob, useResource } from "../hooks/useData.js";
import { api } from "../lib/api.js";
import { formatNumber, newIdempotencyKey } from "../lib/format.js";

const DRAFT_KEY = "voix.studio.draft";
const SAMPLE =
  "Every great product starts with a story. Today, we're going to tell you ours. " +
  "It began with a simple question: what if anyone could give their words a voice?";

function loadDraft() {
  try {
    return JSON.parse(localStorage.getItem(DRAFT_KEY)) || {};
  } catch {
    return {};
  }
}

export default function Studio() {
  const draft = useMemo(loadDraft, []);
  const [text, setText] = useState(draft.text ?? SAMPLE);
  const [voiceId, setVoiceId] = useState(draft.voiceId ?? "");
  const [speed, setSpeed] = useState(draft.speed ?? 1);
  const [pitch, setPitch] = useState(draft.pitch ?? 0);
  const [expressiveness, setExpressiveness] = useState(draft.expressiveness ?? 1);
  const [format, setFormat] = useState(draft.format ?? "mp3");
  const [subtitles, setSubtitles] = useState(draft.subtitles ?? true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");
  const [job, setJob] = useJob(jobId);

  const voices = useResource(() => api.voices());
  const engines = useResource(() => api.engines());
  const usage = useResource(() => api.usage(), [job?.status === "succeeded"]);
  const health = useWorkerHealth();
  const jobRef = useRef(null);
  // Which engines a connected worker serves comes from the (polled) health feed.
  const onlineEngines = new Set((health?.workers || []).flatMap((w) => w.engines));

  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ text, voiceId, speed, pitch, expressiveness, format, subtitles }));
    } catch {
      /* storage unavailable */
    }
  }, [text, voiceId, speed, pitch, expressiveness, format, subtitles]);

  const ready = useMemo(() => (voices.data || []).filter((v) => v.status === "ready"), [voices.data]);
  useEffect(() => {
    if (ready.length && !ready.some((v) => v.id === voiceId)) {
      setVoiceId((ready.find((v) => v.engine === "kokoro") || ready[0]).id);
    }
  }, [ready, voiceId]);

  const voice = ready.find((v) => v.id === voiceId);
  const engineInfo = (engines.data || []).find((e) => e.id === voice?.engine);
  const groups = useMemo(() => {
    const byEngine = new Map();
    for (const v of ready) {
      const key = v.is_system ? v.engine : "mine";
      if (!byEngine.has(key)) byEngine.set(key, []);
      byEngine.get(key).push(v);
    }
    return [...byEngine.entries()];
  }, [ready]);

  const limit = usage.data?.limits.max_text_chars ?? 5000;
  const remaining = usage.data?.chars_remaining ?? Infinity;
  const chars = text.length;
  const overLimit = chars > limit;
  const overQuota = chars > remaining;
  const busy = job && (job.status === "queued" || job.status === "running");
  const canSubmit = chars > 0 && text.trim() && voice && !overLimit && !overQuota && !submitting && !busy;

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const created = await api.createTts(
        {
          text,
          voice_id: voice.id,
          speed,
          pitch_semitones: pitch,
          expressiveness,
          output_format: format,
          subtitles,
        },
        newIdempotencyKey(),
      );
      setJob(created);
      setParams({ job: created.id });
      requestAnimationFrame(() => jobRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
      usage.reload();
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  const engineLabel = (id) => (id === "mine" ? "Your cloned voices" : (engines.data || []).find((e) => e.id === id)?.name || id);

  return (
    <div className="studio">
      <PageHead kicker="Studio" title="Write it. Hear it." />

      <form className="studio__grid" onSubmit={submit}>
        <section className="panel script">
          <div className="script__head">
            <label htmlFor="script" className="label">
              Script
            </label>
            <span className={`script__count mono ${overLimit || overQuota ? "is-over" : ""}`}>
              {formatNumber(chars)} / {formatNumber(Math.min(limit, remaining))}
            </span>
          </div>
          <textarea
            id="script"
            className="script__input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste or write your voiceover script…"
            spellCheck
          />
          <p className="script__hint">
            {overLimit
              ? `Per-job limit is ${formatNumber(limit)} characters. Split long scripts into several renders.`
              : overQuota
                ? `Only ${formatNumber(remaining)} characters left this month on the ${usage.data?.plan} plan.`
                : "Punctuation shapes the pacing: full stops and question marks get longer pauses than commas."}
          </p>
        </section>

        <aside className="panel console">
          <div className="console__section">
            <label htmlFor="voice" className="label">
              Voice
            </label>
            <select id="voice" className="select" value={voiceId} onChange={(e) => setVoiceId(e.target.value)} disabled={!ready.length}>
              {groups.map(([key, list]) => (
                <optgroup key={key} label={engineLabel(key)}>
                  {list.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name} — {v.description || v.language}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            {engineInfo && (
              <p className="console__engine">
                <span className={`chip ${engineInfo.commercial_use ? "chip--ok" : "chip--warn"}`}>{engineInfo.license}</span>
                {health && !onlineEngines.has(engineInfo.id) && <span className="chip chip--muted">no worker serving {engineInfo.id}</span>}
              </p>
            )}
            <Link to="/voices" className="console__link">
              Clone a voice →
            </Link>
          </div>

          <div className="console__section faders">
            <Fader label="Speed" value={speed} min={0.5} max={2} step={0.05} onChange={setSpeed} format={(v) => `${v.toFixed(2)}×`} />
            <Fader
              label="Pitch"
              value={pitch}
              min={-6}
              max={6}
              step={0.5}
              onChange={setPitch}
              format={(v) => `${v > 0 ? "+" : ""}${v} st`}
            />
            <Fader
              label="Expressiveness"
              value={expressiveness}
              min={0.5}
              max={1.5}
              step={0.05}
              onChange={setExpressiveness}
              format={(v) => v.toFixed(2)}
              disabled={voice?.engine !== "xtts"}
              hint={voice?.engine !== "xtts" ? "XTTS voices only" : undefined}
            />
          </div>

          <div className="console__section console__row">
            <div className="segmented" role="radiogroup" aria-label="Format">
              {["mp3", "wav"].map((f) => (
                <button key={f} type="button" role="radio" aria-checked={format === f} className={format === f ? "is-on" : ""} onClick={() => setFormat(f)}>
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
            <label className="toggle">
              <input type="checkbox" checked={subtitles} onChange={(e) => setSubtitles(e.target.checked)} />
              <span>SRT subtitles</span>
            </label>
          </div>

          <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={!canSubmit}>
            {submitting ? "Queuing…" : job?.status === "queued" ? "Queued…" : busy ? "Rendering…" : "Render voiceover"}
          </button>
          {health && health.workers_online === 0 && (
            <p className="console__warn">Worker offline: you can still queue this, it will render when the GPU worker reconnects.</p>
          )}
          <ErrorNote error={error || voices.error} />
        </aside>
      </form>

      <div ref={jobRef} className="studio__job">
        {job && <JobPanel job={job} onChange={setJob} />}
      </div>
    </div>
  );
}
