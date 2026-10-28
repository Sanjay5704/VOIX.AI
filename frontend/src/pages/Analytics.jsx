import React, { useState } from "react";
import { DailyBars, seriesColor } from "../components/charts.jsx";
import { Empty, ErrorNote, PageHead } from "../components/ui.jsx";
import { useResource } from "../hooks/useData.js";
import { api } from "../lib/api.js";
import { formatDuration, formatNumber } from "../lib/format.js";

const RANGES = [7, 30, 90];
const ms = (v) => (v == null ? "—" : v >= 10_000 ? `${(v / 1000).toFixed(1)} s` : `${formatNumber(Math.round(v))} ms`);
const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

export default function Analytics() {
  const [days, setDays] = useState(30);
  const { data, error } = useResource(() => api.analytics(days), [days]);

  if (error?.status === 403) {
    return (
      <div>
        <PageHead kicker="Analytics" title="Platform health" />
        <Empty title="Operators only">
          <p>
            Ask an operator to run <code>python -m voix_api.admin promote &lt;email&gt;</code>.
          </p>
        </Empty>
      </div>
    );
  }

  const t = data?.totals;
  const engines = data ? Object.entries(data.engines) : [];

  return (
    <div>
      <PageHead kicker="Analytics" title="Platform health">
        <div className="segmented" role="radiogroup" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r} type="button" role="radio" aria-checked={days === r} className={days === r ? "is-on" : ""} onClick={() => setDays(r)}>
              {r}d
            </button>
          ))}
        </div>
      </PageHead>
      <ErrorNote error={error} />
      {data && (
        <>
          <p className="section__note">
            From the <code>stg_jobs → fct_daily_activity / fct_engine_daily</code> views since {data.window.since}.
            Percentiles are nearest-rank over finished jobs.
          </p>
          <div className="tiles">
            <Tile label="Active users" value={formatNumber(t.active_users)} />
            <Tile label="Jobs" value={formatNumber(t.jobs)} />
            <Tile label="Characters rendered" value={formatNumber(t.chars)} />
            <Tile label="Audio rendered" value={formatDuration(t.audio_seconds)} />
            <Tile label="Failure rate" value={pct(t.failure_rate)} />
          </div>

          <section className="section">
            <h2 className="section__title">Engines</h2>
            {engines.length === 0 ? (
              <Empty title="No finished synthesis jobs in this window" />
            ) : (
              <div className="panel table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Engine</th>
                      <th className="num">Jobs</th>
                      <th className="num">Failed</th>
                      <th className="num">Failure rate</th>
                      <th className="num">Render p50</th>
                      <th className="num">Render p95</th>
                      <th className="num">Queue p50</th>
                      <th className="num">Queue p95</th>
                      <th className="num">Median RTF</th>
                    </tr>
                  </thead>
                  <tbody>
                    {engines.map(([name, e]) => (
                      <tr key={name}>
                        <td>
                          <span className="legend__swatch" style={{ background: seriesColor(name) }} /> {name}
                        </td>
                        <td className="num mono">{formatNumber(e.jobs)}</td>
                        <td className="num mono">{formatNumber(e.failed)}</td>
                        <td className="num mono">{pct(e.failure_rate)}</td>
                        <td className="num mono">{ms(e.p50_processing_ms)}</td>
                        <td className="num mono">{ms(e.p95_processing_ms)}</td>
                        <td className="num mono">{ms(e.p50_queue_ms)}</td>
                        <td className="num mono">{ms(e.p95_queue_ms)}</td>
                        <td className="num mono">{e.median_synthesis_rtf?.toFixed(3) ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="section panel chart-panel">
            <h2 className="section__title">Jobs per day</h2>
            <DailyBars points={data.daily.map((d) => ({ day: d.day, value: d.jobs }))} format={formatNumber} label="Jobs per day" />
          </section>

          <section className="section">
            <h2 className="section__title">Daily detail</h2>
            <div className="panel table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Day</th>
                    <th className="num">Active users</th>
                    <th className="num">Jobs</th>
                    <th className="num">Chars requested</th>
                    <th className="num">Audio</th>
                    <th className="num">Failed</th>
                    <th className="num">Voice clones</th>
                  </tr>
                </thead>
                <tbody>
                  {data.daily
                    .slice()
                    .reverse()
                    .map((d) => (
                      <tr key={d.day}>
                        <td className="mono">{d.day}</td>
                        <td className="num mono">{formatNumber(d.active_users)}</td>
                        <td className="num mono">{formatNumber(d.jobs)}</td>
                        <td className="num mono">{formatNumber(d.chars_requested)}</td>
                        <td className="num mono">{formatDuration(d.audio_seconds)}</td>
                        <td className="num mono">{formatNumber(d.failed)}</td>
                        <td className="num mono">{formatNumber(d.voice_clones)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function Tile({ label, value }) {
  return (
    <div className="tile">
      <span className="tile__label">{label}</span>
      <span className="tile__value mono">{value}</span>
    </div>
  );
}
