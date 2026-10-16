"use client";

import { Box } from "@twilio-paste/core/box";
import { Select, Option } from "@twilio-paste/core/select";
import { Text } from "@twilio-paste/core/text";
import { useState } from "react";

import { Kpi, KpiGrid } from "@/components/Kpi";
import { PageHeader, Panel } from "@/components/Shell";
import { SendTestEvent } from "@/components/SendTestEvent";
import { TrendChart } from "@/components/TrendChart";
import { usePoll } from "@/lib/api";
import { money, pct, seconds, usd } from "@/lib/format";

interface Impact {
  legit_spend_saved: { count: number; amounts: Record<string, string> };
  fraud_stopped: { count: number; amounts: Record<string, string>; denied_by_cardholder: number };
  customers_not_contacted_rate: number | null;
  median_resolution_s: number | null;
  witness_protection: { sim_swap_blocked: number; code_failed: number; testimony_flagged: number; scam_held?: number };
}

/** Per-currency totals, largest first: "$4,500.00" or "$4,500.00 + €120.00". */
const totals = (amounts: Record<string, string> | undefined) => {
  const parts = Object.entries(amounts ?? {}).map(([c, v]) => money(v, c));
  return parts.length ? parts.join(" + ") : money(0);
};
interface Economics {
  tiers: { tier0_approve: number; tier0_block: number; courtroom: number };
  decided_without_model_rate: number | null;
  ai_spend_usd: number;
  cost_per_evaluation_usd: number | null;
  usd_protected: string;
  usd_protected_per_ai_dollar: number | null;
}

/** How each evaluation was decided; only the courtroom calls the model. */
const TIERS = [
  { key: "tier0_approve", label: "Tier 0 approve", color: "#0b7a39" },
  { key: "tier0_block", label: "Tier 0 block (incl. hard rules)", color: "#c72323" },
  { key: "courtroom", label: "Courtroom (Gemini)", color: "#6d2ed1" },
] as const;

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

interface Overview {
  window_hours: number;
  evaluations: number;
  evaluations_per_hour: number;
  sent_to_court: number;
  rates: { approve: number; block: number; subpoena: number; escalate: number };
  median_decision_latency_s: number | null;
  median_courtroom_latency_s: number | null;
  subpoenas: number;
  subpoena_resolution_rate: number | null;
  median_time_to_testimony_s: number | null;
  false_positives_avoided: number;
  cost_per_courtroom_case_usd: number | null;
  total_cost_usd: number;
  top_risk_signals: [string, number][];
  series: Record<string, any>[];
  bucket_minutes?: number;
  impact?: Impact;
  economics?: Economics;
}

