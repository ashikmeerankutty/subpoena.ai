// Same-origin proxy to the Subpoena.ai API. The API key or Google session lives only in an httpOnly cookie.
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

import { API, SESSION_COOKIE } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

const FORWARD = ["content-type", "accept", "idempotency-key"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const key = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!key) {
    return Response.json(
      { type: "about:blank", title: "Unauthorized", status: 401 },
      { status: 401, headers: { "content-type": "application/problem+json" } },
    );
  }
  const { path } = await ctx.params;
  const url = `${API}/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers({ authorization: `Bearer ${key}` });
  for (const h of FORWARD) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const upstream = await fetch(url, {
    method: req.method,
    headers,
    body: hasBody ? await req.text() : undefined,
    cache: "no-store",
    signal: req.signal,
  });
  const out = new Headers();
  for (const h of ["content-type", "cache-control", "idempotent-replayed"]) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
