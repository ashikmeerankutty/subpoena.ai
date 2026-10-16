// Which sign-in methods the login page should offer, the API URL for "Copy as curl", and the
// public demo login (an analyst key in a sandbox workspace) when DEMO_LOGIN_KEY is set.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({
    google: Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET),
    api_url: process.env.SUBPOENA_API_URL ?? "http://localhost:8000",
    demo_key: process.env.DEMO_LOGIN_KEY || null,
  });
}
