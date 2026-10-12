"use client";

import { Alert } from "@twilio-paste/core/alert";
import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Checkbox, CheckboxGroup } from "@twilio-paste/core/checkbox";
import { HelpText } from "@twilio-paste/core/help-text";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Modal, ModalBody, ModalFooter, ModalFooterActions, ModalHeader, ModalHeading } from "@twilio-paste/core/modal";
import { Switch } from "@twilio-paste/core/switch";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useState } from "react";

import { useToast } from "@/app/providers";
import { Drawer } from "@/components/Drawer";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { api, usePoll } from "@/lib/api";
import { ago, pct } from "@/lib/format";

type DType = "WEBHOOK" | "SLACK" | "PUBSUB" | "BIGQUERY";
interface Delivery {
  id: string; destination_id: string; event_type: string; evaluation_id: string | null; status: "SUCCESS" | "FAILED";
  attempts: number; response_code: number | null; error: string | null; latency_ms: number; at: string;
}
interface Dest {
  id: string; name: string; type: DType; config: Record<string, string>; enabled_events: string[]; enabled: boolean;
  created_at: string; deliveries: number; failure_rate: number | null; last_delivery: Delivery | null; signing_secret?: string;
}
interface ListResponse { data: Dest[]; meta: { event_types: string[]; bigquery_table: string | null; pubsub_project: string | null } }

const CATALOG: { type: DType; name: string; logo: string; color: string; field: string; label: string; help: string }[] = [
  { type: "WEBHOOK", name: "Webhook", logo: "{ }", color: "#121c2d", field: "url", label: "Endpoint URL",
    help: "HTTPS endpoint in your bank. Every request carries Subpoena-Signature: t=…,v1=HMAC_SHA256." },
  { type: "SLACK", name: "Slack", logo: "#", color: "#4a154b", field: "url", label: "Incoming webhook URL",
    help: "Create an incoming webhook in Slack (https://hooks.slack.com/services/…). Alerts link back to the case." },
  { type: "PUBSUB", name: "Pub/Sub", logo: "⇄", color: "#1a73e8", field: "topic", label: "Topic",
    help: "projects/<project>/topics/<topic>. Grant the Subpoena.ai service account Pub/Sub Publisher on it." },
  { type: "BIGQUERY", name: "BigQuery", logo: "▦", color: "#669df6", field: "table", label: "Table",
    help: "<project>.<dataset>.<table> with the export schema; one row per event for analytics in Looker Studio." },
];
const byType = Object.fromEntries(CATALOG.map((c) => [c.type, c])) as Record<DType, (typeof CATALOG)[number]>;

function Logo({ type, size = 40 }: { type: DType; size?: number }) {
  const c = byType[type];
  return (
    <Box display="flex" alignItems="center" justifyContent="center" borderRadius="borderRadius30" flexShrink={0}
      style={{ width: size, height: size, background: c.color, color: "white", fontWeight: 700, fontSize: size * 0.42 }}>
      {c.logo}
    </Box>
  );
}

