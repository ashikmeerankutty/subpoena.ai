"use client";

import { Badge } from "@twilio-paste/core/badge";
import { Box } from "@twilio-paste/core/box";
import { Text } from "@twilio-paste/core/text";
import { useEffect, useRef, type ReactNode } from "react";

import { ReceiptCard } from "@/components/ReceiptCard";
import { AGENTS } from "@/lib/agents";
import { channelName, money, time } from "@/lib/format";
import type { Finding, PipelineEvent, ReceiptCheck } from "@/lib/types";

const SEV: Record<string, "neutral" | "info" | "warning" | "error" | "decorative20"> = {
  INFO: "neutral", LOW: "info", MEDIUM: "warning", HIGH: "error", CRITICAL: "error",
};

function Cite({ id, findings }: { id: string; findings: Map<string, Finding> }) {
  const f = findings.get(id);
  const tone = id.startsWith("P") ? "#6d2ed1" : f?.supports === "FRAUD" ? "#c72323" : f?.supports === "LEGIT" ? "#0b7a39" : "#4b5671";
  return (
    <span title={f ? `${f.type}: ${f.detail}` : id.startsWith("P") ? "Precedent" : "Unknown citation"}
      style={{ display: "inline-block", fontSize: 11, fontWeight: 600, padding: "0 6px", marginLeft: 4, borderRadius: 4,
        border: `1px solid ${tone}55`, color: tone, background: `${tone}0d`, cursor: "help" }}>
      {id}
    </span>
  );
}

function Claims({ claims, findings }: { claims: { text: string; cites: string[] }[]; findings: Map<string, Finding> }) {
  return (
    <Box as="ol" margin="space0" paddingLeft="space60">
      {claims.map((c, i) => (
        <Box as="li" key={i} marginBottom="space20">
          <Text as="span" fontSize="fontSize30">{c.text}</Text>
          {c.cites.map((id) => <Cite key={id} id={id} findings={findings} />)}
        </Box>
      ))}
    </Box>
  );
}