export default function OverviewPage() {
  const [hours, setHours] = useState(24);
  const { data } = usePoll<Overview>(`stats/overview?hours=${hours}`, 5000);
  const top = data?.top_risk_signals ?? [];
  const max = Math.max(1, ...top.map(([, n]) => n));
  const impact = data?.impact;
  const guard = impact?.witness_protection;
  const econ = data?.economics;
  const tierTotal = econ ? Object.values(econ.tiers).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader title="Overview" description="Decisions, subpoenas and cost across the workspace."
        actions={<>
          <Box width="size20">
            <Select value={String(hours)} onChange={(e) => setHours(Number(e.target.value))} aria-label="Window">
              <Option value="1">Last hour</Option>
              <Option value="24">Last 24 hours</Option>
              <Option value="168">Last 7 days</Option>
            </Select>
          </Box>
          <SendTestEvent openCase={false} />
        </>} />
      <Panel title="Customer impact">
        <Text as="p" color="colorTextWeak" marginBottom="space50">
          What these decisions meant for cardholders in this window.
        </Text>
        <KpiGrid>
          <Kpi label="Genuine purchases approved" value={totals(impact?.legit_spend_saved.amounts)} tone="#0b7a39"
            hint={`${plural(impact?.legit_spend_saved.count ?? 0, "payment")} approved after the cardholder confirmed, instead of a decline`} />
          <Kpi label="Fraud stopped" value={totals(impact?.fraud_stopped.amounts)} tone="#c72323"
            hint={`${plural(impact?.fraud_stopped.count ?? 0, "payment")} blocked · ${impact?.fraud_stopped.denied_by_cardholder ?? 0} denied by the cardholder`} />
          <Kpi label="Customers not contacted" value={pct(impact?.customers_not_contacted_rate)}
            hint="decided without a message or a frozen card" />
          <Kpi label="Median time to resolution" value={seconds(impact?.median_resolution_s)}
            hint="payment to final decision, including waiting for a reply" />
          <Kpi label="Witness safeguards triggered"
            value={(guard?.sim_swap_blocked ?? 0) + (guard?.code_failed ?? 0) + (guard?.testimony_flagged ?? 0) + (guard?.scam_held ?? 0)}
            hint={`${guard?.sim_swap_blocked ?? 0} SIM swap · ${guard?.code_failed ?? 0} failed code · ${guard?.testimony_flagged ?? 0} flagged reply · ${guard?.scam_held ?? 0} scam held`} />
        </KpiGrid>
      </Panel>
      <Panel title="AI cost and value">
        <Text as="p" color="colorTextWeak" marginBottom="space50">
          Rules decide the clear cases for free. Gemini is only called for the uncertain ones.
        </Text>
        <KpiGrid>
          <Kpi label="Protected per $1 of AI" tone="#0b7a39"
            value={econ?.usd_protected_per_ai_dollar != null ? money(econ.usd_protected_per_ai_dollar) : "—"}
            hint={`${money(econ?.usd_protected ?? 0)} protected for ${usd(econ?.ai_spend_usd)} of model spend (USD only)`} />
          <Kpi label="Decided without a model" value={pct(econ?.decided_without_model_rate)}
            hint="Tier 0 rules and baselines, at no model cost" />
          <Kpi label="AI cost per evaluation" value={usd(econ?.cost_per_evaluation_usd)}
            hint={`${usd(data?.cost_per_courtroom_case_usd)} per courtroom case`} />
        </KpiGrid>
        {econ && tierTotal ? (
          <Box marginTop="space60">
            <Box display="flex" height="12px" borderRadius="borderRadius20" overflow="hidden" role="img"
              aria-label={`How evaluations were decided: ${TIERS.map((t) => `${t.label} ${econ.tiers[t.key]}`).join(", ")}`}>
              {TIERS.map((t) => (
                <Box key={t.key} style={{ width: `${(econ.tiers[t.key] / tierTotal) * 100}%`, backgroundColor: t.color }} />
              ))}
            </Box>
            <Box display="flex" flexWrap="wrap" columnGap="space60" rowGap="space20" marginTop="space30" aria-hidden="true">
              {TIERS.map((t) => (
                <Text key={t.key} as="span" fontSize="fontSize20" color="colorTextWeak">
                  <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, marginRight: 6, backgroundColor: t.color }} />
                  {t.label} · {econ.tiers[t.key]}
                </Text>
              ))}
            </Box>
          </Box>
        ) : null}
      </Panel>
      <Text as="h2" fontSize="fontSize40" fontWeight="fontWeightSemibold" marginBottom="space50">Operations</Text>
      <KpiGrid>
        <Kpi label="Evaluations / hour" value={data?.evaluations_per_hour ?? "—"} hint={`${data?.evaluations ?? 0} total · ${data?.sent_to_court ?? 0} sent to court`} />
        <Kpi label="Approve rate" value={pct(data?.rates.approve)} tone="#0b7a39" />
        <Kpi label="Block rate" value={pct(data?.rates.block)} tone="#c72323" />
        <Kpi label="Subpoena rate" value={pct(data?.rates.subpoena)} tone="#6d2ed1" />
        <Kpi label="Escalate rate" value={pct(data?.rates.escalate)} tone="#c25700" />
        <Kpi label="Median decision latency" value={seconds(data?.median_decision_latency_s)} hint={`courtroom ${seconds(data?.median_courtroom_latency_s)}`} />
        <Kpi label="Subpoena resolution" value={pct(data?.subpoena_resolution_rate)} hint={`${data?.subpoenas ?? 0} subpoenas`} />
        <Kpi label="Median time-to-testimony" value={seconds(data?.median_time_to_testimony_s)} />
        <Kpi label="False positives avoided" value={data?.false_positives_avoided ?? 0} hint="approved after testimony" tone="#0b7a39" />
        <Kpi label="Cost per courtroom case" value={usd(data?.cost_per_courtroom_case_usd)} hint={`${usd(data?.total_cost_usd)} total`} />
      </KpiGrid>
      <Box display="grid" columnGap="space60" marginTop="space70" style={{ gridTemplateColumns: "2fr 1fr" }}>
        <Panel title="Evaluations by verdict">
          <TrendChart series={data?.series ?? []} hours={hours} bucketMinutes={data?.bucket_minutes} />
        </Panel>
        <Panel title="Top risk signals">
          {top.length === 0 ? <Text as="p" color="colorTextWeak">No courtroom findings yet.</Text> : null}
          {top.map(([name, n]) => (
            <Box key={name} marginBottom="space40">
              <Box display="flex" justifyContent="space-between">
                <Text as="span" fontSize="fontSize20" fontWeight="fontWeightMedium">{name.replaceAll("_", " ").toLowerCase()}</Text>
                <Text as="span" fontSize="fontSize20" color="colorTextWeak">{n}</Text>
              </Box>
              <Box height="4px" backgroundColor="colorBackgroundStrong" borderRadius="borderRadius10" marginTop="space10">
                <Box height="4px" borderRadius="borderRadius10" backgroundColor="colorBackgroundErrorStrong" style={{ width: `${(n / max) * 100}%` }} />
              </Box>
            </Box>
          ))}
        </Panel>
      </Box>
    </>
  );
}
