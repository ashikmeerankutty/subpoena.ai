"use client";

import { Badge } from "@twilio-paste/core/badge";
import type { Status, Verdict } from "@/lib/types";

type Variant = "success" | "error" | "warning" | "neutral" | "info" | "new" | "decorative20";

const STATUS: Record<Status, [Variant, string]> = {
  RECEIVED: ["neutral", "Received"],
  IN_DEBATE: ["info", "In debate"],
  AWAITING_TESTIMONY: ["new", "Awaiting testimony"],
  RULED: ["neutral", "Ruled"],
  ESCALATED: ["warning", "Escalated"],
  APPEALED: ["decorative20", "Appealed"],
};

const VERDICT: Record<Verdict, [Variant, string]> = {
  APPROVE: ["success", "Approved"],
  BLOCK: ["error", "Blocked"],
  HOLD: ["warning", "Held"],
};

export function StatusBadge({ status, verdict }: { status: Status; verdict: Verdict | null }) {
  // Like the docket in the spec: show the verdict once ruled, otherwise the lifecycle status.
  const [variant, label] =
    status === "RULED" && verdict ? VERDICT[verdict] : status === "ESCALATED" && verdict === "BLOCK"
      ? (["error", "Blocked · escalated"] as [Variant, string])
      : STATUS[status];
  return (
    <Badge as="span" variant={variant} size="small">
      {label}
    </Badge>
  );
}

export function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return <Badge as="span" variant="neutral" size="small">Pending</Badge>;
  const [variant, label] = VERDICT[verdict];
  return <Badge as="span" variant={variant} size="small">{label}</Badge>;
}

export function PFraud({ value }: { value: number | null }) {
  if (value == null) return <span style={{ color: "#8891aa" }}>—</span>;
  const color = value >= 0.85 ? "#d61f1f" : value <= 0.15 ? "#14b053" : "#f47c22";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontVariantNumeric: "tabular-nums" }}>
      <span style={{ width: 36, height: 6, borderRadius: 3, background: "#e1e3ea", overflow: "hidden" }}>
        <span style={{ display: "block", width: `${value * 100}%`, height: "100%", background: color }} />
      </span>
      {value.toFixed(2)}
    </span>
  );
}
