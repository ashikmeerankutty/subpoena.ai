export type Status = "RECEIVED" | "IN_DEBATE" | "AWAITING_TESTIMONY" | "RULED" | "ESCALATED" | "APPEALED";
export type Verdict = "APPROVE" | "BLOCK" | "HOLD";
export type AgentName =
  | "system" | "clerk" | "geo" | "device" | "velocity" | "merchant" | "graph"
  | "prosecutor" | "defense" | "judge" | "bailiff" | "stenographer" | "witness" | "analyst";

export interface Finding {
  id: string;
  agent: AgentName;
  type: string;
  severity: "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  supports: "FRAUD" | "LEGIT" | "NEUTRAL";
  detail: string;
}

export interface Tier0 {
  score: number;
  route: "EXIT_APPROVE" | "EXIT_BLOCK" | "COURT";
  rules_hit: string[];
  signals: Record<string, number>;
  latency_ms: number;
}

export interface Testimony {
  subpoena_id: string;
  raw_text: string;
  claims: { confirms_transaction: boolean | null; stated_reason: string | null; mentions_travel: boolean; sentiment: string | null };
  witness_auth_result: string;
  flagged_by_screening: boolean;
  media_refs?: string[];
  receipt?: ReceiptCheck | null;
  screening_reasons: string[];
  received_at: string;
}

export interface Evaluation {
  evaluation_id: string;
  transaction_id: string;
  user_id: string;
  status: Status;
  p_fraud: number | null;
  verdict: Verdict | null;
  rationale: string | null;
  explanation: string | null;
  policy_version: number;
  tier0: Tier0 | null;
  findings: Finding[];
  debate_summary: { agent: AgentName; position: Verdict; summary: string }[];
  subpoena: { id: string; channel: string; sent_at: string; expires_at: string } | null;
  testimony: Testimony | null;
  created_at: string;
  updated_at: string;
  ruled_at: string | null;
  cost_usd: number | null;
  tokens: number | null;
  override: Record<string, string> | null;
  amount: string;
  currency: string;
  merchant: string;
  occurred_at: string;
}

export interface PipelineEvent {
  event_id: string;
  evaluation_id: string;
  sequence: number;
  round: number | null;
  from_agent: AgentName;
  to_agent: AgentName | null;
  type: string;
  payload: Record<string, any>;
  model: string | null;
  tokens: { input: number; output: number } | null;
  latency_ms: number | null;
  created_at: string;
}

export interface MediaRef { id: string; content_type: string; size_bytes: number; source: string }

export interface ReceiptCheck {
  media_id: string;
  result: "MATCH" | "PARTIAL" | "MISMATCH" | "NOT_A_RECEIPT" | "UNREADABLE";
  merchant: string | null;
  amount: string | null;
  currency: string | null;
  date: string | null;
  order_reference: string | null;
  merchant_match: boolean | null;
  amount_match: boolean | null;
  date_match: boolean | null;
  reasons: string[];
}

export interface WitnessMessage {
  id: string;
  phone: string;
  direction: "INBOUND" | "OUTBOUND";
  channel: string;
  body: string;
  status: string;
  media?: MediaRef[];
  created_at: string;
}

export interface Subpoena {
  id: string;
  evaluation_id: string;
  user_id: string;
  phone: string;
  question: string;
  channel: string;
  state: string;
  delivery_status: string;
  sent_at: string;
  expires_at: string;
  lookup: Record<string, any>;
  reply_text: string | null;
  code_verified: boolean;
  code_attempts: number;
  responded_at: string | null;
  evaluation?: Evaluation | null;
  messages?: WitnessMessage[];
}

export interface Page<T> {
  data: T[];
  meta: { next_page_token: string | null };
}

export type Role = "ADMIN" | "ANALYST" | "VIEWER";

export interface Me {
  workspace: { id: string; name: string; settings?: { pii_masking: boolean } };
  key: { id: string; name: string; prefix: string; scopes: string[] };
  role: Role;
  principal: { type: "MEMBER" | "API_KEY"; name: string; email: string | null; expires_at: string | null };
  simulator: boolean;
}

export interface Member {
  id: string;
  email: string;
  name: string | null;
  role: Role;
  added_by: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface AuditEntry {
  id: string;
  actor: { type: "API_KEY" | "MEMBER" | "SYSTEM"; id: string | null; name: string };
  action: string;
  target: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  at: string;
}

export interface Precedent {
  id: string;
  summary: string;
  verdict: string;
  label: "FRAUD" | "LEGIT";
  tags: string[];
  source: "SEED" | "CASE" | "OVERRIDE";
  evaluation_id: string | null;
  embedding_model: string | null;
  created_at: string;
  similarity?: number;
}