export default function DestinationsPage() {
  const me = useMe();
  const toast = useToast();
  const admin = me?.role === "ADMIN";
  const { data, reload } = usePoll<ListResponse>(admin ? "destinations" : null, 10000);
  const [adding, setAdding] = useState<DType | null>(null);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [open, setOpen] = useState<Dest | null>(null);
  const { data: log, reload: reloadLog } = usePoll<{ data: Delivery[] }>(open ? `deliveries?destination_id=${open.id}&limit=50` : null, 5000);
  const eventTypes = data?.meta.event_types ?? [];

  async function run<T>(fn: () => Promise<T>, ok?: string): Promise<T | null> {
    try {
      const out = await fn();
      if (ok) toast.push({ message: ok, variant: "success", dismissAfter: 3000 });
      reload();
      return out;
    } catch (e) {
      toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 6000 });
      return null;
    }
  }

  function startAdd(type: DType) {
    setAdding(type);
    setName(type === "SLACK" ? "#fraud-alerts" : `${byType[type].name}`);
    setEvents(type === "SLACK" ? ["evaluation.escalated", "witness_auth.failed"] : []);
    setTarget(type === "BIGQUERY" ? data?.meta.bigquery_table ?? "" : type === "PUBSUB" && data?.meta.pubsub_project
      ? `projects/${data.meta.pubsub_project}/topics/` : "");
  }

  async function add() {
    if (!adding) return;
    const created = await run(() => api<Dest>("destinations", {
      method: "POST",
      body: JSON.stringify({ name, type: adding, config: { [byType[adding].field]: target.trim() }, enabled_events: events }),
    }), `Added ${name}`);
    if (created) { setAdding(null); setOpen(created); }
  }

  async function test(d: Dest) {
    const r = await run(() => api<Delivery>(`destinations/${d.id}/test`, { method: "POST" }));
    if (r) {
      toast.push({ message: r.status === "SUCCESS" ? `Test event delivered to ${d.name}` : `Delivery failed: ${r.error}`,
        variant: r.status === "SUCCESS" ? "success" : "error", dismissAfter: 5000 });
      reloadLog();
    }
  }

  async function openDrawer(d: Dest) {
    setOpen(d);
    const full = await run(() => api<Dest>(`destinations/${d.id}`));
    if (full) setOpen({ ...d, ...full });
  }

  if (me && !admin) {
    return <><PageHeader title="Destinations" /><Alert variant="neutral"><Text as="span">Only workspace admins can manage destinations.</Text></Alert></>;
  }
  const rows = data?.data ?? [];

  return (
    <>
      <PageHeader title="Destinations" description="Where decisions go: your bank's systems, Slack, Pub/Sub and BigQuery. Every delivery is signed, retried and logged." />
      <Panel title="Catalog">
        <Box display="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
          {CATALOG.map((c) => (
            <Box key={c.type} as="button" onClick={() => startAdd(c.type)} display="flex" columnGap="space40" alignItems="center"
              padding="space50" borderRadius="borderRadius30" borderWidth="borderWidth10" borderStyle="solid" borderColor="colorBorderWeaker"
              backgroundColor="colorBackgroundBody" cursor="pointer" textAlign="left" _hover={{ borderColor: "colorBorderPrimary", boxShadow: "shadowLow" }}>
              <Logo type={c.type} />
              <Box>
                <Text as="div" fontWeight="fontWeightSemibold">{c.name}</Text>
                <Text as="div" fontSize="fontSize20" color="colorTextWeak">Add destination</Text>
              </Box>
            </Box>
          ))}
        </Box>
      </Panel>

      <Panel title={`${rows.length} destination${rows.length === 1 ? "" : "s"}`}>
        <Table>
          <THead><Tr><Th>Destination</Th><Th>Events</Th><Th>Deliveries</Th><Th>Failure rate</Th><Th>Last delivery</Th><Th>Enabled</Th><Th><span className="sr-only">Actions</span></Th></Tr></THead>
          <TBody>
            {rows.map((d) => (
              <Tr key={d.id}>
                <Td>
                  <Box as="button" onClick={() => openDrawer(d)} display="flex" columnGap="space30" alignItems="center"
                    backgroundColor="transparent" borderWidth="borderWidth0" cursor="pointer" padding="space0" textAlign="left">
                    <Logo type={d.type} size={28} />
                    <Box><Text as="div" fontWeight="fontWeightSemibold">{d.name}</Text>
                      <Text as="div" fontSize="fontSize20" color="colorTextWeak">{byType[d.type].name} · {Object.values(d.config)[0]}</Text></Box>
                  </Box>
                </Td>
                <Td><Text as="span" fontSize="fontSize20">{d.enabled_events.length ? d.enabled_events.join(", ") : "All events"}</Text></Td>
                <Td>{d.deliveries}</Td>
                <Td>{d.failure_rate == null ? "—" : <Badge as="span" size="small" variant={d.failure_rate === 0 ? "success" : d.failure_rate < 0.2 ? "warning" : "error"}>{pct(d.failure_rate, 1)}</Badge>}</Td>
                <Td>{d.last_delivery ? <><Badge as="span" size="small" variant={d.last_delivery.status === "SUCCESS" ? "success" : "error"}>{d.last_delivery.status}</Badge> {ago(d.last_delivery.at)}</> : "—"}</Td>
                <Td><Switch checked={d.enabled} onChange={(e) => run(() => api(`destinations/${d.id}`, { method: "PATCH", body: JSON.stringify({ enabled: e.target.checked }) }))}>
                  <Text as="span" fontSize="fontSize20">{d.enabled ? "On" : "Off"}</Text></Switch></Td>
                <Td textAlign="right"><Box display="flex" columnGap="space30" justifyContent="flex-end">
                  <Button size="small" variant="secondary" onClick={() => test(d)}>Send test</Button>
                  <Button size="small" variant="secondary" onClick={() => openDrawer(d)}>Delivery log</Button>
                </Box></Td>
              </Tr>
            ))}
            {data && !rows.length ? <Tr><Td colSpan={7}><Text as="span" color="colorTextWeak">No destinations yet. Pick one from the catalog above.</Text></Td></Tr> : null}
          </TBody>
        </Table>
      </Panel>

      {adding ? <Modal isOpen onDismiss={() => setAdding(null)} size="wide" ariaLabelledby="add-dest">
        <ModalHeader><ModalHeading as="h3" id="add-dest">
          <Box display="flex" columnGap="space40" alignItems="center"><Logo type={adding} size={32} />Add {byType[adding].name} destination</Box>
        </ModalHeading></ModalHeader>
        <ModalBody>
          <>
            <Label htmlFor="d-name" required>Name</Label>
            <Input id="d-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
            <Box marginTop="space50">
              <Label htmlFor="d-target" required>{byType[adding].label}</Label>
              <Input id="d-target" type="text" value={target} onChange={(e) => setTarget(e.target.value)} />
              <HelpText>{byType[adding].help}</HelpText>
            </Box>
            <Box marginTop="space60">
              <CheckboxGroup name="events" legend="Events" helpText="Leave all unchecked to receive every event.">
                {eventTypes.map((t) => (
                  <Checkbox key={t} id={`ev-${t}`} value={t} checked={events.includes(t)}
                    onChange={(e) => setEvents(e.target.checked ? [...events, t] : events.filter((x) => x !== t))}><code>{t}</code></Checkbox>
                ))}
              </CheckboxGroup>
            </Box>
          </>
        </ModalBody>
        <ModalFooter><ModalFooterActions>
          <Button variant="secondary" onClick={() => setAdding(null)}>Cancel</Button>
          <Button variant="primary" onClick={add} disabled={!name.trim() || !target.trim()}>Add destination</Button>
        </ModalFooterActions></ModalFooter>
      </Modal> : null}

      <Drawer open={!!open} title={open?.name ?? ""} onClose={() => setOpen(null)} width="720px"
        actions={open ? <Button size="small" variant="secondary" onClick={() => test(open)}>Send test</Button> : null}>
        {open ? <>
          <Box display="flex" columnGap="space40" alignItems="center" marginBottom="space50">
            <Logo type={open.type} size={32} />
            <Box><Text as="div" fontWeight="fontWeightSemibold">{byType[open.type].name}</Text>
              <Text as="div" fontSize="fontSize20" color="colorTextWeak"><code>{Object.values(open.config)[0]}</code></Text></Box>
          </Box>
          {open.signing_secret ? (
            <Box marginBottom="space50">
              <Text as="div" fontSize="fontSize20" color="colorTextWeak">Signing secret (verify <code>Subpoena-Signature</code>)</Text>
              <code>{open.signing_secret}</code>
            </Box>
          ) : null}
          <Text as="h3" fontWeight="fontWeightSemibold" marginBottom="space30">Delivery log</Text>
          <Table>
            <THead><Tr><Th>When</Th><Th>Event</Th><Th>Result</Th><Th>Code</Th><Th>Attempts</Th><Th>Latency</Th></Tr></THead>
            <TBody>
              {(log?.data ?? []).map((r) => (
                <Tr key={r.id}>
                  <Td>{ago(r.at)}</Td>
                  <Td><code>{r.event_type}</code>{r.evaluation_id ? <Text as="div" fontSize="fontSize20" color="colorTextWeak">{r.evaluation_id}</Text> : null}</Td>
                  <Td><Badge as="span" size="small" variant={r.status === "SUCCESS" ? "success" : "error"}>{r.status}</Badge>
                    {r.error ? <Text as="div" fontSize="fontSize20" color="colorTextError">{r.error}</Text> : null}</Td>
                  <Td>{r.response_code ?? "—"}</Td>
                  <Td>{r.attempts}</Td>
                  <Td>{r.latency_ms} ms</Td>
                </Tr>
              ))}
              {log && !log.data.length ? <Tr><Td colSpan={6}><Text as="span" color="colorTextWeak">No deliveries yet. Send a test event.</Text></Td></Tr> : null}
            </TBody>
          </Table>
          <Box marginTop="space70">
            <Button variant="destructive_secondary" size="small"
              onClick={async () => { await run(() => api(`destinations/${open.id}`, { method: "DELETE" }), `Deleted ${open.name}`); setOpen(null); }}>
              Delete destination
            </Button>
          </Box>
        </> : null}
      </Drawer>
    </>
  );
}
