// Which sign-in methods the login page should offer, and the API URL for "Copy as curl".
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({
    google: Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET),
    api_url: process.env.SUBPOENA_API_URL ?? "http://localhost:8000",
  });
}
