import React, { useState } from "react";
import { CopyButton, Empty, ErrorNote, Modal, PageHead } from "../components/ui.jsx";
import { useResource } from "../hooks/useData.js";
import { API_BASE_FOR_DOCS, api } from "../lib/api.js";
import { formatDate, timeAgo } from "../lib/format.js";

export default function ApiKeys() {
  const keys = useResource(() => api.apiKeys());
  const [name, setName] = useState("");
  const [created, setCreated] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const create = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCreated(await api.createApiKey(name.trim()));
      setName("");
      keys.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (k) => {
    if (!window.confirm(`Revoke "${k.name}"? Requests using it will start failing immediately.`)) return;
    try {
      await api.revokeApiKey(k.id);
      keys.reload();
    } catch (err) {
      setError(err);
    }
  };

  const example = `curl -X POST ${API_BASE_FOR_DOCS}/v1/jobs/tts \\
  -H "X-API-Key: vx_live_..." \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -H "Content-Type: application/json" \\
  -d '{"voice_id": "<voice id>", "text": "Hello from the VOIX API."}'`;

  return (
    <div>
      <PageHead kicker="Developers" title="API keys" />

      <form className="panel inline-form" onSubmit={create}>
        <label className="field field--grow">
          <span className="label">New key name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. production server" maxLength={100} />
        </label>
        <button type="submit" className="btn btn--primary" disabled={!name.trim() || busy}>
          Create key
        </button>
      </form>
      <ErrorNote error={error || keys.error} />

      {keys.data?.length === 0 ? (
        <Empty title="No API keys yet">
          <p>Keys let your own code create jobs and download results without a browser session.</p>
        </Empty>
      ) : (
        <div className="panel table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Key</th>
                <th>Created</th>
                <th>Last used</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(keys.data || []).map((k) => (
                <tr key={k.id} className={k.revoked_at ? "is-revoked" : ""}>
                  <td>{k.name}</td>
                  <td className="mono">vx_live_{k.prefix}_••••••••</td>
                  <td title={formatDate(k.created_at)}>{timeAgo(k.created_at)}</td>
                  <td>{k.last_used_at ? timeAgo(k.last_used_at) : "never"}</td>
                  <td className="num">
                    {k.revoked_at ? (
                      <span className="muted">revoked</span>
                    ) : (
                      <button type="button" className="btn btn--ghost btn--sm" onClick={() => revoke(k)}>
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <section className="section">
        <h2 className="section__title">Quick start</h2>
        <pre className="code">{example}</pre>
        <p className="section__note">
          The call returns <code>202</code> with a job id. Poll <code>GET /v1/jobs/&lt;id&gt;</code> until it succeeds, then
          download <code>/audio</code> and <code>/subtitles</code>. Repeating a request with the same{" "}
          <code>Idempotency-Key</code> returns the original job instead of creating a duplicate.
        </p>
      </section>

      {created && (
        <Modal title="Your new API key" onClose={() => setCreated(null)} footer={<button type="button" className="btn btn--primary" onClick={() => setCreated(null)}>I've stored it</button>}>
          <p>This is the only time the full key is shown. VOIX keeps only a hash of it.</p>
          <div className="secret">
            <code className="mono">{created.key}</code>
            <CopyButton text={created.key} />
          </div>
        </Modal>
      )}
    </div>
  );
}
