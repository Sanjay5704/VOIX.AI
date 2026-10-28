import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import OnAirBadge from "../components/OnAirBadge.jsx";
import { ErrorNote } from "../components/ui.jsx";
import { api } from "../lib/api.js";

export default function AuthPage({ mode }) {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [health, setHealth] = useState(null);
  const isLogin = mode === "login";

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (isLogin ? login : register)(email, password);
      navigate(location.state?.from || "/studio", { replace: true });
    } catch (err) {
      setError(err.code === "validation_error" ? { message: err.details.errors?.[0]?.msg || err.message } : err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth__hero">
        <div className="brand brand--big">
          <span className="brand__mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          <span className="brand__name">VOIX</span>
        </div>
        <h1 className="auth__title">
          Scripts in.
          <br />
          <em>Voiceovers</em> out.
        </h1>
        <p className="auth__lede">
          Paste a script, pick or clone a voice, and get broadcast-ready audio with subtitles. The same engine is
          available as a REST API.
        </p>
        <ul className="auth__facts mono">
          <li>queue → GPU worker → audio + SRT</li>
          <li>Kokoro-82M · XTTS-v2</li>
          <li>API keys · quotas · idempotent jobs</li>
        </ul>
        {health && <OnAirBadge health={health} />}
      </section>

      <section className="auth__panel">
        <form className="auth__form" onSubmit={submit}>
          <h2>{isLogin ? "Sign in" : "Create your account"}</h2>
          <label className="field">
            <span className="label">Email</span>
            <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Password</span>
            <input
              className="input"
              type="password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              required
              minLength={isLogin ? undefined : 8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {!isLogin && <span className="small muted">At least 8 characters.</span>}
          </label>
          <ErrorNote error={error} />
          <button className="btn btn--primary btn--block btn--lg" type="submit" disabled={busy}>
            {busy ? "One moment…" : isLogin ? "Sign in" : "Create account"}
          </button>
          <p className="small muted">
            {isLogin ? (
              <>
                New here? <Link to="/register">Create an account</Link> (free: 20,000 characters/month)
              </>
            ) : (
              <>
                Already have an account? <Link to="/login">Sign in</Link>
              </>
            )}
          </p>
        </form>
      </section>
    </div>
  );
}