function Details({ summary, value }: { summary: string; value: unknown }) {
  return (
    <details style={{ marginTop: 4 }}>
      <summary style={{ cursor: "pointer", fontSize: 12, color: "#606b85" }}>{summary}</summary>
      <pre style={{ fontSize: 11, background: "#f4f4f6", padding: 8, borderRadius: 6, overflow: "auto", maxHeight: 220 }}>
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function Body({ e, findings }: { e: PipelineEvent; findings: Map<string, Finding> }): ReactNode {
  const p = e.payload;
  switch (e.type) {
    case "CASE_OPENED":
      return <Text as="p">Tier 0 score <strong>{p.tier0?.score?.toFixed(2)}</strong> → {p.tier0?.route === "COURT" ? "sent to the courtroom" : p.tier0?.route}. Policy v{p.policy_version}.</Text>;
    case "TOOL_CALL":
      return <>
        <Text as="p" fontSize="fontSize20"><code>{p.tool ? `${p.tool}(${Object.values(p.arguments ?? {}).map(String).join(", ")})` : p.resource}</code></Text>
        <Details summary="result" value={p.result} />
      </>;
    case "FINDING":
      return <Box display="flex" columnGap="space30" alignItems="flex-start">
        <Badge as="span" size="small" variant={SEV[p.severity]}>{p.id} · {p.severity}</Badge>
        <Text as="span" fontSize="fontSize30">{p.detail} <Text as="span" color={p.supports === "FRAUD" ? "colorTextError" : p.supports === "LEGIT" ? "colorTextSuccess" : "colorTextWeak"} fontSize="fontSize20" fontWeight="fontWeightSemibold">({p.supports.toLowerCase()})</Text></Text>
      </Box>;
    case "ARGUMENT":
    case "REBUTTAL":
      return <><Text as="p" fontSize="fontSize20" color="colorTextWeak" marginBottom="space20">{e.type === "ARGUMENT" ? "Opening" : `Rebuttal (round ${e.round})`} — argues {p.position}</Text><Claims claims={p.claims} findings={findings} /></>;
    case "CLAIM_STRUCK":
      return <Text as="p" fontSize="fontSize30" color="colorTextWeaker"><s>{p.claim}</s> <em>— struck from the {AGENTS[p.agent as keyof typeof AGENTS]?.label ?? p.agent}'s argument: {p.reason}</em></Text>;
    case "RULING":
      return <>
        <Box display="flex" alignItems="baseline" columnGap="space40">
          <Text as="span" fontSize="fontSize60" fontWeight="fontWeightBold">p_fraud {Number(p.p_fraud).toFixed(2)}</Text>
          <Badge as="span" size="small" variant={p.outcome === "APPROVE" ? "success" : p.outcome === "BLOCK" ? "error" : p.outcome === "SUBPOENA" ? "new" : "warning"}>{p.outcome}</Badge>
          {p.re_ruling ? <Badge as="span" size="small" variant="neutral">re-ruling with testimony</Badge> : null}
        </Box>
        <Text as="p" marginTop="space20">{p.rationale}</Text>
        {p.cited_findings?.length ? <Text as="p" fontSize="fontSize20" color="colorTextWeak">Relied on {p.cited_findings.map((id: string) => <Cite key={id} id={id} findings={findings} />)}</Text> : null}
        {p.subpoena_question && p.outcome === "SUBPOENA" ? <Text as="p" marginTop="space20">Question for the witness: <em>“{p.subpoena_question}”</em></Text> : null}
        <Text as="p" fontSize="fontSize20" color="colorTextWeak">{p.reason}</Text>
      </>;
    case "SUBPOENA_SENT":
      if (p.fallback_from) {
        return p.delivered
          ? <Text as="p">Not delivered via <strong>{channelName(p.fallback_from)}</strong>; resent via <strong>{channelName(p.channel)}</strong> — still expires {time(p.expires_at)}</Text>
          : <Text as="p">Not delivered via <strong>{channelName(p.fallback_from)}</strong> and no channel left ({p.reason}); waiting for a reply until {time(p.expires_at)}</Text>;
      }
      return <Text as="p">Subpoena sent via <strong>{channelName(p.channel)}</strong>: <em>“{p.question}”</em> — expires {time(p.expires_at)}</Text>;
    case "WITNESS_AUTH":
      return <Box display="flex" columnGap="space30" alignItems="center">
        <Badge as="span" size="small" variant={p.result === "PASSED" ? "success" : p.result === "NO_REPLY" ? "warning" : "error"}>{p.result}</Badge>
        <Text as="span">{p.reason ?? (p.check ? `checks: ${p.check}` : "")}</Text>
      </Box>;
    case "TESTIMONY":
      return <>
        <Box borderLeftWidth="borderWidth20" borderLeftStyle="solid" borderLeftColor="colorBorderWeak" paddingLeft="space40" marginBottom="space30">
          <Text as="p" fontSize="fontSize20" color="colorTextWeak">Untrusted witness text</Text>
          <Text as="p"><em>“{p.raw_text}”</em></Text>
        </Box>
        {p.flagged ? <Box marginBottom="space30"><Badge as="span" variant="error" size="small">Flagged by {p.screening?.engine}: {p.screening?.reasons?.join(", ")}</Badge></Box> : null}
        <Details summary="structured claims (tool-less extractor)" value={p.claims} />
      </>;
    case "EVIDENCE":
      return p.kind === "receipt"
        ? <><Text as="p" fontSize="fontSize20" color="colorTextWeak" marginBottom="space20">Receipt photo read by Gemini vision, compared by code</Text><ReceiptCard check={p as ReceiptCheck} /></>
        : <Details summary="evidence" value={p} />;
    case "VERDICT":
      return <>
        <Box display="flex" columnGap="space30" alignItems="center" marginBottom="space20">
          <Badge as="span" variant={p.verdict === "APPROVE" ? "success" : p.verdict === "BLOCK" ? "error" : "warning"}>{p.verdict ?? "HOLD"}</Badge>
          <Text as="span" fontWeight="fontWeightSemibold">{p.status}</Text>
          {p.reissue_card ? <Badge as="span" variant="warning" size="small">card reissue</Badge> : null}
        </Box>
        <Text as="p">{p.bank_explanation ?? p.rationale ?? p.reason}</Text>
        {p.cardholder_notice ? <Text as="p" fontSize="fontSize20" color="colorTextWeak" marginTop="space20">Cardholder notice: {p.cardholder_notice}</Text> : null}
        {p.sar_draft ? <Details summary="SAR draft" value={p.sar_draft} /> : null}
      </>;
    case "OVERRIDE":
      return <Text as="p">{p.by} changed the verdict {p.previous_verdict} → <strong>{p.verdict}</strong>: {p.reason}</Text>;
    case "ERROR":
      return <Text as="p" color="colorTextError">{p.error}</Text>;
    default:
      return <Details summary={e.type} value={p} />;
  }
}

export function Transcript({ events, findings, follow }: { events: PipelineEvent[]; findings: Finding[]; follow: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const map = new Map(findings.map((f) => [f.id, f]));
  for (const e of events) if (e.type === "FINDING") map.set(e.payload.id, e.payload as Finding);
  useEffect(() => {
    // Follow the live transcript inside its own scroll box, never the whole page.
    const el = box.current;
    if (follow && el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [events.length, follow]);
  return (
    <div ref={box} style={{ maxHeight: 640, overflowY: "auto", paddingRight: 8 }}>
      {events.map((e) => {
        const meta = AGENTS[e.from_agent];
        const struck = e.type === "CLAIM_STRUCK";
        return (
          <Box key={e.event_id} display="flex" columnGap="space40" marginBottom="space50">
            <Box flexShrink={0} width="sizeSquare80" height="sizeSquare80" borderRadius="borderRadiusCircle"
              display="flex" alignItems="center" justifyContent="center"
              style={{ background: `${meta.color}18`, color: meta.color, fontWeight: 700, fontSize: 13 }}>
              {meta.label.slice(0, 2)}
            </Box>
            <Box flexGrow={1} minWidth="0px" opacity={struck ? "0.75" : undefined}>
              <Box display="flex" columnGap="space30" alignItems="baseline" flexWrap="wrap">
                <Text as="span" fontWeight="fontWeightSemibold" style={{ color: meta.color }}>{meta.label}</Text>
                {e.to_agent ? <Text as="span" fontSize="fontSize20" color="colorTextWeak">→ {AGENTS[e.to_agent].label}</Text> : null}
                <Text as="span" fontSize="fontSize10" color="colorTextWeak" fontWeight="fontWeightSemibold" letterSpacing="wider">{e.type}</Text>
                <Text as="span" fontSize="fontSize10" color="colorTextWeaker" marginLeft="auto">
                  #{e.sequence} · {time(e.created_at)}
                  {e.model ? ` · ${e.model}` : ""}
                  {e.tokens ? ` · ${e.tokens.input}+${e.tokens.output} tok` : ""}
                  {e.latency_ms != null ? ` · ${e.latency_ms} ms` : ""}
                </Text>
              </Box>
              <Box marginTop="space10"><Body e={e} findings={map} /></Box>
            </Box>
          </Box>
        );
      })}
    </div>
  );
}

export { money };
