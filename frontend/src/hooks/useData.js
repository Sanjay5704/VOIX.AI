import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

/** Load once (and on `reload()`); `deps` re-trigger the load. */
export function useResource(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await loaderRef.current();
      setState({ data, error: null, loading: false });
      return data;
    } catch (error) {
      setState((s) => ({ ...s, error, loading: false }));
      return null;
    }
  }, []);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, reload, setData: (data) => setState((s) => ({ ...s, data })) };
}

/** Poll `fn` every `intervalMs` while `enabled`; pauses while the tab is hidden. */
export function usePolling(fn, intervalMs, enabled = true) {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    if (!enabled) return undefined;
    let timer;
    let stopped = false;
    const tick = async () => {
      if (!document.hidden) {
        try {
          await fnRef.current();
        } catch {
          /* keep polling through transient errors */
        }
      }
      if (!stopped) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [intervalMs, enabled]);
}

/** Worker/queue health, refreshed every 15 s. */
export function useHealth() {
  const [health, setHealth] = useState(null);
  usePolling(async () => {
    try {
      setHealth(await api.health());
    } catch {
      setHealth({ status: "degraded", database: "error", workers_online: 0, workers: [], queue_depth: 0 });
    }
  }, 15000);
  return health;
}

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);
export const isTerminal = (job) => job && TERMINAL.has(job.status);

/** Follow one job until it reaches a terminal state. Polls fast at first, then backs off. */
export function useJob(jobId, initial = null) {
  const [job, setJob] = useState(initial);
  const startedAt = useRef(Date.now());

  useEffect(() => {
    setJob(initial);
    startedAt.current = Date.now();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  useEffect(() => {
    if (!jobId) return undefined;
    let timer;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (stopped) return;
        setJob(j);
        if (isTerminal(j)) return;
      } catch {
        /* transient: retry */
      }
      const age = Date.now() - startedAt.current;
      const delay = age < 30_000 ? 1000 : age < 120_000 ? 2500 : 5000;
      if (!stopped) timer = setTimeout(tick, delay);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return [job, setJob];
}

/** Fetch an authenticated file into an object URL (revoked on change/unmount). */
export function useBlobUrl(path) {
  const [state, setState] = useState({ url: null, blob: null, error: null });
  useEffect(() => {
    if (!path) {
      setState({ url: null, blob: null, error: null });
      return undefined;
    }
    let url = null;
    let cancelled = false;
    api
      .download(path)
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setState({ url, blob, error: null });
      })
      .catch((error) => !cancelled && setState({ url: null, blob: null, error }));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);
  return state;
}
