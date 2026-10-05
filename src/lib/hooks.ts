"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** Poll an async fetcher on an interval. Keeps last good data on errors. */
export function usePoll<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  opts?: { deps?: unknown[]; immediate?: boolean; enabled?: boolean }
): { data: T | null; error: string | null; refresh: () => void; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const enabled = opts?.enabled !== false;

  const run = useCallback(async () => {
    try {
      const result = await fetchRef.current();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (opts?.immediate !== false) void run();
    const id = setInterval(() => void run(), intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, ...(opts?.deps ?? [])]);

  return { data, error, refresh: () => void run(), loading };
}

export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 900px)");
    const update = () => setMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return mobile;
}
