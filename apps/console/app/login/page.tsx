"use client";

import { Alert } from "@twilio-paste/core/alert";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { HelpText } from "@twilio-paste/core/help-text";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Text } from "@twilio-paste/core/text";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Login() {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/session", { method: "POST", body: JSON.stringify({ key: key.trim() }) });
    setBusy(false);
    if (res.ok) router.replace("/");
    else setError(((await res.json()) as { error: string }).error);
  }

  return (
    <Box minHeight="100vh" display="flex" alignItems="center" justifyContent="center" backgroundColor="colorBackgroundInverse">
      <Box as="form" onSubmit={submit} backgroundColor="colorBackgroundBody" borderRadius="borderRadius30"
        padding="space100" boxShadow="shadowHigh" style={{ width: 420 }}>
        <Box display="flex" alignItems="center" columnGap="space30" marginBottom="space70">
          <img src="/favicon.svg" alt="" width={36} height={36} />
          <Box>
            <Text as="div" fontWeight="fontWeightBold" fontSize="fontSize50">Courthouse Console</Text>
            <Text as="div" color="colorTextWeak" fontSize="fontSize20">Subpoena.ai</Text>
          </Box>
        </Box>
        {error ? <Box marginBottom="space50"><Alert variant="error"><Text as="span">{error}</Text></Alert></Box> : null}
        <Label htmlFor="key" required>Workspace API key</Label>
        <Input id="key" name="key" type="password" value={key} placeholder="sk_live_…"
          onChange={(e) => setKey(e.target.value)} required />
        <HelpText>Admin keys can manage keys and policies; analyst keys can override verdicts.</HelpText>
        <Box marginTop="space70">
          <Button variant="primary" type="submit" fullWidth loading={busy}>Sign in</Button>
        </Box>
      </Box>
    </Box>
  );
}
