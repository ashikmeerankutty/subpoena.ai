"use client";

import { Alert } from "@twilio-paste/core/alert";
import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Button } from "@twilio-paste/core/button";
import { Input } from "@twilio-paste/core/input";
import { Label } from "@twilio-paste/core/label";
import { Option, Select } from "@twilio-paste/core/select";
import { Table, TBody, Td, Th, THead, Tr } from "@twilio-paste/core/table";
import { Text } from "@twilio-paste/core/text";
import { type ComponentProps, useMemo, useState } from "react";

import { Drawer } from "@/components/Drawer";
import { JsonView } from "@/components/JsonView";
import { PageHeader, Panel, useMe } from "@/components/Shell";
import { usePoll } from "@/lib/api";
import { ago } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";

const CATEGORIES = [
  { value: "", label: "All actions" },
  { value: "api_key", label: "API keys" },
  { value: "policy", label: "Policies" },
  { value: "evaluation", label: "Overrides" },
  { value: "member", label: "Members & sign-ins" },
  { value: "settings", label: "Settings" },
  { value: "destination", label: "Destinations" },
];

const VARIANT: Record<string, ComponentProps<typeof Badge>["variant"]> = {
  api_key: "decorative10", policy: "decorative20", evaluation: "warning", member: "decorative30",
  settings: "neutral", destination: "decorative40",
};

/** One-line summary of what changed, e.g. "role: ANALYST → VIEWER". */
function summary(e: AuditEntry): string {
  const keys = new Set([...Object.keys(e.before ?? {}), ...Object.keys(e.after ?? {})]);
  const fmt = (v: unknown) => (v == null ? "—" : typeof v === "object" ? "{…}" : String(v));
  return [...keys]
    .slice(0, 3)
    .map((k) => (e.before && k in e.before && e.after && k in e.after
      ? `${k}: ${fmt(e.before[k])} → ${fmt(e.after[k])}`
      : `${k}: ${fmt((e.after ?? e.before ?? {})[k])}`))
    .join(" · ");
}

function toCsv(rows: AuditEntry[]): string {
  const esc = (v: unknown) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const head = ["at", "actor_type", "actor", "action", "target", "before", "after"];
  const lines = rows.map((r) => [r.at, r.actor.type, r.actor.name, r.action, r.target,
    JSON.stringify(r.before ?? {}), JSON.stringify(r.after ?? {})].map(esc).join(","));
  return [head.join(","), ...lines].join("\n");
}

export default function AuditLogPage() {
  const me = useMe();
  const admin = me?.role === "ADMIN";
  const [category, setCategory] = useState("");
  const [actor, setActor] = useState("");
  const [open, setOpen] = useState<AuditEntry | null>(null);
  const query = useMemo(() => {
    const q = new URLSearchParams({ limit: "500" });
    if (category) q.set("action", category);
    if (actor.trim()) q.set("actor", actor.trim());
    return `audit-log?${q}`;
  }, [category, actor]);
  const { data } = usePoll<{ data: AuditEntry[] }>(admin ? query : null, 10000);
  const rows = data?.data ?? [];

  function exportCsv() {
    const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: "text/csv" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `audit-log-${new Date().toISOString().slice(0, 10)}.csv` });
    a.click();
    URL.revokeObjectURL(url);
  }

  if (me && !admin) {
    return <><PageHeader title="Audit Log" /><Alert variant="neutral"><Text as="span">Only workspace admins can view the audit log.</Text></Alert></>;
  }

  return (
    <>
      <PageHeader title="Audit Log"
        description="Every human and system action in this workspace: keys, policies, overrides, members, sign-ins and settings. Append-only."
        actions={<Button variant="secondary" onClick={exportCsv} disabled={!rows.length}>Export CSV</Button>} />
      <Panel>
        <Box display="flex" columnGap="space50" marginBottom="space50">
          <Box width="size30">
            <Label htmlFor="cat">Action</Label>
            <Select id="cat" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => <Option key={c.value} value={c.value}>{c.label}</Option>)}
            </Select>
          </Box>
          <Box width="size40">
            <Label htmlFor="actor">Actor</Label>
            <Input id="actor" type="search" value={actor} placeholder="email or key name" onChange={(e) => setActor(e.target.value)} />
          </Box>
        </Box>
        <Table scrollHorizontally>
          <THead><Tr><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th>Target</Th><Th>Change</Th></Tr></THead>
          <TBody>
            {rows.map((r) => (
              <Tr key={r.id}>
                <Td><span title={new Date(r.at).toLocaleString()}>{ago(r.at)}</span></Td>
                <Td><Text as="div">{r.actor.name}</Text><Text as="div" color="colorTextWeak" fontSize="fontSize20">{r.actor.type.replace("_", " ").toLowerCase()}</Text></Td>
                <Td><Badge as="button" variant={VARIANT[r.action.split(".")[0]] ?? "neutral"} size="small" onClick={() => setOpen(r)}>{r.action}</Badge></Td>
                <Td><code>{r.target ?? "—"}</code></Td>
                <Td><Text as="span" color="colorTextWeak" fontSize="fontSize20">{summary(r)}</Text></Td>
              </Tr>
            ))}
            {data && !rows.length ? <Tr><Td colSpan={5}><Text as="span" color="colorTextWeak">No matching entries.</Text></Td></Tr> : null}
          </TBody>
        </Table>
      </Panel>
      <Drawer open={!!open} title={open?.action ?? ""} onClose={() => setOpen(null)}>
        {open ? (
          <>
            <Text as="p"><strong>{open.actor.name}</strong> ({open.actor.type.toLowerCase()}) · {new Date(open.at).toLocaleString()}</Text>
            <Text as="p" marginTop="space30">Target: <code>{open.target ?? "—"}</code></Text>
            <Text as="h3" fontWeight="fontWeightSemibold" marginTop="space60" marginBottom="space30">Before</Text>
            <JsonView value={open.before ?? {}} />
            <Text as="h3" fontWeight="fontWeightSemibold" marginTop="space60" marginBottom="space30">After</Text>
            <JsonView value={open.after ?? {}} />
          </>
        ) : null}
      </Drawer>
    </>
  );
}
