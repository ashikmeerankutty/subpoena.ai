"use client";

import { Alert } from "@twilio-paste/core/alert";
import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Checkbox, CheckboxGroup } from "@twilio-paste/core/checkbox";
import { CodeBlock, CodeBlockHeader, CodeBlockTab, CodeBlockTabList, CodeBlockTabPanel, CodeBlockWrapper } from "@twilio-paste/core/code-block";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Modal, ModalBody, ModalFooter, ModalFooterActions, ModalHeader, ModalHeading } from "@twilio-paste/core/modal";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useState } from "react";

import { useToast } from "@/app/providers";
import { Kpi, KpiGrid } from "@/components/Kpi";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { api, usePoll } from "@/lib/api";
import { ago, pct } from "@/lib/format";

interface Key { id: string; name: string; prefix: string; scopes: string[]; created_at: string; last_used_at: string | null; revoked_at: string | null }
interface Sources { api_base_url: string; api_keys: Key[]; webhook_signing_secret: string; snippets: Record<string, string> }

const SCOPES = ["evaluations:write", "evaluations:read", "evaluations:override", "admin"];

export default function SourcesPage() {
  const me = useMe();
  const toast = useToast();
  const admin = me?.role === "ADMIN";
  const { data, reload } = usePoll<Sources>(admin ? "sources" : null);
  const { data: stats } = usePoll<any>("stats/overview?hours=24", 10000);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["evaluations:write", "evaluations:read"]);
  const [secret, setSecret] = useState<string | null>(null);
  const [showWebhook, setShowWebhook] = useState(false);

  async function create() {
    try {
      const k = await api<{ secret: string }>("api-keys", { method: "POST", body: JSON.stringify({ name, scopes }) });
      setSecret(k.secret);
      setName("");
      reload();
    } catch (e) {
      toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 5000 });
    }
  }

  async function revoke(k: Key) {
    await api(`api-keys/${k.id}`, { method: "DELETE" });
    toast.push({ message: `Revoked ${k.name}`, variant: "warning", dismissAfter: 4000 });
    reload();
  }

  if (me && !admin) {
    return <><PageHeader title="Sources" /><Alert variant="neutral"><Text as="span">Only workspace admins can manage API keys.</Text></Alert></>;
  }

  return (
    <>
      <PageHeader title="Sources" description="How your bank backend sends transactions: REST source, API keys and integration snippets."
        actions={<Button variant="primary" onClick={() => setCreating(true)}>Create API key</Button>} />
      <Panel title={<Box display="flex" columnGap="space30" alignItems="center">REST API <Badge as="span" variant="success" size="small">Healthy</Badge></Box>}>
        <KpiGrid>
          <Kpi label="Endpoint" value={<Text as="span" fontSize="fontSize30"><code>{data?.api_base_url}/evaluations</code></Text>} />
          <Kpi label="Ingest (24h)" value={stats?.evaluations ?? "—"} hint={`${stats?.evaluations_per_hour ?? 0}/hour`} />
          <Kpi label="Sent to court" value={pct(stats ? stats.sent_to_court / Math.max(1, stats.evaluations) : null)} />
          <Kpi label="Error rate" value="0%" hint="4xx/5xx at the API" />
        </KpiGrid>
      </Panel>
      <Panel title="API keys">
        <Table>
          <THead><Tr><Th>Name</Th><Th>Key</Th><Th>Scopes</Th><Th>Created</Th><Th>Last used</Th><Th>Status</Th><Th /></Tr></THead>
          <TBody>
            {(data?.api_keys ?? []).map((k) => (
              <Tr key={k.id}>
                <Td>{k.name}</Td>
                <Td><code>{k.prefix}…</code></Td>
                <Td>{k.scopes.map((s) => <Badge as="span" key={s} size="small" variant="neutral">{s}</Badge>)}</Td>
                <Td>{ago(k.created_at)}</Td>
                <Td>{ago(k.last_used_at)}</Td>
                <Td>{k.revoked_at ? <Badge as="span" variant="error" size="small">Revoked</Badge> : <Badge as="span" variant="success" size="small">Active</Badge>}</Td>
                <Td textAlign="right">{!k.revoked_at && k.id !== me?.key.id ? <Button variant="destructive_link" size="small" onClick={() => revoke(k)}>Revoke</Button> : null}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </Panel>
      <Panel title="Send a transaction">
        {data ? (
          <CodeBlockWrapper>
            <CodeBlockHeader>POST /v1/evaluations</CodeBlockHeader>
            <CodeBlockTabList>
              <CodeBlockTab>cURL</CodeBlockTab>
              <CodeBlockTab>Node.js</CodeBlockTab>
              <CodeBlockTab>Python</CodeBlockTab>
            </CodeBlockTabList>
            <CodeBlockTabPanel><CodeBlock language="shell" code={data.snippets.curl} /></CodeBlockTabPanel>
            <CodeBlockTabPanel><CodeBlock language="javascript" code={data.snippets.node} /></CodeBlockTabPanel>
            <CodeBlockTabPanel><CodeBlock language="python" code={data.snippets.python} /></CodeBlockTabPanel>
          </CodeBlockWrapper>
        ) : null}
      </Panel>
      <Panel title="Outbound webhooks" actions={<Button variant="secondary" size="small" onClick={() => setShowWebhook(!showWebhook)}>{showWebhook ? "Hide" : "Reveal"} signing secret</Button>}>
        <Text as="p">Verdicts are delivered to each evaluation's <code>options.callback_url</code>, signed with <code>Subpoena-Signature: t=…,v1=HMAC_SHA256(secret, t + "." + body)</code>.</Text>
        <Box marginTop="space30"><code>{showWebhook ? data?.webhook_signing_secret : "whsec_••••••••••••••••"}</code></Box>
      </Panel>

      <Modal isOpen={creating} onDismiss={() => { setCreating(false); setSecret(null); }} size="default" ariaLabelledby="new-key">
        <ModalHeader><ModalHeading as="h3" id="new-key">{secret ? "Copy your API key" : "Create API key"}</ModalHeading></ModalHeader>
        <ModalBody>
          {secret ? (
            <>
              <Alert variant="warning"><Text as="span">This secret is shown once. Store it in your secret manager now.</Text></Alert>
              <Box marginTop="space50"><CodeBlock language="shell" variant="single-line" code={secret} /></Box>
            </>
          ) : (
            <>
              <Label htmlFor="kname" required>Name</Label>
              <Input id="kname" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="payments-backend-prod" />
              <Box marginTop="space50">
                <CheckboxGroup name="scopes" legend="Scopes">
                  {SCOPES.map((s) => (
                    <Checkbox key={s} id={s} value={s} checked={scopes.includes(s)}
                      onChange={(e) => setScopes(e.target.checked ? [...scopes, s] : scopes.filter((x) => x !== s))}>{s}</Checkbox>
                  ))}
                </CheckboxGroup>
              </Box>
            </>
          )}
        </ModalBody>
        <ModalFooter><ModalFooterActions>
          {secret ? <Button variant="primary" onClick={() => { setCreating(false); setSecret(null); }}>Done</Button> : <>
            <Button variant="secondary" onClick={() => setCreating(false)}>Cancel</Button>
            <Button variant="primary" onClick={create} disabled={!name || !scopes.length}>Create</Button>
          </>}
        </ModalFooterActions></ModalFooter>
      </Modal>
    </>
  );
}
