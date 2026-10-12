// Start Google sign-in: authorization code flow with PKCE, state and nonce.
import { createHash, randomBytes } from "node:crypto";

import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

import { googleRedirectUri, OAUTH_COOKIE, publicOrigin } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

const token = (bytes = 32) => randomBytes(bytes).toString("base64url");

export async function GET(req: NextRequest) {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  if (!clientId) return Response.redirect(`${publicOrigin(req)}/login?error=sso-not-configured`, 302);
  const state = token(24);
  const nonce = token(24);
  const verifier = token(48);
  (await cookies()).set(OAUTH_COOKIE, JSON.stringify({ state, nonce, verifier }), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/api/auth/google",
    maxAge: 600,
  });
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.search = new URLSearchParams({
    client_id: clientId,
    redirect_uri: googleRedirectUri(req),
    response_type: "code",
    scope: "openid email profile",
    state,
    nonce,
    code_challenge: createHash("sha256").update(verifier).digest("base64url"),
    code_challenge_method: "S256",
    prompt: "select_account",
  }).toString();
  return Response.redirect(url.toString(), 302);
}
