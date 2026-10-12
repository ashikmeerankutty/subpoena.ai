"use client";

import { Alert } from "@twilio-paste/core/alert";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Disclosure, DisclosureContent, DisclosureHeading } from "@twilio-paste/core/disclosure";
import { HelpText } from "@twilio-paste/core/help-text";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Separator } from "@twilio-paste/core/separator";
import { Text } from "@twilio-paste/core/text";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const ERRORS: Record<string, string> = {
  "not-a-member": "Your Google account is not a member of any workspace. Ask a workspace admin to add you.",
  "unverified-email": "Your Google account email is not verified.",
  "invalid-state": "The sign-in link expired or was tampered with. Please try again.",
  "sign-in-expired": "The sign-in took too long. Please try again.",
  "google-cancelled": "Google sign-in was cancelled.",
  "sso-not-configured": "Google sign-in is not configured for this Console.",
};

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [google, setGoogle] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("/api/auth/config").then((r) => r.json()).then((c: { google: boolean }) => setGoogle(c.google)).catch(() => setGoogle(false));
    const slug = params.get("error");
    if (slug) setError(ERRORS[slug] ?? params.get("detail") ?? "Sign-in failed. Please try again.");
  }, [params]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/session", { method: "POST", body: JSON.stringify({ key: key.trim() }) });
    setBusy(false);
    if (res.ok) router.replace("/");
    else setError(((await res.json()) as { error: string }).error);
  }

  const keyForm = (
    <Box as="form" onSubmit={submit}>
      <Label htmlFor="key" required>Workspace API key</Label>
      <Input id="key" name="key" type="password" value={key} placeholder="sk_live_…"
        onChange={(e) => setKey(e.target.value)} required />
      <HelpText>Admin keys can manage keys and policies; analyst keys can override verdicts.</HelpText>
      <Box marginTop="space50">
        <Button variant={google ? "secondary" : "primary"} type="submit" fullWidth loading={busy}>Sign in with API key</Button>
      </Box>
    </Box>
  );

  return (
    <Box minHeight="100vh" display="flex" alignItems="center" justifyContent="center" backgroundColor="colorBackgroundInverse">
      <Box backgroundColor="colorBackgroundBody" borderRadius="borderRadius30" padding="space100" boxShadow="shadowHigh"
        style={{ width: 420 }}>
        <Box display="flex" alignItems="center" columnGap="space30" marginBottom="space70">
          <img src="/favicon.svg" alt="" width={36} height={36} />
          <Box>
            <Text as="div" fontWeight="fontWeightBold" fontSize="fontSize50">Courthouse Console</Text>
            <Text as="div" color="colorTextWeak" fontSize="fontSize20">Subpoena.ai</Text>
          </Box>
        </Box>
        {error ? <Box marginBottom="space50"><Alert variant="error"><Text as="span">{error}</Text></Alert></Box> : null}
        {google ? (
          <>
            <Button variant="primary" fullWidth onClick={() => { location.href = "/api/auth/google/start"; }}>
              <Box as="span" display="inline-flex" alignItems="center" justifyContent="center" backgroundColor="colorBackgroundBody"
                borderRadius="borderRadiusCircle" padding="space10"><GoogleMark /></Box>
              Sign in with Google
            </Button>
            <Box marginY="space70"><Separator orientation="horizontal" /></Box>
            <Disclosure variant="contained">
              <DisclosureHeading as="h3" variant="heading60">Use an API key instead</DisclosureHeading>
              <DisclosureContent>{keyForm}</DisclosureContent>
            </Disclosure>
          </>
        ) : google === false ? keyForm : null}
      </Box>
    </Box>
  );
}

export default function Login() {
  return <Suspense><LoginForm /></Suspense>;
}
