// Endpoints the API Playground offers as presets. Paths are relative to /v1; {name} segments
// become inputs and are filled from earlier responses (the last evaluation, subpoena, ...).

export type Method = "GET" | "POST" | "PATCH" | "DELETE";

export interface Endpoint {
  id: string;
  group: string;
  method: Method;
  path: string;
  title: string;
  description: string;
  body?: Record<string, unknown>;
  /** POST /v1/evaluations: body comes from a seed scenario, with a fresh transaction id. */
  scenario?: boolean;
  idempotent?: boolean;
  stream?: boolean;
}

export const ENDPOINTS: Endpoint[] = [
  {
    id: "evaluate", group: "Evaluations", method: "POST", path: "evaluations", title: "Evaluate a transaction",
    description: "Tier 0 screens it; unclear cases go to the courtroom. Waits up to sync_timeout_ms for a verdict, else returns 202.",
    scenario: true, idempotent: true,
  },
  {
    id: "get-evaluation", group: "Evaluations", method: "GET", path: "evaluations/{evaluation_id}", title: "Get an evaluation",
    description: "Status, verdict, p_fraud, findings, subpoena and testimony.",
  },
  {
    id: "list-evaluations", group: "Evaluations", method: "GET", path: "evaluations?limit=10", title: "List evaluations",
    description: "Newest first. Filters: status, verdict, user_id, created_from, created_to.",
  },
  {
    id: "stream-events", group: "Evaluations", method: "GET", path: "evaluations/{evaluation_id}/events", title: "Stream pipeline events (SSE)",
    description: "The courtroom transcript as server-sent events, live until the verdict.", stream: true,
  },
  {
    id: "override", group: "Evaluations", method: "POST", path: "evaluations/{evaluation_id}/override", title: "Override a verdict",
    description: "Analyst appeal: replaces the verdict, records it in the audit log and notifies the bank.",
    body: { verdict: "APPROVE", reason: "Verified with the cardholder by phone" },
  },
  {
    id: "similar", group: "Evaluations", method: "GET", path: "evaluations/{evaluation_id}/similar", title: "Similar past cases",
    description: "Nearest precedents by embedding similarity.",
  },
  {
    id: "witness-reply", group: "Witness", method: "POST", path: "simulator/witness-reply", title: "Reply as the witness (simulator)",
    description: "Behaves exactly like an inbound reply on the subpoena's channel. Put the 6-digit code in the body to verify.",
    body: { phone: "+14155550123", body: "Yes, those are parts for my BMW project" },
  },
  {
    id: "get-subpoena", group: "Witness", method: "GET", path: "subpoenas/{subpoena_id}", title: "Get a subpoena",
    description: "Delivery status, channels tried and the full witness conversation.",
  },
  {
    id: "precedents", group: "Precedents", method: "GET", path: "precedents?q=auto%20parts%20new%20device", title: "Search precedents",
    description: "Semantic search over the seed library and every ruled case.",
  },
  {
    id: "policies", group: "Policy", method: "GET", path: "policies", title: "List policy versions",
    description: "Thresholds, subpoena rules and hard rules, newest first.",
  },
  {
    id: "simulate-policy", group: "Policy", method: "POST", path: "policies/simulate", title: "Simulate a policy change",
    description: "Replays recent courtroom rulings under draft thresholds. Changes nothing.",
    body: { thresholds: { approve_max: 0.2, block_min: 0.9 } },
  },
  {
    id: "overview", group: "Workspace", method: "GET", path: "stats/overview?hours=24", title: "Overview stats",
    description: "Rates, latencies, cost and the verdict time series.",
  },
  {
    id: "me", group: "Workspace", method: "GET", path: "me", title: "Who am I",
    description: "The workspace, role and scopes of the current session.",
  },
];

export const PARAM = /\{(\w+)\}/g;

export function params(path: string): string[] {
  return [...path.matchAll(PARAM)].map((m) => m[1]);
}

/** IDs worth carrying into the next request, found anywhere in a response. */
export function harvest(body: unknown, into: Record<string, string>): Record<string, string> {
  const out = { ...into };
  const visit = (v: unknown, depth: number) => {
    if (!v || typeof v !== "object" || depth > 3) return;
    if (Array.isArray(v)) return v.slice(0, 1).forEach((x) => visit(x, depth + 1));
    const o = v as Record<string, unknown>;
    if (typeof o.evaluation_id === "string") out.evaluation_id = o.evaluation_id;
    if (typeof o.id === "string" && o.id.startsWith("sbp_")) out.subpoena_id = o.id;
    Object.values(o).forEach((x) => visit(x, depth + 1));
  };
  visit(body, 0);
  return out;
}

export function curl(apiUrl: string, method: Method, path: string, body: string | null, idem: string | null): string {
  const lines = [`curl -X ${method} "${apiUrl.replace(/\/$/, "")}/v1/${path}"`, `  -H "Authorization: Bearer $SUBPOENA_API_KEY"`];
  if (idem) lines.push(`  -H "Idempotency-Key: ${idem}"`);
  if (body) lines.push(`  -H "Content-Type: application/json"`, `  -d '${body.replaceAll("'", "'\\''")}'`);
  return lines.join(" \\\n");
}
