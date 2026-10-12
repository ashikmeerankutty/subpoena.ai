"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { HelpText } from "@twilio-paste/core/help-text";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Option, Select } from "@twilio-paste/core/select";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { useEffect, useState } from "react";

import { useToast } from "@/app/providers";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { api, usePoll } from "@/lib/api";
import { CHANNELS } from "@/lib/format";

interface Policy {
  id: string; version: number; active: boolean;
  thresholds: { approve_max: number; block_min: number };
  tier0: { approve_max: number; block_min: number };
  subpoena: { min_amount: string; channels: string[]; timeout_seconds: number; timeout_action: string };
  hard_rules: { sanctioned_countries: string[]; amount_ceiling: string | null };
}
interface Simulation { cases: number; current: Record<string, number>; draft: Record<string, number>; changed: { evaluation_id: string; p_fraud: number; from: string; to: string }[] }

const OUTCOMES = ["APPROVE", "SUBPOENA", "ESCALATE", "BLOCK"];

export default function PoliciesPage() {
  const me = useMe();
  const toast = useToast();
  const { data, reload } = usePoll<{ data: Policy[] }>("policies");
  const active = data?.data.find((p) => p.active);
  const [draft, setDraft] = useState<Policy | null>(null);
  const [sim, setSim] = useState<Simulation | null>(null);
  useEffect(() => { if (active && !draft) setDraft(active); }, [active, draft]);
  if (!draft || !active) return <Text as="p">Loading policy…</Text>;

  const body = () => ({
    thresholds: draft.thresholds, tier0: draft.tier0,
    subpoena: { ...draft.subpoena, min_amount: String(draft.subpoena.min_amount) },
  });
  const set = (path: string[], value: unknown) => {
    const next: any = structuredClone(draft);
    let o = next;
    for (const k of path.slice(0, -1)) o = o[k];
    o[path[path.length - 1]] = value;
    setDraft(next);
    setSim(null);
  };
  async function simulate() {
    try { setSim(await api<Simulation>("policies/simulate", { method: "POST", body: JSON.stringify(body()) })); }
    catch (e) { toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 5000 }); }
  }
  async function publish() {
    try {
      const p = await api<Policy>("policies", { method: "POST", body: JSON.stringify(body()) });
      toast.push({ message: `Published policy v${p.version}`, variant: "success", dismissAfter: 4000 });
      setDraft(p); setSim(null); reload();
    } catch (e) { toast.push({ message: (e as Error).message, variant: "error", dismissAfter: 5000 }); }
  }
  const num = (label: string, path: string[], value: number, step = 0.01, help?: string) => (
    <Box>
      <Label htmlFor={path.join(".")}>{label}</Label>
      <Input id={path.join(".")} type="number" step={String(step)} value={String(value)} onChange={(e) => set(path, Number(e.target.value))} />
      {help ? <HelpText>{help}</HelpText> : null}
    </Box>
  );

  return (
    <>
      <PageHeader title="Policies" description="Decision thresholds and subpoena rules. Every p_fraud maps to exactly one outcome."
        actions={<>
          <Button variant="secondary" onClick={simulate}>Simulate against history</Button>
          {me?.role === "ADMIN" ? <Button variant="primary" onClick={publish}>Publish v{active.version + 1}</Button> : null}
        </>} />
      <Box display="grid" columnGap="space60" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <Panel title={<>Judge thresholds <Badge as="span" variant="neutral" size="small">active v{active.version}</Badge></>}>
          <Box display="grid" columnGap="space50" rowGap="space50" style={{ gridTemplateColumns: "1fr 1fr" }}>
            {num("Approve if p_fraud ≤", ["thresholds", "approve_max"], draft.thresholds.approve_max)}
            {num("Block if p_fraud ≥", ["thresholds", "block_min"], draft.thresholds.block_min)}
            {num("Tier 0: exit approve ≤", ["tier0", "approve_max"], draft.tier0.approve_max)}
            {num("Tier 0: exit block ≥", ["tier0", "block_min"], draft.tier0.block_min)}
          </Box>
          <Box marginTop="space50">
            <svg viewBox="0 0 400 28" width="100%" role="img"
              aria-label={`Outcome bands: approve up to ${draft.thresholds.approve_max}, subpoena or escalate up to ${draft.thresholds.block_min}, block above`}>
              <rect x="0" y="4" width={400 * draft.thresholds.approve_max} height="16" fill="#14b053" />
              <rect x={400 * draft.thresholds.approve_max} y="4" width={400 * (draft.thresholds.block_min - draft.thresholds.approve_max)} height="16" fill="#6d2ed1" />
              <rect x={400 * draft.thresholds.block_min} y="4" width={400 * (1 - draft.thresholds.block_min)} height="16" fill="#d61f1f" />
            </svg>
            <Text as="p" fontSize="fontSize20" color="colorTextWeak">approve · subpoena or escalate · block</Text>
          </Box>
        </Panel>
        <Panel title="Subpoena rules">
          <Box display="grid" columnGap="space50" rowGap="space50" style={{ gridTemplateColumns: "1fr 1fr" }}>
            {num("Minimum amount ($)", ["subpoena", "min_amount"], Number(draft.subpoena.min_amount), 1)}
            {num("Timeout (seconds)", ["subpoena", "timeout_seconds"], draft.subpoena.timeout_seconds, 60)}
            <Box>
              <Label htmlFor="ta">On timeout</Label>
              <Select id="ta" value={draft.subpoena.timeout_action} onChange={(e) => set(["subpoena", "timeout_action"], e.target.value)}>
                <Option value="HOLD">Hold for analyst</Option><Option value="APPROVE">Approve</Option><Option value="BLOCK">Block</Option>
              </Select>
            </Box>
            <Box style={{ gridColumn: "span 2" }}>
              <Label htmlFor="ch">Channels, in order</Label>
              <Box id="ch" display="flex" flexWrap="wrap" alignItems="center" columnGap="space30" rowGap="space30">
                {draft.subpoena.channels.map((c, i, all) => (
                  <Box key={c} display="flex" alignItems="center" columnGap="space20" paddingX="space30" paddingY="space20"
                    borderRadius="borderRadius20" borderWidth="borderWidth10" borderStyle="solid" borderColor="colorBorderWeak">
                    <Text as="span" fontWeight="fontWeightSemibold">{i + 1}. {CHANNELS[c] ?? c}</Text>
                    <Button variant="secondary_icon" size="reset" disabled={i === 0} title="Try earlier"
                      onClick={() => set(["subpoena", "channels"], [...all.slice(0, i - 1), c, all[i - 1], ...all.slice(i + 1)])}>↑</Button>
                    <Button variant="secondary_icon" size="reset" disabled={all.length === 1} title="Remove"
                      onClick={() => set(["subpoena", "channels"], all.filter((x) => x !== c))}>✕</Button>
                  </Box>
                ))}
                {Object.keys(CHANNELS).filter((c) => !draft.subpoena.channels.includes(c)).map((c) => (
                  <Button key={c} variant="link" size="small" onClick={() => set(["subpoena", "channels"], [...draft.subpoena.channels, c])}>
                    + {CHANNELS[c]}
                  </Button>
                ))}
              </Box>
              <HelpText>The first channel the witness can use is tried first; if it isn't delivered (WhatsApp window closed, call not answered) the next one is.</HelpText>
            </Box>
          </Box>
          <Text as="p" marginTop="space50" fontSize="fontSize20" color="colorTextWeak">
            Hard rules: sanctioned countries {active.hard_rules.sanctioned_countries.join(", ")} · amount ceiling ${active.hard_rules.amount_ceiling}
          </Text>
        </Panel>
      </Box>
      {sim ? (
        <Panel title={`Simulation over ${sim.cases} recent courtroom rulings`}>
          <Table>
            <THead><Tr><Th>Outcome</Th><Th textAlign="right">Current (v{active.version})</Th><Th textAlign="right">Draft</Th><Th textAlign="right">Δ</Th></Tr></THead>
            <TBody>
              {OUTCOMES.map((o) => {
                const a = sim.current[o] ?? 0, b = sim.draft[o] ?? 0;
                return <Tr key={o}><Td>{o}</Td><Td textAlign="right">{a}</Td><Td textAlign="right">{b}</Td>
                  <Td textAlign="right"><Text as="span" color={b > a ? "colorTextSuccess" : b < a ? "colorTextError" : "colorTextWeak"}>{b - a > 0 ? `+${b - a}` : b - a}</Text></Td></Tr>;
              })}
            </TBody>
          </Table>
          {sim.changed.length ? <Text as="p" marginTop="space40" fontSize="fontSize20">{sim.changed.length} case(s) would change outcome, e.g. {sim.changed.slice(0, 3).map((c) => `${c.evaluation_id} (${c.p_fraud.toFixed(2)}: ${c.from} → ${c.to})`).join("; ")}</Text> : null}
        </Panel>
      ) : null}
      <Panel title="Version history">
        <Table>
          <THead><Tr><Th>Version</Th><Th>Approve ≤</Th><Th>Block ≥</Th><Th>Subpoena min</Th><Th>Timeout</Th><Th>Status</Th></Tr></THead>
          <TBody>
            {data!.data.map((p) => (
              <Tr key={p.id}><Td>v{p.version}</Td><Td>{p.thresholds.approve_max}</Td><Td>{p.thresholds.block_min}</Td>
                <Td>${p.subpoena.min_amount}</Td><Td>{p.subpoena.timeout_seconds}s → {p.subpoena.timeout_action}</Td>
                <Td>{p.active ? <Badge as="span" variant="success" size="small">Active</Badge> : <Badge as="span" variant="neutral" size="small">Archived</Badge>}</Td></Tr>
            ))}
          </TBody>
        </Table>
      </Panel>
    </>
  );
}
