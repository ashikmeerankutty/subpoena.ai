// Server-only helpers for Console sign-in (API keys or Google sessions in one httpOnly cookie).
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

export const API = process.env.SUBPOENA_API_URL ?? "http://localhost:8000";
export const SESSION_COOKIE = "subpoena_key";
export const OAUTH_COOKIE = "subpoena_oauth";

/** Public origin of the Console (Cloud Run sits behind a proxy, so prefer the configured URL). */
export function publicOrigin(req: NextRequest): string {
  return (process.env.CONSOLE_PUBLIC_URL ?? req.nextUrl.origin).replace(/\/$/, "");
}

export const googleRedirectUri = (req: NextRequest) => `${publicOrigin(req)}/api/auth/google/callback`;

export async function setSession(token: string, maxAgeSeconds: number) {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: maxAgeSeconds,
  });
}

/** Seconds until ``iso`` (at least one minute), for cookie lifetimes that match the session. */
export const secondsUntil = (iso: string | null | undefined, fallback = 60 * 60 * 12) =>
  iso ? Math.max(60, Math.floor((new Date(iso).getTime() - Date.now()) / 1000)) : fallback;
