"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, public problem: Record<string, any>) {
    super(problem?.detail ?? problem?.title ?? `HTTP ${status}`);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/v1/${path.replace(/^\//, "")}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
    cache: "no-store",
  });
  if (res.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
    location.href = "/login";
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

/** Fetch ``path`` now and every ``intervalMs`` (0 = once). Returns data, error and a reload. */
export function usePoll<T>(path: string | null, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e as Error);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    load();
    if (!intervalMs) return () => void (alive.current = false);
    const t = setInterval(load, intervalMs);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
  }, [load, intervalMs]);

  return { data, error, loading, reload: load };
}
