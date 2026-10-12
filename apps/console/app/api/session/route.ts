// Sign in with a workspace API key: verified against /v1/me, then stored in an httpOnly cookie.
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

const API = process.env.SUBPOENA_API_URL ?? "http://localhost:8000";

export async function POST(req: Request) {
  const { key } = (await req.json()) as { key?: string };
  if (!key || !key.startsWith("sk_")) {
    return Response.json({ error: "Enter an API key (sk_live_… or sk_test_…)" }, { status: 400 });
  }
  const me = await fetch(`${API}/v1/me`, { headers: { authorization: `Bearer ${key}` }, cache: "no-store" });
  if (!me.ok) {
    return Response.json({ error: "That key was rejected by the API" }, { status: 401 });
  }
  (await cookies()).set("subpoena_key", key, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 12,
  });
  return Response.json(await me.json());
}

export async function DELETE() {
  (await cookies()).delete("subpoena_key");
  return new Response(null, { status: 204 });
}
