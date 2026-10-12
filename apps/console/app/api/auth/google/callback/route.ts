// Finish Google sign-in: check state, exchange the code (with the PKCE verifier) for an ID token,
// and trade the ID token for a Subpoena.ai session at the API. Only the session reaches the cookie.
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

import { API, googleRedirectUri, OAUTH_COOKIE, publicOrigin, secondsUntil, setSession } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const origin = publicOrigin(req);
  const fail = (error: string, detail?: string) => {
    const q = new URLSearchParams({ error, ...(detail ? { detail } : {}) });
    return Response.redirect(`${origin}/login?${q}`, 302);
  };
  const jar = await cookies();
  const raw = jar.get(OAUTH_COOKIE)?.value;
  jar.delete({ name: OAUTH_COOKIE, path: "/api/auth/google" });
  const params = req.nextUrl.searchParams;
  if (params.get("error")) return fail("google-cancelled", params.get("error") ?? undefined);
  if (!raw) return fail("sign-in-expired");
  const pending = JSON.parse(raw) as { state: string; nonce: string; verifier: string };
  const code = params.get("code");
  if (!code || params.get("state") !== pending.state) return fail("invalid-state");

  const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: process.env.GOOGLE_CLIENT_ID ?? "",
      client_secret: process.env.GOOGLE_CLIENT_SECRET ?? "",
      redirect_uri: googleRedirectUri(req),
      grant_type: "authorization_code",
      code_verifier: pending.verifier,
    }),
    cache: "no-store",
  });
  const tokens = (await tokenRes.json().catch(() => ({}))) as { id_token?: string; error_description?: string };
  if (!tokenRes.ok || !tokens.id_token) return fail("google-exchange-failed", tokens.error_description);

  const session = await fetch(`${API}/v1/sessions/google`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ id_token: tokens.id_token, nonce: pending.nonce }),
    cache: "no-store",
  });
  const body = (await session.json().catch(() => ({}))) as { token?: string; expires_at?: string; type?: string; detail?: string };
  if (!session.ok || !body.token) return fail(body.type?.split("/").pop() ?? "sign-in-failed", body.detail);
  await setSession(body.token, secondsUntil(body.expires_at));
  return Response.redirect(`${origin}/`, 302);
}
