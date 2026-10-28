import React from "react";
import { ErrorNote, Meter, PageHead } from "../components/ui.jsx";
import { useResource } from "../hooks/useData.js";
import { api } from "../lib/api.js";
import { formatDuration, formatNumber } from "../lib/format.js";

export default function Usage() {
  const { data: u, error } = useResource(() => api.usage());
  const resets = u && new Date(u.period_end).toLocaleDateString(undefined, { day: "numeric", month: "long" });

  return (
    <div>
      <PageHead kicker="Usage" title="This month" />
      <ErrorNote error={error} />
      {u && (
        <>
          <section className="panel quota">
            <div className="quota__head">
              <span className="label">Characters</span>
              <span className="chip">{u.plan} plan</span>
            </div>
            <p className="quota__big mono">
              {formatNumber(u.chars_used)}
              <span className="quota__of"> / {formatNumber(u.chars_quota)}</span>
            </p>
            <Meter value={u.chars_used} max={u.chars_quota} label="Monthly character quota" />
            <p className="muted small">
              {formatNumber(u.chars_remaining)} left · resets {resets}. Characters are reserved when a job is queued and
              returned if it fails or is canceled.
            </p>
          </section>

          <div className="tiles">
            <div className="tile">
              <span className="tile__label">Audio generated</span>
              <span className="tile__value mono">{formatDuration(u.audio_seconds)}</span>
            </div>
            <div className="tile">
              <span className="tile__label">Successful renders</span>
              <span className="tile__value mono">{formatNumber(u.jobs_succeeded)}</span>
            </div>
            <div className="tile">
              <span className="tile__label">Max per job</span>
              <span className="tile__value mono">{formatNumber(u.limits.max_text_chars)} chars</span>
            </div>
            <div className="tile">
              <span className="tile__label">Rate limit</span>
              <span className="tile__value mono">{u.limits.rate_limit_jobs_per_minute} jobs/min</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
