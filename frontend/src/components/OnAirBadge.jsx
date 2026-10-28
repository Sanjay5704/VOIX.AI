import React from "react";
import { timeAgo } from "../lib/format.js";

/**
 * Studio "ON AIR" lamp for the GPU worker. Lit = at least one worker has
 * checked in recently, so queued jobs will render. Dark = jobs wait in the
 * queue until the laptop comes back.
 */
export default function OnAirBadge({ health, compact = false }) {
  if (!health) {
    return <span className="onair onair--unknown">Checking worker…</span>;
  }
  const online = health.workers_online > 0;
  const worker = health.workers?.[0];
  const title = online
    ? `${worker.name} · ${worker.gpu || "CPU"} · engines: ${worker.engines.join(", ")} · seen ${timeAgo(worker.last_seen_at)}`
    : "No GPU worker is connected. New jobs are queued and will render when it comes back online.";

  return (
    <span className={`onair ${online ? "onair--live" : "onair--off"}`} title={title} role="status">
      <span className="onair__lamp" aria-hidden="true" />
      <span className="onair__label">{online ? "On air" : "Worker offline"}</span>
      {!compact && (
        <span className="onair__meta">
          {online ? `${worker.gpu || worker.name}` : "jobs will queue"}
          {health.queue_depth > 0 && ` · ${health.queue_depth} queued`}
        </span>
      )}
    </span>
  );
}
