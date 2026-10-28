import React, { useState } from "react";
import { api } from "../lib/api.js";
import { formatDuration, timeAgo } from "../lib/format.js";
import AudioPlayer from "./AudioPlayer.jsx";
import { useWorkerHealth } from "./Layout.jsx";
import { StatusPill } from "./ui.jsx";

const STAGES = ["queued", "running", "succeeded"];

/** Live view of one job: stage track, progress, then the player or the error. */
export default function JobPanel({ job, onChange }) {
  const health = useWorkerHealth();
  const [canceling, setCanceling] = useState(false);
  if (!job) return null;

  const workerOffline = health && health.workers_online === 0;
  const stageIndex = STAGES.indexOf(job.status);
  const metrics = job.result?.metrics;

  const cancel = async () => {
    setCanceling(true);
    try {
      onChange?.(await api.cancelJob(job.id));
    } finally {
      setCanceling(false);
    }
  };

  return (
    <section className="job" aria-live="polite">
      <header className="job__head">
        <StatusPill status={job.status} />
        <span className="job__id mono">job {job.id.slice(0, 8)}</span>
        <span className="job__when">{timeAgo(job.created_at)}</span>
        {(job.status === "queued" || job.status === "running") && (
          <button type="button" className="btn btn--ghost btn--sm job__cancel" onClick={cancel} disabled={canceling || job.cancel_requested}>
            {job.cancel_requested ? "Stopping…" : "Cancel"}
          </button>
        )}
      </header>

      {job.status !== "failed" && job.status !== "canceled" && (
        <ol className="track">
          {STAGES.map((s, i) => (
            <li key={s} className={`track__step ${i < stageIndex || job.status === "succeeded" ? "is-done" : ""} ${i === stageIndex && job.status !== "succeeded" ? "is-now" : ""}`}>
              {s === "queued" ? "Queued" : s === "running" ? "Rendering on GPU" : "Ready"}
            </li>
          ))}
        </ol>
      )}

      {job.status === "queued" && (
        <p className="job__note">
          {workerOffline
            ? "The GPU worker is offline. This job is safely queued and will render as soon as it reconnects."
            : job.attempts > 0
              ? `Retrying (attempt ${job.attempts + 1} of ${job.max_attempts}). ${job.error ?? ""}`
              : "Waiting for the worker to pick this up…"}
        </p>
      )}

      {job.status === "running" && job.progress === 0 && (
        <p className="job__note">Warming up: the worker is loading the voice model onto the GPU…</p>
      )}
      {job.status === "running" && (
        <div className="progress" aria-label="Render progress">
          <span className="progress__bar" style={{ width: `${Math.max(3, job.progress * 100)}%` }} />
          <span className="progress__label mono">{Math.round(job.progress * 100)}%</span>
        </div>
      )}

      {job.status === "failed" && <p className="notice notice--error">{job.error || "The job failed."}</p>}
      {job.status === "canceled" && <p className="job__note">Canceled. Reserved characters were returned to your quota.</p>}

      {job.status === "succeeded" && job.type === "synthesize" && (
        <>
          <AudioPlayer job={job} />
          {metrics && (
            <dl className="stats">
              <div>
                <dt>Audio</dt>
                <dd>{formatDuration(job.result.duration_seconds)}</dd>
              </div>
              <div>
                <dt>Render time</dt>
                <dd>{formatDuration(metrics.processing_ms / 1000)}</dd>
              </div>
              <div>
                <dt>Real-time factor</dt>
                <dd title="Synthesis time ÷ audio length. Below 1 = faster than real time.">{metrics.synthesis_rtf?.toFixed(2) ?? "—"}</dd>
              </div>
              <div>
                <dt>Engine</dt>
                <dd>
                  {metrics.engine} · {metrics.device ?? "—"}
                </dd>
              </div>
            </dl>
          )}
        </>
      )}
    </section>
  );
}
