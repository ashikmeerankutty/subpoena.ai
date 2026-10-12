// Sign in with a workspace API key (verified against /v1/me), or sign out of either kind of session.
import { cookies } from "next/headers";

import { API, SESSION_COOKIE, setSession } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const { key } = (await req.json()) as { key?: string };
  if (!key || !key.startsWith("sk_")) {
    return Response.json({ error: "Enter an API key (sk_live_… or sk_test_…)" }, { status: 400 });
  }
  const me = await fetch(`${API}/v1/me`, { headers: { authorization: `Bearer ${key}` }, cache: "no-store" });
  if (!me.ok) {
    return Response.json({ error: "That key was rejected by the API" }, { status: 401 });
  }
  await setSession(key, 60 * 60 * 12);
  return Response.json(await me.json());
}

export async function DELETE() {
  const jar = await cookies();
  const current = jar.get(SESSION_COOKIE)?.value;
  if (current?.startsWith("ss_")) {
    // Revoke Google sessions server-side; API keys stay valid (they belong to the bank's systems).
    await fetch(`${API}/v1/sessions/current`, {
      method: "DELETE",
      headers: { authorization: `Bearer ${current}` },
      cache: "no-store",
    }).catch(() => undefined);
  }
  jar.delete(SESSION_COOKIE);
  return new Response(null, { status: 204 });
}
