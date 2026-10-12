"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Callout, CalloutHeading, CalloutText } from "@twilio-paste/core/callout";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Tab, TabList, TabPanel, TabPanels, Tabs } from "@twilio-paste/core/tabs";
import { Text } from "@twilio-paste/core/text";
import { PauseIcon } from "@twilio-paste/icons/esm/PauseIcon";
import { PlayIcon } from "@twilio-paste/icons/esm/PlayIcon";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { OverrideModal } from "@/components/OverrideModal";
import { PipelineGraph } from "@/components/PipelineGraph";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { PFraud, StatusBadge } from "@/components/StatusBadge";
import { ReceiptCard } from "@/components/ReceiptCard";
import { Transcript } from "@/components/Transcript";
import { WitnessChat } from "@/components/WitnessChat";
import { api, usePoll } from "@/lib/api";
import { AGENTS } from "@/lib/agents";
import { money, seconds, time, usd } from "@/lib/format";
import type { AgentName, Evaluation, Page, PipelineEvent } from "@/lib/types";

const FINAL = ["RULED", "ESCALATED", "APPEALED"];

function useEvents(id: string) {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [live, setLive] = useState(false);
  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;
    const seen = new Set<number>();
    api<Page<PipelineEvent>>(`evaluations/${id}/events`).then((p) => {
      if (closed) return;
      p.data.forEach((e) => seen.add(e.sequence));
      setEvents(p.data);
      es = new EventSource(`/api/v1/evaluations/${id}/events`);
      setLive(true);
      es.addEventListener("pipeline", (m) => {
        const e = JSON.parse((m as MessageEvent).data) as PipelineEvent;
        if (seen.has(e.sequence)) return;
        seen.add(e.sequence);
        setEvents((prev) => [...prev, e].sort((a, b) => a.sequence - b.sequence));
      });
      es.addEventListener("end", () => { es?.close(); setLive(false); });
      es.onerror = () => { es?.close(); setLive(false); };
    });
    return () => { closed = true; es?.close(); };
  }, [id]);
  return { events, live };
}

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const me = useMe();
  const { data: polled, reload } = usePoll<Evaluation>(`evaluations/${id}`, 2000);
  const [ev, setEv] = useState<Evaluation | null>(null);
  useEffect(() => { if (polled) setEv(polled); }, [polled]);
  const { events, live } = useEvents(id);
  const [selected, setSelected] = useState<AgentName | null>(null);
  const [cursor, setCursor] = useState<number | null>(null); // null = follow live
  const [playing, setPlaying] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      setCursor((c) => {
        const next = (c ?? -1) + 1;
        if (next >= events.length - 1) { setPlaying(false); return null; }
        return next;
      });
    }, 650);
    return () => clearInterval(t);
  }, [playing, events.length]);

  const shown = useMemo(() => (cursor == null ? events : events.slice(0, cursor + 1)), [events, cursor]);
  const witnessPhone = events.find((e) => e.type === "TOOL_CALL" && e.payload.tool === "issue_subpoena")?.payload.result?.phone
    ?? events.find((e) => e.type === "TOOL_CALL" && e.payload.tool === "lookup_phone")?.payload.result?.phone;
  const transcript = selected ? shown.filter((e) => e.from_agent === selected || e.to_agent === selected) : shown;

  if (!ev) return <Text as="p">Loading case…</Text>;
  const latency = ev.ruled_at ? (new Date(ev.ruled_at).getTime() - new Date(ev.created_at).getTime()) / 1000 : null;
  const canOverride = me && me.role !== "VIEWER" && FINAL.includes(ev.status);

  return (
    <>
      <PageHeader title={`Case ${ev.evaluation_id}`}
        description={<>{money(ev.amount, ev.currency)} at <strong>{ev.merchant}</strong> · {ev.user_id} · txn <code>{ev.transaction_id}</code></>}
        actions={canOverride ? <Button variant="secondary" onClick={() => setOverrideOpen(true)}>Override verdict</Button> : null} />

      <Box display="grid" columnGap="space50" marginBottom="space60" style={{ gridTemplateColumns: "repeat(6, minmax(0, 1fr))" }}>
        {[
          ["Status", <StatusBadge key="s" status={ev.status} verdict={ev.verdict} />],
          ["p_fraud", <PFraud key="p" value={ev.p_fraud} />],
          ["Tier 0 score", ev.tier0 ? ev.tier0.score.toFixed(2) : "—"],
          ["Decision latency", seconds(latency)],
          ["Model cost", `${usd(ev.cost_usd)}${ev.tokens ? ` · ${ev.tokens.toLocaleString()} tok` : ""}`],
          ["Policy", `v${ev.policy_version}`],
        ].map(([label, value]) => (
          <Box key={label as string} backgroundColor="colorBackgroundBody" borderRadius="borderRadius30" padding="space50"
            borderWidth="borderWidth10" borderStyle="solid" borderColor="colorBorderWeaker">
            <Text as="div" fontSize="fontSize20" color="colorTextWeak">{label}</Text>
            <Box marginTop="space20" fontWeight="fontWeightSemibold">{value}</Box>
          </Box>
        ))}
      </Box>

      {ev.explanation ? (
        <Box marginBottom="space60">
          <Callout variant={ev.verdict === "BLOCK" ? "error" : ev.verdict === "APPROVE" ? "success" : "warning"}>
            <CalloutHeading as="h3">Stenographer</CalloutHeading>
            <CalloutText>{ev.explanation}</CalloutText>
          </Callout>
        </Box>
      ) : null}
      {ev.override ? (
        <Box marginBottom="space60"><Callout variant="neutral"><CalloutHeading as="h3">Appealed by {ev.override.by}</CalloutHeading>
          <CalloutText>{ev.override.previous_verdict} → {ev.override.verdict}: {ev.override.reason}</CalloutText></Callout></Box>
      ) : null}

      <Tabs selectedId={search.get("tab") === "file" ? "file" : "pipeline"} baseId="case-tabs">
        <TabList aria-label="Case views">
          <Tab id="pipeline">Pipeline view</Tab>
          <Tab id="file">Case file</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>
            <Box marginTop="space50">
              <Panel title={<Box display="flex" alignItems="center" columnGap="space30">
                  Multi-agent pipeline
                  {live && cursor == null ? <Badge as="span" variant="success" size="small"><span className="live-dot">●</span>&nbsp;Live</Badge> : null}
                  {cursor != null ? <Badge as="span" variant="neutral" size="small">Replay {cursor + 1}/{events.length}</Badge> : null}
                </Box>}
                actions={<>
                  <Button variant="secondary" size="small" onClick={() => { if (!playing && cursor == null) setCursor(0); setPlaying(!playing); }}>
                    {playing ? <PauseIcon decorative /> : <PlayIcon decorative />} {playing ? "Pause" : "Replay"}
                  </Button>
                  <Button variant="secondary" size="small" disabled={cursor == null} onClick={() => setCursor((c) => Math.max(0, (c ?? 0) - 1))}>Step back</Button>
                  <Button variant="secondary" size="small" disabled={cursor == null} onClick={() => setCursor((c) => (c == null || c + 1 >= events.length - 1 ? null : c + 1))}>Step</Button>
                  <Button variant="link" size="small" onClick={() => { setPlaying(false); setCursor(null); }}>Show all</Button>
                </>}>
                {cursor != null ? (
                  <Box marginBottom="space40">
                    <input type="range" min={0} max={Math.max(0, events.length - 1)} value={cursor}
                      onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }} style={{ width: "100%" }} aria-label="Replay position" />
                  </Box>
                ) : null}
                <PipelineGraph events={shown} selected={selected} onSelect={setSelected} />
                <Text as="p" fontSize="fontSize20" color="colorTextWeak" marginTop="space30">
                  Click an agent to filter the transcript. Claims cite findings (F#) or precedents (P#); uncited claims are struck before the Judge sees them.
                </Text>
              </Panel>
              <Box display="grid" columnGap="space60" style={{ gridTemplateColumns: ev.subpoena ? "minmax(0, 2fr) minmax(320px, 1fr)" : "1fr" }}>
                <Panel title={selected ? `Transcript · ${AGENTS[selected].label}` : `Transcript · ${transcript.length} messages`}
                  actions={selected ? <Button variant="link" size="small" onClick={() => setSelected(null)}>Clear filter</Button> : null}>
                  <Transcript events={transcript} findings={ev.findings} follow={cursor == null && !selected} />
                </Panel>
                {ev.subpoena && witnessPhone ? (
                  <Box>
                    <WitnessChat phone={witnessPhone} simulator={!!me?.simulator && ev.status === "AWAITING_TESTIMONY"} />
                  </Box>
                ) : null}
              </Box>
            </Box>
          </TabPanel>
          <TabPanel>
            <Box marginTop="space50">
              <Panel title={`Evidence findings (${ev.findings.length})`}>
                <Table>
                  <THead><Tr><Th>ID</Th><Th>Expert</Th><Th>Signal</Th><Th>Severity</Th><Th>Supports</Th><Th>Detail</Th></Tr></THead>
                  <TBody>
                    {ev.findings.map((f) => (
                      <Tr key={f.id}>
                        <Td><strong>{f.id}</strong></Td><Td>{AGENTS[f.agent].label}</Td><Td><code>{f.type}</code></Td>
                        <Td><Badge as="span" size="small" variant={f.severity === "HIGH" || f.severity === "CRITICAL" ? "error" : f.severity === "MEDIUM" ? "warning" : "neutral"}>{f.severity}</Badge></Td>
                        <Td>{f.supports}</Td><Td>{f.detail}</Td>
                      </Tr>
                    ))}
                  </TBody>
                </Table>
              </Panel>
              <Box display="grid" columnGap="space60" style={{ gridTemplateColumns: "1fr 1fr" }}>
                <Panel title="Debate summary">
                  {ev.debate_summary.map((d) => (
                    <Box key={d.agent} marginBottom="space40">
                      <Text as="div" fontWeight="fontWeightSemibold" style={{ color: AGENTS[d.agent].color }}>{AGENTS[d.agent].label} — {d.position}</Text>
                      <Text as="p">{d.summary}</Text>
                    </Box>
                  ))}
                  {ev.rationale ? <><Text as="div" fontWeight="fontWeightSemibold" style={{ color: AGENTS.judge.color }}>Judge</Text><Text as="p">{ev.rationale}</Text></> : null}
                </Panel>
                <Panel title="Testimony">
                  {ev.testimony ? <>
                    <Text as="p"><em>“{ev.testimony.raw_text}”</em></Text>
                    <Text as="p" marginTop="space30">Confirms: <strong>{String(ev.testimony.claims.confirms_transaction)}</strong> · reason: {ev.testimony.claims.stated_reason ?? "—"}</Text>
                    <Text as="p">Witness auth: {ev.testimony.witness_auth_result} · received {time(ev.testimony.received_at)}</Text>
                    {ev.testimony.flagged_by_screening ? <Badge as="span" variant="error">Flagged: {ev.testimony.screening_reasons.join(", ")}</Badge> : null}
                    {ev.testimony.receipt ? (
                      <Box marginTop="space50">
                        <ReceiptCard check={ev.testimony.receipt} expected={{
                          merchant: ev.merchant, amount: ev.amount, currency: ev.currency, date: ev.occurred_at,
                        }} />
                      </Box>
                    ) : null}
                  </> : <Text as="p" color="colorTextWeak">{ev.subpoena ? "Awaiting the witness." : "No subpoena was issued."}</Text>}
                </Panel>
              </Box>
            </Box>
          </TabPanel>
        </TabPanels>
      </Tabs>
      {ev && overrideOpen ? <OverrideModal ev={ev} open={overrideOpen} onClose={() => setOverrideOpen(false)} onDone={(e) => { setEv(e); reload(); }} /> : null}
    </>
  );
}
