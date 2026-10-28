import React, { useMemo, useState } from "react";
import { GroupedBars, seriesColor } from "../components/charts.jsx";
import { Empty, ErrorNote, PageHead } from "../components/ui.jsx";
import { useResource } from "../hooks/useData.js";
import { api } from "../lib/api.js";
import { formatDate, formatNumber } from "../lib/format.js";

const METRICS = {
  rtf: { label: "Synthesis RTF", hint: "seconds of compute per second of audio · lower is faster", get: (r) => r.rtf, fmt: (v) => v.toFixed(3) },
  wer: { label: "Word error rate", hint: "Whisper transcript vs script · lower is clearer", get: (r) => r.wer, fmt: (v) => `${(v * 100).toFixed(1)}%` },
  latency: { label: "Synthesis time", hint: "median of repeats, milliseconds", get: (r) => r.synthesis_ms_p50, fmt: (v) => `${formatNumber(Math.round(v))} ms` },
};

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

export default function Benchmarks() {
  const run = useResource(() => api.latestBenchmark());
  const engines = useResource(() => api.engines());
  const [metric, setMetric] = useState("rtf");

  const data = run.data?.results;
  const names = data ? Object.keys(data.engines) : [];
  const scripts = data ? data.engines[names[0]].scripts : [];
  const info = (id) => (engines.data || []).find((e) => e.id === id);

  const rows = useMemo(
    () =>
      scripts.map((s) => ({
        key: s.id,
        label: s.id,
        values: Object.fromEntries(
          names.map((n) => [n, METRICS[metric].get(data.engines[n].scripts.find((x) => x.id === s.id)) ?? null]),
        ),
      })),
    [scripts, names, data, metric],
  );

  if (run.error?.status === 404) {
    return (
      <div>
        <PageHead kicker="Benchmarks" title="Engines, measured" />
        <Empty title="No benchmark uploaded yet">
          <p>
            Run <code>python -m benchmarks.run_benchmark --upload</code> on a worker host to publish one.
          </p>
        </Empty>
      </div>
    );
  }

  return (
    <div>
      <PageHead kicker="Benchmarks" title="Engines, measured" />
      <ErrorNote error={run.error && run.error.status !== 404 ? run.error : null} />
      {data && (
        <>
          <p className="section__note">
            {data.hardware.gpu} · {data.hardware.os} · torch {data.hardware.torch} · {data.settings.repeats} repeats per
            script · quality via {data.settings.asr_model} · run {formatDate(data.started_at)}
          </p>

          <div className="engine-cards">
            {names.map((n) => {
              const e = data.engines[n];
              const sm = e.summary;
              const meta = info(n);
              return (
                <article key={n} className="card engine-card">
                  <header className="engine-card__head">
                    <span className="legend__swatch" style={{ background: seriesColor(n) }} />
                    <h3>{meta?.name || n}</h3>
                    {meta && <span className={`chip ${meta.commercial_use ? "chip--ok" : "chip--warn"}`}>{meta.license}</span>}
                  </header>
                  <dl className="engine-card__stats">
                    <div>
                      <dt>× real time</dt>
                      <dd className="mono">{sm.x_realtime}×</dd>
                    </div>
                    <div>
                      <dt>WER</dt>
                      <dd className="mono">{pct(sm.wer)}</dd>
                    </div>
                    <div>
                      <dt>Peak VRAM</dt>
                      <dd className="mono">{e.peak_vram_mb != null ? `${formatNumber(Math.round(e.peak_vram_mb))} MB` : "—"}</dd>
                    </div>
                    <div>
                      <dt>Load</dt>
                      <dd className="mono">{(e.load_ms / 1000).toFixed(1)} s</dd>
                    </div>
                    <div>
                      <dt>Short line</dt>
                      <dd className="mono">{formatNumber(sm.latency_ms_short)} ms</dd>
                    </div>
                    <div>
                      <dt>Voice</dt>
                      <dd className="mono">{e.voice}</dd>
                    </div>
                  </dl>
                </article>
              );
            })}
          </div>

          <section className="section panel chart-panel">
            <header className="chart-panel__head">
              <div>
                <h2 className="section__title">{METRICS[metric].label} by script</h2>
                <p className="section__note">{METRICS[metric].hint}</p>
              </div>
              <div className="segmented" role="radiogroup" aria-label="Metric">
                {Object.entries(METRICS).map(([k, m]) => (
                  <button key={k} type="button" role="radio" aria-checked={metric === k} className={metric === k ? "is-on" : ""} onClick={() => setMetric(k)}>
                    {k}
                  </button>
                ))}
              </div>
            </header>
            <GroupedBars rows={rows} series={names} format={METRICS[metric].fmt} label={`${METRICS[metric].label} by script and engine`} />
          </section>

          <section className="section">
            <h2 className="section__title">What Whisper heard</h2>
            <p className="section__note">
              Transcripts of each render, scored against the text the engine was asked to say. WER measures intelligibility,
              not naturalness.
            </p>
            <div className="panel table-wrap">
              <table className="table table--wrap">
                <thead>
                  <tr>
                    <th>Script</th>
                    <th>Engine</th>
                    <th className="num">Audio</th>
                    <th className="num">RTF</th>
                    <th className="num">WER</th>
                    <th>Transcript</th>
                  </tr>
                </thead>
                <tbody>
                  {scripts.flatMap((s) =>
                    names.map((n) => {
                      const r = data.engines[n].scripts.find((x) => x.id === s.id);
                      return (
                        <tr key={`${s.id}-${n}`}>
                          <td className="mono">{s.id}</td>
                          <td>
                            <span className="legend__swatch" style={{ background: seriesColor(n) }} /> {n}
                          </td>
                          <td className="num mono">{r.audio_seconds.toFixed(1)} s</td>
                          <td className="num mono">{r.rtf?.toFixed(3)}</td>
                          <td className="num mono">{pct(r.wer)}</td>
                          <td className="transcript">{r.transcript ?? "—"}</td>
                        </tr>
                      );
                    }),
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
