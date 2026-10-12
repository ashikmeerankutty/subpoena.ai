// Which sign-in methods the login page should offer.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ google: Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET) });
}
