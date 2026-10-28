import React, { useEffect, useRef } from "react";

const STATUS_LABEL = {
  queued: "Queued",
  running: "Rendering",
  succeeded: "Done",
  failed: "Failed",
  canceled: "Canceled",
  pending: "Preparing",
  ready: "Ready",
};

export function StatusPill({ status }) {
  return <span className={`pill pill--${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

/** A mixing-desk style fader: label, live value readout, range input. */
export function Fader({ label, value, min, max, step, onChange, format = (v) => v, disabled, hint }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <label className={`fader ${disabled ? "fader--disabled" : ""}`}>
      <span className="fader__head">
        <span className="fader__label">{label}</span>
        <span className="fader__value mono">{format(value)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ "--fill": `${pct}%` }}
      />
      {hint && <span className="fader__hint">{hint}</span>}
    </label>
  );
}

export function Meter({ value, max, label, danger = 0.9 }) {
  const frac = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <div
      className={`meter ${frac >= danger ? "meter--hot" : ""}`}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
    >
      <span className="meter__fill" style={{ width: `${frac * 100}%` }} />
    </div>
  );
}

export function Modal({ title, onClose, children, footer, dismissable = true }) {
  const ref = useRef(null);
  useEffect(() => {
    const prev = document.activeElement;
    ref.current?.focus();
    const onKey = (e) => e.key === "Escape" && dismissable && onClose?.();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [onClose, dismissable]);

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && dismissable && onClose?.()}>
      <div className="modal__card" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <header className="modal__head">
          <h2>{title}</h2>
          {dismissable && (
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
              ×
            </button>
          )}
        </header>
        <div className="modal__body">{children}</div>
        {footer && <footer className="modal__foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return (
    <p className="notice notice--error" role="alert">
      {error.message}
      {error.code === "rate_limited" && error.headers?.get?.("Retry-After") && (
        <> Try again in {error.headers.get("Retry-After")} s.</>
      )}
    </p>
  );
}

export function PageHead({ kicker, title, children }) {
  return (
    <header className="page-head">
      <div>
        {kicker && <p className="kicker">{kicker}</p>}
        <h1>{title}</h1>
      </div>
      {children && <div className="page-head__aside">{children}</div>}
    </header>
  );
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {children && <div className="empty__body">{children}</div>}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <button
      type="button"
      className="btn btn--sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard blocked: user can select manually */
        }
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}
