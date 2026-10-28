import React, { useState } from "react";

/**
 * Small hand-rolled SVG/HTML charts (no chart library).
 * Series colours come from --series-N tokens (validated for CVD separation in
 * both themes); text always uses text tokens, never the series colour.
 */

export const ENGINE_SLOT = { kokoro: 1, xtts: 2, mock: 3 };
export const seriesColor = (engine) => `var(--series-${ENGINE_SLOT[engine] ?? 3})`;

export function Legend({ items }) {
  if (items.length < 2) return null;
  return (
    <ul className="legend">
      {items.map((it) => (
        <li key={it.key}>
          <span className="legend__swatch" style={{ background: seriesColor(it.key) }} />
          {it.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Horizontal grouped bars: one row per category, one bar per series.
 * rows: [{ key, label, values: { [series]: number|null } }]
 */
export function GroupedBars({ rows, series, format = (v) => v, label }) {
  const [hover, setHover] = useState(null);
  const max = Math.max(1e-9, ...rows.flatMap((r) => series.map((s) => r.values[s] ?? 0)));
  return (
    <figure className="chart" aria-label={label}>
      <Legend items={series.map((s) => ({ key: s, label: s }))} />
      <div className="hbars" role="table" aria-label={label}>
        {rows.map((r) => (
          <div className="hbars__row" role="row" key={r.key}>
            <div className="hbars__label" role="rowheader">
              {r.label}
            </div>
            <div className="hbars__bars">
              {series.map((s) => {
                const v = r.values[s];
                const pct = v == null ? 0 : (v / max) * 100;
                const id = `${r.key}:${s}`;
                return (
                  <div
                    className={`hbars__track ${hover === id ? "is-hover" : ""}`}
                    role="cell"
                    key={s}
                    onMouseEnter={() => setHover(id)}
                    onMouseLeave={() => setHover(null)}
                    title={`${r.label} · ${s}: ${v == null ? "n/a" : format(v)}`}
                  >
                    {/* bars use at most 75% of the track so the value label always fits */}
                    <span className="hbars__bar" style={{ width: `max(${pct * 0.75}%, 3px)`, background: seriesColor(s) }} />
                    <span className="hbars__value mono">
                      {s} {v == null ? "—" : format(v)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </figure>
  );
}

/** Vertical bars over days for one measure. points: [{ day, value }] */
export function DailyBars({ points, format = (v) => v, label, height = 160 }) {
  const [hover, setHover] = useState(null);
  if (!points.length) return <p className="muted small">No data in this window.</p>;
  const max = Math.max(1, ...points.map((p) => p.value));
  const ticks = [0, max / 2, max];
  return (
    <figure className="chart" aria-label={label}>
      <div className="vbars" style={{ height }}>
        <div className="vbars__grid" aria-hidden="true">
          {ticks
            .slice()
            .reverse()
            .map((t) => (
              <span key={t} className="mono">
                {format(Math.round(t))}
              </span>
            ))}
        </div>
        <div className="vbars__plot">
          {points.map((p, i) => (
            <div
              key={p.day}
              className="vbars__col"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              tabIndex={0}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              aria-label={`${p.day}: ${format(p.value)}`}
            >
              <span className="vbars__bar" style={{ height: `${(p.value / max) * 100}%` }} />
              {hover === i && (
                <span className="tooltip" role="tooltip">
                  <strong>{format(p.value)}</strong>
                  <span>{p.day}</span>
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="vbars__axis mono" aria-hidden="true">
        <span>{points[0].day}</span>
        {points.length > 1 && <span>{points[points.length - 1].day}</span>}
      </div>
    </figure>
  );
}
