import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import JobPanel from "../components/JobPanel.jsx";
import { Empty, ErrorNote, PageHead, StatusPill } from "../components/ui.jsx";
import { useJob } from "../hooks/useData.js";
import { api } from "../lib/api.js";
import { formatDate, formatDuration, formatNumber, timeAgo } from "../lib/format.js";

const FILTERS = ["", "succeeded", "running", "queued", "failed", "canceled"];

export function History() {
  const [status, setStatus] = useState("");
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(
    async (next = null) => {
      setLoading(true);
      setError(null);
      try {
        const page = await api.jobs({ cursor: next, status: status || undefined });
        setItems((prev) => (next ? [...prev, ...page.items] : page.items));
        setCursor(page.next_cursor);
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    },
    [status],
  );

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHead kicker="History" title="Every render, on the record">
        <div className="segmented segmented--wrap" role="radiogroup" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button key={f || "all"} type="button" role="radio" aria-checked={status === f} className={status === f ? "is-on" : ""} onClick={() => setStatus(f)}>
              {f || "all"}
            </button>
          ))}
        </div>
      </PageHead>

      <ErrorNote error={error} />
      {!loading && items.length === 0 ? (
        <Empty title="Nothing here yet">
          <Link className="btn btn--primary" to="/studio">
            Render your first voiceover
          </Link>
        </Empty>
      ) : (
        <div className="panel table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Script</th>
                <th className="num">Chars</th>
                <th className="num">Audio</th>
                <th className="hide-sm">Engine</th>
                <th className="hide-sm">Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.id}>
                  <td>
                    <StatusPill status={j.status} />
                  </td>
                  <td className="table__script">
                    <Link to={`/jobs/${j.id}`}>{j.type === "synthesize" ? j.params.text : "Voice preparation"}</Link>
                  </td>
                  <td className="num mono">{j.type === "synthesize" ? formatNumber(j.char_count) : "—"}</td>
                  <td className="num mono">{j.result?.duration_seconds != null ? formatDuration(j.result.duration_seconds) : "—"}</td>
                  <td className="mono hide-sm">{j.engine}</td>
                  <td className="hide-sm" title={formatDate(j.created_at)}>
                    {timeAgo(j.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cursor && (
        <div className="load-more">
          <button type="button" className="btn" onClick={() => load(cursor)} disabled={loading}>
            {loading ? "Loading…" : "Load older"}
          </button>
        </div>
      )}
    </div>
  );
}

export function JobDetail() {
  const { id } = useParams();
  const [job, setJob] = useJob(id);

  return (
    <div>
      <PageHead kicker={<Link to="/history">← History</Link>} title={job?.type === "prepare_voice" ? "Voice preparation" : "Render"} />
      {!job ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          {job.type === "synthesize" && (
            <section className="panel quote">
              <p>{job.params.text}</p>
              <p className="quote__meta mono">
                {job.params.speed}× · {job.params.pitch_semitones > 0 ? "+" : ""}
                {job.params.pitch_semitones} st · {job.params.output_format} · {formatNumber(job.char_count)} chars · {formatDate(job.created_at)}
              </p>
            </section>
          )}
          <JobPanel job={job} onChange={setJob} />
        </>
      )}
    </div>
  );
}
