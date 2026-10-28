// Thin fetch client for the VOIX API.
//
// Every non-2xx response becomes an ApiError carrying the API's
// {error: {code, message, details}} envelope, so pages can branch on
// `err.code` (quota_exceeded, rate_limited, ...) instead of parsing text.

const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const TOKEN_KEY = "voix.token";

export class ApiError extends Error {
  constructor(status, code, message, details = {}, headers = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.headers = headers;
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): session-only login */
  }
}

async function request(path, { method = "GET", body, form, headers = {}, raw = false, auth = true } = {}) {
  const h = { ...headers };
  const token = getToken();
  if (auth && token) h.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    h["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let resp;
  try {
    resp = await fetch(`${BASE}${path}`, { method, headers: h, body: payload });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the VOIX API. Is it running?");
  }

  if (!resp.ok) {
    let err = { code: "http_error", message: `Request failed (${resp.status})`, details: {} };
    try {
      err = { ...err, ...(await resp.json()).error };
    } catch {
      /* non-JSON error body */
    }
    if (resp.status === 401 && auth && token) onUnauthorized();
    throw new ApiError(resp.status, err.code, err.message, err.details, resp.headers);
  }
  if (raw) return resp;
  if (resp.status === 204) return null;
  return resp.json();
}

export const api = {
  // auth
  register: (email, password) => request("/v1/auth/register", { method: "POST", body: { email, password }, auth: false }),
  login: (email, password) => request("/v1/auth/login", { method: "POST", body: { email, password }, auth: false }),
  me: () => request("/v1/auth/me"),

  // system
  health: () => request("/v1/health", { auth: false }),
  engines: () => request("/v1/engines", { auth: false }),
  usage: () => request("/v1/usage"),
  latestBenchmark: () => request("/v1/benchmarks/latest", { auth: false }),
  analytics: (days = 30) => request(`/v1/analytics?days=${days}`),

  // voices
  voices: () => request("/v1/voices"),
  voice: (id) => request(`/v1/voices/${id}`),
  cloneVoice: ({ name, language, file, consentStatement }) => {
    const form = new FormData();
    form.append("name", name);
    form.append("language", language);
    form.append("file", file);
    form.append("consent", "true");
    form.append("consent_statement", consentStatement);
    return request("/v1/voices", { method: "POST", form });
  },
  deleteVoice: (id) => request(`/v1/voices/${id}`, { method: "DELETE" }),

  // jobs
  createTts: (params, idempotencyKey) =>
    request("/v1/jobs/tts", {
      method: "POST",
      body: params,
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
    }),
  jobs: ({ cursor, status, limit = 20 } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (cursor) q.set("cursor", cursor);
    if (status) q.set("status", status);
    return request(`/v1/jobs?${q}`);
  },
  job: (id) => request(`/v1/jobs/${id}`),
  cancelJob: (id) => request(`/v1/jobs/${id}/cancel`, { method: "POST" }),
  // Downloads need the Authorization header, so they go through fetch -> Blob
  // rather than a bare <a href>/<audio src>.
  download: async (path) => (await request(path, { raw: true })).blob(),

  // api keys
  apiKeys: () => request("/v1/api-keys"),
  createApiKey: (name) => request("/v1/api-keys", { method: "POST", body: { name } }),
  revokeApiKey: (id) => request(`/v1/api-keys/${id}`, { method: "DELETE" }),
};

export const API_BASE_FOR_DOCS = BASE || window.location.origin;
