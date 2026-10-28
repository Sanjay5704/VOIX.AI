export function formatClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatNumber(n) {
  return new Intl.NumberFormat().format(n ?? 0);
}

export function formatDuration(seconds) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const UNITS = [
  ["year", 31536000],
  ["month", 2592000],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

export function timeAgo(iso) {
  if (!iso) return "";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  for (const [unit, secs] of UNITS) {
    if (Math.abs(diff) >= secs || unit === "second") return rtf.format(Math.round(diff / secs), unit);
  }
  return "";
}

export function formatDate(iso) {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
}

export function newIdempotencyKey() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
