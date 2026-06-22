import React from "react";

export default function ErrorBanner({ error, onDismiss }) {
  if (!error) return null;
  return (
    <div className="error-banner" role="alert">
      <span className="error-banner__icon">!</span>
      <div className="error-banner__body">
        <p className="error-banner__message">{error.message}</p>
        {error.code && <p className="error-banner__code">{error.code}</p>}
      </div>
      {onDismiss && (
        <button
          type="button"
          className="error-banner__dismiss"
          onClick={onDismiss}
          aria-label="Dismiss error"
        >
          ×
        </button>
      )}
    </div>
  );
}
