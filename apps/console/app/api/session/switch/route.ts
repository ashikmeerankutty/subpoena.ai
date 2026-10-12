// Switch a Google session to another workspace the member belongs to.
import { cookies } from "next/headers";

import { API, SESSION_COOKIE, secondsUntil, setSession } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const current = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!current) return Response.json({ error: "Not signed in" }, { status: 401 });
  const res = await fetch(`${API}/v1/sessions/switch`, {
    method: "POST",
    headers: { authorization: `Bearer ${current}`, "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  const body = (await res.json().catch(() => ({}))) as { token?: string; expires_at?: string; detail?: string };
  if (!res.ok || !body.token) return Response.json({ error: body.detail ?? "Switch failed" }, { status: res.status });
  await setSession(body.token, secondsUntil(body.expires_at));
  return Response.json({ ok: true });
}
