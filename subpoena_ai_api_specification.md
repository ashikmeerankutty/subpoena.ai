# Project Specification: Subpoena.ai

**Tagline:** The API-First Multi-Agent Fraud Defense Engine that Calls the User as a Witness
**Category Track:** BFSI: Intelligent Risk & Fraud / Agentic Workflows
**Target Event:** Google Cloud AI Builder Cup
**Version:** 1.0 · **Last updated:** 2026-10-09

---

## Table of Contents
1. [Executive Summary & Problem Statement](#1-executive-summary--problem-statement)
2. [Personas & Use Cases](#2-personas--use-cases)
3. [System Architecture](#3-system-architecture)
4. [Agents & the Multi-Agent Communication Pipeline](#4-agents--the-multi-agent-communication-pipeline)
5. [Decision Policy](#5-decision-policy)
6. [Subpoena & Testimony Flow](#6-subpoena--testimony-flow)
7. [Model Context Protocol (MCP) Server](#7-model-context-protocol-mcp-server)
8. [API Specification](#8-api-specification)
9. [Data Model](#9-data-model)
10. [Dashboard: Courthouse Console](#10-dashboard-courthouse-console)
11. [Google Cloud & Twilio Resources](#11-google-cloud--twilio-resources)
12. [Security, Privacy & Compliance](#12-security-privacy--compliance)
13. [Non-Functional Requirements](#13-non-functional-requirements)
14. [Success Metrics](#14-success-metrics)
15. [Additional Ideas & Roadmap](#15-additional-ideas--roadmap)
16. [Hackathon Execution Plan](#16-hackathon-execution-plan)
17. [Demo Script](#17-demo-script)
18. [Open Decisions](#18-open-decisions)
19. [Glossary](#19-glossary)

---

## 1. Executive Summary & Problem Statement

### The Problem
Traditional fraud detection relies on black-box ML classifiers that produce a single confidence score, leading to critical failures for enterprise banking:
1. **High False Positive Rates (FPR):** Legitimate users making anomalous purchases are hard-blocked, causing customer churn.
2. **The "Explainability Crisis":** Analysts spend hours correlating disparate logs because traditional models cannot explain their reasoning.
3. **No customer in the loop:** When a model is unsure, the only options are block (angry customer) or allow (fraud loss). Nobody asks the person who actually knows: the cardholder.

### The Solution: Subpoena.ai
**Subpoena.ai** is an API-first fraud resolution engine powered by **Multi-Agent Debate (MAD)** and **Adaptive Conversational Friction**, with a dedicated operator dashboard — the **Courthouse Console**.

- A bank's backend sends high-risk transactions to the API.
- A **courtroom of AI agents** gathers evidence and debates: a **Prosecutor** argues for blocking, a **Defense** argues for approval, specialist **Expert Witnesses** contribute findings, and a **Judge** rules.
- If the evidence is deadlocked, the Judge issues a **subpoena** directly to the cardholder over WhatsApp/SMS/voice. The witness is **authenticated first** (so a fraudster holding a stolen phone can't testify), and their testimony is admitted as evidence.
- Every step — every agent message, tool call, subpoena and verdict — is persisted and streamed live to the Courthouse Console, giving analysts a fully auditable, explainable case file.

Agents access bank data and external services through a strict **Model Context Protocol (MCP)** server, so LLMs never see raw database credentials. Agents talk to each other using Google's **Agent2Agent (A2A)** protocol, built with the **Agent Development Kit (ADK)** on **Vertex AI**.

### Where It Fits (Latency Tiers)
A multi-LLM debate takes seconds, so Subpoena.ai is **not** inline with sub-300 ms card authorization. It is designed for:

| Tier | Latency | Used for |
| :--- | :--- | :--- |
| **Tier 0 – Pre-screen** | < 100 ms | Rules + ML score. Clear approvals/blocks exit immediately; only the ambiguous middle goes to court. |
| **Tier 1 – Courtroom** | 3–20 s | Multi-agent debate. Suits P2P transfers, wires/ACH, card-not-present holds, new-payee payments, pre-settlement review. |
| **Tier 2 – Subpoena** | 1–15 min | Waiting on cardholder testimony. Transaction is held (soft decline / pending). |
| **Tier 3 – Appeal** | hours | Human analyst review in the Console. |

---

## 2. Personas & Use Cases

| Persona | Goal | Primary surface |
| :--- | :--- | :--- |
| **Integrating Developer** (bank backend team) | Send transactions, receive verdicts via webhook | REST API, Sources page, API keys |
| **Fraud Analyst** | Review escalated cases, understand why a verdict was made, override | Cases, Pipeline view, Subpoenas |
| **Risk / Compliance Lead** | Tune thresholds, audit decisions, export reports | Policies, Audit Log, Overview |
| **Cardholder (Witness)** | Quickly confirm or deny a transaction, safely | WhatsApp / SMS / voice |

**Key use cases**
1. Unusual-but-legit purchase (e.g. $4,500 auto parts at 2 a.m.) → subpoena → user confirms → approve, no churn.
2. Account takeover with SIM swap → witness authentication fails → block + escalate.
3. Clear-cut fraud (known bad IP + mule account in graph) → blocked by agents with no customer friction.
4. Analyst disagrees with a verdict → override → label feeds back into evaluation and precedent library.

---

## 3. System Architecture

### High-Level Diagram

```text
 [ Client Banking Backend ]
          |  POST /v1/evaluations  (API key + Idempotency-Key)
          v
 +------------------------+        +----------------------------------+
 | Apigee / API Gateway   |------->| Cloud Run: api service           |
 | (auth, quota, WAF via  |        |  - validates, writes Firestore   |
 |  Cloud Armor)          |        |  - Tier 0 pre-screen (rules+BQML)|
 +------------------------+        +----------------+-----------------+
                                                    | Pub/Sub: evaluations.created
                                                    v
 +-------------------------------------------------------------------------------+
 |              Courtroom (ADK multi-agent system on Vertex AI Agent Engine)      |
 |                                                                               |
 |   Clerk --> [Geo] [Device] [Velocity] [Merchant] [Graph]  (Expert Witnesses)   |
 |                     \______________|______________/                           |
 |                                    v                                          |
 |                    Prosecutor  <---- A2A ---->  Defense                        |
 |                                    v                                          |
 |                                  Judge ----> Bailiff (witness auth)            |
 |                                    v                                          |
 |                              Stenographer (summary / SAR draft)                |
 +-----------------------------+-------------------------------------------------+
                               | MCP (tools + resources)
                               v
 +-------------------------------------------------------------------------------+
 |                        MCP Server (Cloud Run)                                  |
 |  BigQuery (txns, baselines) | Spanner Graph (entities) | Vector Search         |
 |  (precedents) | Maps API (geo) | Twilio (WhatsApp/SMS/Verify/Lookup/Voice)     |
 +-------------------------------------------------------------------------------+
          |                                   |
          v                                   v
 Firestore (live case state) ----> Courthouse Console (Next.js + Twilio Paste)
          |                                   ^
          v                                   |
 BigQuery (audit, analytics) -----> Looker Studio      Destinations (webhooks, Slack,
                                                        Pub/Sub, BigQuery export)
```

### Request Lifecycle (Sequence)

```text
Bank         API         Pre-screen    Courtroom        Twilio        Witness      Console
 | POST eval  |               |             |               |             |            |
 |----------->| score         |             |               |             |            |
 |            |-------------->|             |               |             |            |
 |            |<--ambiguous---|             |               |             |            |
 |<-202 eval--|  publish ------------------>| Clerk gathers evidence (MCP)|        live|
 |            |               |             | Experts -> Prosecutor/Defense ------------>|
 |            |               |             | Judge: SUBPOENA             |            |
 |            |               |             |-- Lookup/Verify ->|         |            |
 |            |               |             |-- WhatsApp Q ---->|-------->|            |
 |            |               |             |               |<-- OTP + reply          |
 |            |<-------- inbound webhook (signed) ------------|             |            |
 |            |               |             | Judge re-rules: APPROVE --------------->|
 |<-- webhook evaluation.completed (HMAC) --|               |             |            |
```

### Pause / Resume
The courtroom is stateful across a subpoena. Case state lives in Firestore; when a subpoena is sent, a **Cloud Tasks** timer is scheduled (default 15 min). The inbound Twilio webhook or the timeout resumes the Judge with the stored context.

---

## 4. Agents & the Multi-Agent Communication Pipeline

### Agent Roster

| Agent | Model | Core Directive | MCP Access |
| :--- | :--- | :--- | :--- |
| **Clerk (Intake)** | Gemini Flash | Normalize the transaction, fetch baselines & history, open the case, build the evidence bundle. | Resources |
| **Expert Witnesses** (run in parallel) | Gemini Flash | Each produces typed `EvidenceFinding`s in one domain: **Geo** (impossible travel, geo-velocity), **Device** (new fingerprint, emulator), **Velocity** (amount/frequency spikes), **Merchant** (MCC risk, merchant validity), **Graph** (links to known mule accounts/devices). | Resources + read-only tools |
| **Prosecutor** | Gemini Flash | Argue strictly for blocking. Every claim must cite finding IDs. | Resources |
| **Defense** | Gemini Flash | Argue strictly for approval using historical edge cases and normal variance. Must cite finding IDs or precedents. | Resources + precedent search |
| **Judge** | Gemini Pro | Weigh arguments impartially, output calibrated `p_fraud`, rule or issue a subpoena with a targeted question. | Resources + subpoena tool |
| **Bailiff** | Deterministic service (no LLM) | Authenticate the witness (Twilio Lookup SIM-swap check, Verify OTP) before testimony is admitted. | Twilio tools |
| **Stenographer** | Gemini Flash | Write a plain-language verdict explanation for the bank, cardholder notice, and an optional SAR / adverse-action draft. | None |
| **Appeals Court** | Human analyst | Override verdicts from the Console. Overrides become labels. | Console |

> **Model IDs:** use the latest generally available Gemini Pro / Flash models on Vertex AI (Gemini 3.x family at time of writing — confirm GA status before the build). Model choice is per-agent config, not hard-coded.

### Debate Protocol
1. **Discovery:** Clerk assembles the evidence bundle; Expert Witnesses run in parallel and emit findings with IDs (`F1`, `F2`…), severity and source.
2. **Opening arguments:** Prosecutor and Defense each submit an argument (structured JSON).
3. **Rebuttal rounds:** up to `max_rounds` (default 2). Each side may rebut the other's latest argument.
4. **Citation rule:** any claim without a valid finding/precedent ID is **struck** and not shown to the Judge. This keeps arguments grounded and reduces hallucination.
5. **Ruling:** Judge returns `{ p_fraud, confidence, verdict, rationale, cited_findings[], subpoena_question? }`.
6. **All outputs** use Gemini structured output (response JSON schemas); invalid outputs are retried once, then the case escalates.

### Pipeline Events (what the dashboard shows)
Every agent-to-agent message is an **A2A message** and is also persisted as a `PipelineEvent`:

```json
{
  "event_id": "pev_01J9X…",
  "evaluation_id": "eval_773",
  "sequence": 7,
  "round": 1,
  "from_agent": "prosecutor",
  "to_agent": "judge",
  "type": "ARGUMENT",
  "payload": {
    "position": "BLOCK",
    "claims": [
      { "text": "Device never seen for this user", "cites": ["F2"] },
      { "text": "Amount is 6.2x the 90-day average", "cites": ["F4"] }
    ]
  },
  "model": "gemini-flash",
  "tokens": { "input": 2140, "output": 312 },
  "latency_ms": 840,
  "created_at": "2026-10-09T02:14:07.412Z"
}
```

Event types: `CASE_OPENED`, `TOOL_CALL`, `FINDING`, `ARGUMENT`, `REBUTTAL`, `CLAIM_STRUCK`, `RULING`, `SUBPOENA_SENT`, `WITNESS_AUTH`, `TESTIMONY`, `VERDICT`, `OVERRIDE`, `ERROR`.

---

## 5. Decision Policy

The Judge outputs a single calibrated probability of fraud, `p_fraud ∈ [0, 1]`. Thresholds are **per-tenant Policies** (versioned, editable in the Console). Defaults:

| Condition | Outcome |
| :--- | :--- |
| `p_fraud ≥ 0.85` | **BLOCK** |
| `p_fraud ≤ 0.15` | **APPROVE** |
| `0.15 < p_fraud < 0.85` **and** witness channel available **and** `amount ≥ subpoena_min_amount` | **SUBPOENA** (evidentiary deadlock) |
| `0.15 < p_fraud < 0.85` otherwise | **ESCALATE** to analyst |

Every value of `p_fraud` maps to exactly one outcome.

While a case is **ESCALATE**d the transaction is held (`verdict: HOLD`, `status: ESCALATED`) until an analyst rules. "BLOCK + ESCALATE" means `verdict: BLOCK`, `status: ESCALATED`.

**Tier 0 routing** uses its own per-policy cut-offs on the pre-screen score (defaults: `score ≤ 0.30` → exit APPROVE, `score ≥ 0.97` → exit BLOCK, otherwise → courtroom); hard-rule hits always exit BLOCK.

**After testimony**
- Witness authentication **fails** → **BLOCK** + **ESCALATE** (likely account takeover).
- Witness says "not me" → **BLOCK** + notify bank to start card reissue.
- Witness confirms → Judge re-rules **once** with testimony as new evidence; result above `0.15` → **ESCALATE**.
- **No reply** before `subpoena_timeout` (default 15 min) → apply `timeout_action` (default **HOLD** for analyst review).

**Hard rules** (applied before the courtroom, configurable): sanctioned countries, known-bad device list, amount ceilings.

---

## 6. Subpoena & Testimony Flow

### Channels (in policy-defined fallback order)
1. **WhatsApp** — approved template message with quick-reply buttons: *"Yes, it was me"* / *"No, block my card"* / free text.
2. **SMS** — fallback when WhatsApp isn't available.
3. **Voice** (stretch) — Twilio ConversationRelay + Gemini runs a short spoken interview.
4. **In-app push** — deep link into the bank's app (via client destination webhook).

### Example Subpoena
> *"Hi Alex, this is [Bank] Security. We noticed a **$4,500.00** purchase at **AutoZone Online** from a new device at 2:14 AM. Was this you? Reply YES or NO, or tell us more."*

The Judge writes the question to target the specific uncertainty (e.g. *"Are you currently travelling in Portugal?"*), within a template approved by the bank.

### Witness Authentication (Bailiff)
Before any testimony is admitted:
1. **Twilio Lookup** — line type and **SIM-swap recency**. Recent SIM swap → auth fails.
2. **Twilio Verify** — one-time code (or passkey link to the bank's app) confirms the witness controls the registered identity.
3. Result recorded as a `WITNESS_AUTH` event (`PASSED` / `FAILED` / `SKIPPED_BY_POLICY`).

### Testimony Processing (prompt-injection safe)
1. Inbound message arrives at `POST /v1/webhooks/twilio/inbound`; the **Twilio signature is validated**.
2. Text is screened by **Model Armor** (prompt injection, jailbreak, malicious URLs).
3. A **tool-less extractor model** converts the reply into structured `TestimonyClaims`:
   ```json
   { "confirms_transaction": true, "stated_reason": "Buying parts for BMW E36 project", "mentions_travel": false, "sentiment": "calm" }
   ```
4. The Judge sees only the structured claims plus the quoted raw text, clearly marked as untrusted. **Testimony can never trigger tools.**
5. **Multimodal evidence:** the witness can send a photo (receipt, order confirmation). Gemini vision extracts merchant, amount and date and checks them against the transaction.

---

## 7. Model Context Protocol (MCP) Server

Built with the official MCP SDK and deployed on Cloud Run. Agents use only MCP; credentials stay in Secret Manager.

### A. MCP Resources (read-only context)
* `user_profile://{user_id}/baselines` — historical device IDs, frequent IPs, home geo, average transfer velocity and amount.
* `transactions://{user_id}/recent` — paginated last 50 transactions.
* `graph://{entity_id}/neighbors` — linked accounts, devices, IPs, payees (Spanner Graph).
* `precedents://search?q=…` — similar past cases and their verdicts (vector search).
* `policy://{tenant_id}/active` — active thresholds and subpoena rules.

### B. MCP Tools (executable actions)
* `query_asn_reputation(ip_address)` — VPN/proxy/hosting ASN checks.
* `geo_velocity(user_id, ip_address, timestamp)` — impossible-travel calculation (Maps / IP geolocation).
* `validate_merchant(merchant_name, mcc)` — merchant existence & category check (Places API).
* `lookup_phone(user_id)` — Twilio Lookup line type + SIM-swap status. *(Bailiff only)*
* `send_verification(user_id, channel)` / `check_verification(user_id, code)` — Twilio Verify. *(Bailiff only)*
* `issue_subpoena(evaluation_id, user_id, question, channels[])` — sends the subpoena via Twilio. *(Judge only)*

Tool access is enforced **per agent** by the MCP server (allow-list), not by prompts.

---

## 8. API Specification

### Conventions
* **Base URL:** `https://api.subpoena.ai/v1`
* **Auth:** `Authorization: Bearer sk_live_…` (API key, scoped per workspace). Keys are created in the Console → Sources.
* **Idempotency:** `Idempotency-Key` header required on `POST /evaluations`; replays return the original response for 24 h.
* **Errors:** RFC 9457 `application/problem+json`.
* **Pagination:** cursor-based (`?limit=50&page_token=…`, response `meta.next_page_token`).
* **Outbound webhooks:** signed with `Subpoena-Signature: t=…,v1=HMAC_SHA256(secret, t + "." + body)`; retried with exponential backoff for 24 h.

### `POST /v1/evaluations`
Creates an evaluation. Returns **200** with a verdict if resolved in Tier 0 or within `sync_timeout_ms`; otherwise **202** with the evaluation in progress.

**Request**
```json
{
  "transaction_id": "tx_8839201",
  "user_id": "usr_9921",
  "amount": 4500.00,
  "currency": "USD",
  "type": "CARD_NOT_PRESENT",
  "occurred_at": "2026-10-09T02:14:03Z",
  "merchant": { "name": "AutoZone Online", "mcc": "5533", "country": "US" },
  "metadata": {
    "ip_address": "203.0.113.44",
    "device_fingerprint": "abc-123",
    "user_agent": "Mozilla/5.0 …"
  },
  "witness": { "phone": "+14155550123", "allowed_channels": ["WHATSAPP", "SMS"], "locale": "en-US" },
  "options": { "sync_timeout_ms": 8000, "callback_url": "https://bank.example.com/hooks/subpoena" }
}
```

**Response — 202 (subpoena issued)**
```json
{
  "evaluation_id": "eval_773",
  "status": "AWAITING_TESTIMONY",
  "p_fraud": 0.52,
  "verdict": null,
  "subpoena": { "id": "sbp_118", "channel": "WHATSAPP", "sent_at": "2026-10-09T02:14:11Z", "expires_at": "2026-10-09T02:29:11Z" },
  "debate_summary": [
    { "agent": "prosecutor", "position": "BLOCK", "summary": "New device; amount 6.2x the 90-day average." },
    { "agent": "defense", "position": "APPROVE", "summary": "Matches prior auto-parts purchases; home IP region." }
  ],
  "links": { "self": "/v1/evaluations/eval_773", "events": "/v1/evaluations/eval_773/events" }
}
```

**Statuses:** `RECEIVED` → `IN_DEBATE` → (`AWAITING_TESTIMONY`) → `RULED` | `ESCALATED` → (`APPEALED`).
**Verdicts:** `APPROVE`, `BLOCK`, `HOLD`.

### Other Endpoints

| Method & Path | Purpose |
| :--- | :--- |
| `GET /v1/evaluations/{id}` | Full evaluation: verdict, `p_fraud`, rationale, findings, subpoena, testimony. |
| `GET /v1/evaluations` | List / filter (`status`, `verdict`, `user_id`, `from`, `to`). |
| `GET /v1/evaluations/{id}/events` | Full pipeline transcript. `Accept: text/event-stream` streams live (SSE). |
| `POST /v1/evaluations/{id}/override` | Analyst override `{ verdict, reason }` (Analyst role). |
| `POST /v1/feedback` | Ground-truth labels from the bank: `{ transaction_id, label: "FRAUD" \| "LEGIT", source: "CHARGEBACK" \| "CUSTOMER_REPORT" }`. |
| `POST /v1/webhooks/twilio/inbound` | Twilio inbound messages (signature validated). |
| `POST /v1/webhooks/twilio/status` | Twilio delivery status callbacks. |
| `GET/POST/DELETE /v1/api-keys` | Manage API keys (Admin). |
| `GET/POST/PATCH /v1/sources`, `/v1/destinations` | Manage integrations. |
| `GET/POST /v1/policies`, `POST /v1/policies/{id}/simulate` | Manage and replay policies. |

### Outbound Webhook Events
`evaluation.completed`, `evaluation.escalated`, `subpoena.sent`, `subpoena.expired`, `testimony.received`, `witness_auth.failed`, `evaluation.overridden`.

```json
{
  "id": "evt_5521",
  "type": "evaluation.completed",
  "created_at": "2026-10-09T02:16:40Z",
  "data": {
    "evaluation_id": "eval_773",
    "transaction_id": "tx_8839201",
    "verdict": "APPROVE",
    "p_fraud": 0.08,
    "explanation": "Cardholder authenticated via OTP and confirmed the purchase with a matching receipt."
  }
}
```

---

## 9. Data Model

| Entity | Key fields | Store |
| :--- | :--- | :--- |
| **Tenant / Workspace** | id, name, region, plan | Firestore |
| **Member** | user_id, workspace_id, role (`ADMIN`, `ANALYST`, `VIEWER`) | Firestore + Identity Platform |
| **ApiKey** | id, prefix (`sk_live_ab12…`), hash, scopes, created_by, last_used_at, revoked_at | Firestore (hash only); secret shown once |
| **Source** | id, name, type (`REST`, `PUBSUB`, `BIGQUERY_STREAM`), api_key_ids, health | Firestore |
| **Destination** | id, type (`WEBHOOK`, `SLACK`, `PUBSUB`, `BIGQUERY`), config, signing_secret_ref, enabled_events | Firestore + Secret Manager |
| **Policy** | id, version, thresholds, subpoena rules, channels, timeouts, hard rules, active | Firestore |
| **Transaction** | transaction_id, user_id, amount, merchant, metadata (DLP-tokenized) | BigQuery |
| **Evaluation (Case)** | evaluation_id, transaction_id, status, p_fraud, verdict, policy_version, timings, cost | Firestore (live) → BigQuery (history) |
| **PipelineEvent** | see §4 | Firestore subcollection → BigQuery |
| **EvidenceFinding** | id, agent, type, severity, detail, source_ref | Firestore |
| **Subpoena** | id, channel, question, twilio_sid, delivery_status, sent_at, expires_at | Firestore |
| **Testimony** | subpoena_id, raw_text (redacted), claims, media_refs, witness_auth_result | Firestore + Cloud Storage (media) |
| **Override / Feedback** | evaluation_id, label, by, reason | Firestore → BigQuery |
| **AuditLog** | actor, action, target, before/after, at | BigQuery (append-only) |

---

## 10. Dashboard: Courthouse Console

### Design Language (Segment-style)
The Console follows the **Segment app** layout and interaction patterns:
- **Left sidebar navigation** with workspace switcher at the top (like Segment's workspace picker).
- **Connections-style catalog** for Sources and Destinations (logo cards, "Add Source" flow, status badges).
- **Dense data tables** with status pills, filters and saved views; clicking a row opens a **right-side detail drawer**.
- **Live Debugger** stream for incoming events (raw vs. pretty JSON), like Segment's Source Debugger.
- **Protocols-style** policy editor with versioning and violations.
- Built with **Twilio Paste** (the Twilio/Segment design system) on **Next.js + React**, **React Flow** for the agent pipeline graph, Firestore real-time listeners for live updates. Light/dark themes.

### Navigation & Pages

```text
+---------------------------------------------------------------------------------+
| [◆ Acme Bank ▾]            Search cases, users, transactions…        [?] [AM]  |
+--------------------+------------------------------------------------------------+
| Overview           |  Cases                                   [Filter] [Export] |
| Connections        |  ---------------------------------------------------------- |
|   Sources          |  Case      Txn         Amount   Status              p_fraud |
|   Destinations     |  eval_773  tx_8839201  $4,500   ● Awaiting testimony  0.52  |
| Transactions       |  eval_772  tx_8839188  $  120   ● Approved            0.04  |
| Cases              |  eval_771  tx_8839150  $9,800   ● Blocked             0.93  |
| Subpoenas          |  eval_770  tx_8839102  $2,300   ● Escalated           0.61  |
| Policies           |                                                             |
| Precedents         |                                                             |
| Audit Log          |                                                             |
| Settings           |                                                             |
+--------------------+------------------------------------------------------------+
```

| Page | What it shows |
| :--- | :--- |
| **Overview** | KPI tiles: evaluations/hour, approve / block / subpoena / escalate rates, median decision latency, subpoena resolution rate, median time-to-testimony, cost per evaluation. Trend charts by day; top risk signals. |
| **Sources** *(stored API info)* | API keys (create, rotate, revoke, scopes, last used, shown-once secret), integration snippets (cURL / Node / Python), ingest volume & error rate, schema of the evaluation payload, test-event button. |
| **Destinations** | Configured outputs (client webhook, Slack alerts, Pub/Sub, BigQuery export, ticketing). Delivery log with retries and response codes; signing secret management. |
| **Transactions** *(live debugger)* | Real-time stream of incoming transactions with Tier 0 score and routing (exited / sent to court). Raw vs. enriched JSON toggle. Filter by user, amount, verdict. |
| **Cases** | Docket table of all evaluations with status pills. Case detail: header (txn, user, amount, verdict, `p_fraud`), evidence findings, timeline, Stenographer explanation, override button. |
| **Pipeline view** *(multi-agent communication)* | For a case: animated graph — Clerk → Expert Witnesses → Prosecutor ⇄ Defense → Judge → Bailiff → Witness. Click a node to see its messages; chat-style transcript alongside. Claims link to cited findings; struck claims shown greyed. Per-step model, tokens, latency, tool calls. Replay a finished case step-by-step. |
| **Subpoenas** | All subpoenas: channel, question, delivery status (Twilio callbacks), witness-auth result, testimony, response time, outcome. Mirrored WhatsApp conversation view. |
| **Policies** | Thresholds, subpoena rules (min amount, channels, timeout, timeout action), hard rules. Version history with diff. **Simulate**: replay the last N evaluations under a draft policy and preview changes in approve/block/subpoena rates before publishing. |
| **Precedents** | Searchable library of past rulings used as case law, with similarity search ("find cases like this"). |
| **Audit Log** | Every human and system action (key created, policy changed, override) — filterable, exportable. |
| **Settings** | Members & roles, SSO, data retention, PII redaction toggles, regions, billing/usage. |

**Auth:** Identity Platform / Firebase Auth with Google SSO. Role-based access (`ADMIN`, `ANALYST`, `VIEWER`); PII is masked for viewers.

---

## 11. Google Cloud & Twilio Resources

### Google Cloud

| Service | Purpose | Hackathon | Prod |
| :--- | :--- | :---: | :---: |
| **Vertex AI – Gemini Pro / Flash** | Agent reasoning, structured output, vision for receipts | ✅ | ✅ |
| **Agent Development Kit (ADK)** | Build the multi-agent courtroom | ✅ | ✅ |
| **Vertex AI Agent Engine** | Managed hosting, sessions and memory for agents | ✅ | ✅ |
| **A2A protocol** | Agent-to-agent messaging (and future 3rd-party expert agents) | ✅ | ✅ |
| **Cloud Run** | API service, MCP server, Console hosting | ✅ | ✅ |
| **Pub/Sub** | Decouple ingest from courtroom; outbound event fan-out | ✅ | ✅ |
| **Cloud Tasks / Workflows** | Subpoena timeouts, pause/resume, webhook retries | ✅ | ✅ |
| **Firestore** | Live case state; real-time Console updates | ✅ | ✅ |
| **BigQuery** | Transactions, baselines, analytics, audit; BigQuery ML for Tier 0 score | ✅ | ✅ |
| **Spanner Graph** | Entity graph (users, devices, IPs, payees, mule rings) | ⚪ (BigQuery fallback) | ✅ |
| **Vertex AI Vector Search / BigQuery vector search** | Precedent library | ✅ | ✅ |
| **Secret Manager** | Twilio creds, webhook signing secrets | ✅ | ✅ |
| **Model Armor** | Prompt-injection & content screening on testimony and inputs | ✅ | ✅ |
| **Sensitive Data Protection (DLP)** | PII detection/tokenization before prompts & in UI | ⚪ | ✅ |
| **Identity Platform / Firebase Auth** | Console login, Google SSO | ✅ | ✅ |
| **Apigee / API Gateway + Cloud Armor** | API keys, quotas, WAF | ⚪ | ✅ |
| **Cloud Logging / Trace / Monitoring** | OpenTelemetry traces per agent step, alerts | ✅ | ✅ |
| **Vertex AI Gen AI Evaluation** | Offline evals of judge accuracy & calibration | ⚪ | ✅ |
| **Looker Studio** | Executive analytics on BigQuery | ⚪ | ✅ |
| **Google Maps Platform** (Geocoding, Places) | Geo-velocity, merchant validation | ✅ | ✅ |
| **reCAPTCHA Enterprise / Fraud Defense** | Extra device/bot risk signal | ⚪ | ✅ |
| **Cloud KMS (CMEK)** | Customer-managed encryption keys | — | ✅ |
| **Terraform** | Infra as code | ⚪ | ✅ |

✅ = in scope · ⚪ = optional/stretch · — = not needed

### Twilio

| Product | Purpose |
| :--- | :--- |
| **WhatsApp Business API / Content Templates** | Primary subpoena channel with quick-reply buttons |
| **Programmable Messaging (SMS)** | Fallback channel; delivery status callbacks |
| **Verify** | OTP / passkey witness authentication |
| **Lookup** (Line Type, SIM Swap) | Witness risk check before testimony |
| **Voice + ConversationRelay** | Spoken subpoena interview (stretch) |
| **Event Streams** | Stream delivery events to Pub/Sub |

---

## 12. Security, Privacy & Compliance

- **Tenant isolation:** every record keyed by `workspace_id`; Firestore security rules + service-level checks.
- **API keys:** stored as hashes, shown once, scoped, rotatable; usage tracked.
- **Least privilege for agents:** MCP enforces a per-agent tool allow-list; no agent gets raw DB credentials.
- **Prompt-injection defence:** Model Armor screening, tool-less extractor for testimony, untrusted-content markers, testimony can never call tools.
- **PII:** DLP tokenization before data reaches prompts where possible; masking in the Console by role; configurable retention (default 90 days for raw testimony).
- **Webhook integrity:** Twilio signature validation inbound; HMAC signatures outbound.
- **Auditability:** append-only audit log and full pipeline transcript per decision; policy version stored with every verdict.
- **Explainability & fairness:** Stenographer explanation for every verdict; no protected attributes in evidence; adverse actions above a configurable amount require human confirmation.
- **Model risk management:** versioned prompts and models, offline eval before rollout, monitoring of approve/block drift (SR 11-7 style documentation).

---

## 13. Non-Functional Requirements

| Area | Target |
| :--- | :--- |
| Tier 0 latency | p95 < 100 ms |
| Courtroom latency (no subpoena) | p95 < 15 s |
| Throughput (hackathon) | 10 evaluations/s sustained |
| Availability (prod target) | 99.9% API |
| Cost | < $0.05 per courtroom evaluation (Flash for most agents, Pro only for Judge) |
| Observability | One trace per evaluation, one span per agent step / tool call |
| Resilience | Model/tool failure → retry once → ESCALATE (never silently approve) |

---

## 14. Success Metrics

- **False positive rate** reduction vs. a score-only baseline on the same dataset.
- **Subpoena resolution rate** (% answered and authenticated) and **median time-to-testimony**.
- **Analyst minutes per case** (with Pipeline view vs. raw logs).
- **Judge calibration** (Brier score, reliability curve) on labeled data.
- **Escalation rate** and **override rate** (how often humans disagree).
- **Cost and latency per evaluation.**

---

## 15. Additional Ideas & Roadmap

| Idea | Description |
| :--- | :--- |
| **Precedent library ("stare decisis")** | Embed past verdicts; Defense/Judge retrieve similar cases, improving consistency. |
| **Jury mode** | Several cheap Flash "jurors" vote independently; disagreement is used as an uncertainty signal for the Judge. |
| **Policy simulator** | Replay historical traffic under draft thresholds before publishing. |
| **Analyst copilot** | "Ask about this case" chat in the Console, grounded only on case data. |
| **Auto SAR / adverse-action drafts** | Stenographer produces regulator-ready narratives for analyst sign-off. |
| **Voice subpoena** | Spoken interview via Twilio ConversationRelay + Gemini for users without WhatsApp. |
| **Cost governor** | Per-tenant token budget; skip debate for low amounts or low-risk tiers. |
| **Synthetic scenario generator** | Gemini-generated realistic legit/fraud transaction stories for demos and evals. |
| **Continuous evaluation** | Nightly eval on labeled set; alert on calibration drift. |
| **Third-party expert agents** | External risk vendors plug in as A2A Expert Witnesses. |
| **Feedback loop** | Chargebacks and overrides automatically become labels and precedents. |

---

## 16. Hackathon Execution Plan

### Proposed Repo Layout
```text
subpoena.ai/
├── apps/
│   ├── api/          # Cloud Run REST API (validation, Tier 0, webhooks)
│   ├── agents/       # ADK courtroom (Clerk, Experts, Prosecutor, Defense, Judge, Stenographer)
│   ├── mcp-server/   # MCP resources & tools (BigQuery, Graph, Maps, Twilio)
│   └── console/      # Next.js + Twilio Paste dashboard
├── data/seed/        # Synthetic users, baselines, transactions, scenarios
├── infra/terraform/  # GCP resources
└── docs/             # This spec, diagrams
```

### Milestones
1. **Foundation** — GCP project, Firestore, BigQuery seeded with synthetic data, `POST/GET /v1/evaluations`, API keys.
2. **Courtroom** — MCP server (resources + read tools), ADK agents with structured output, pipeline events written to Firestore.
3. **Subpoena loop** — Twilio WhatsApp + SMS, Lookup + Verify witness auth, inbound webhook, Cloud Tasks timeout, re-ruling.
4. **Console core** — Overview, Sources (API keys), Transactions debugger, Cases, Pipeline view, Subpoenas.
5. **Polish & stretch** — Destinations, Policies + simulator, Precedents, receipt-photo evidence, voice subpoena.
6. **Demo hardening** — scripted scenarios, fallback recordings, metrics slide.

---

## 17. Demo Script (≈3 minutes)

**Setup:** split screen — Courthouse Console (Pipeline view) on the left, a real phone mirrored on the right.

1. **Clear case (15 s):** a $12 coffee purchase arrives in the Transactions debugger and exits at Tier 0 — approved, no friction.
2. **The deadlock (60 s):** a $4,500 auto-parts purchase at 2:14 AM from a new device. The Pipeline graph lights up: Experts post findings, Prosecutor and Defense argue with citations, one uncited claim is struck. The Judge returns `p_fraud = 0.52` → **SUBPOENA**.
3. **The witness (45 s):** the phone receives a WhatsApp message. The user passes the Verify OTP, replies *"Yes, parts for my BMW E36 project"* and attaches a receipt photo. The Console shows the extracted receipt matching the merchant and amount.
4. **The verdict (20 s):** the Judge re-rules → **APPROVE**, `p_fraud = 0.08`. The Stenographer explanation appears; the bank receives an `evaluation.completed` webhook.
5. **The attack (30 s):** the same scenario for a different user whose SIM was swapped yesterday. The Bailiff's Lookup check fails → **BLOCK + ESCALATE**; the case appears in the analyst queue.
6. **Close (10 s):** Overview KPIs — false positives avoided, median time-to-testimony, cost per case.

---

## 18. Open Decisions

Defaults chosen in this spec; open to change. What the hackathon build actually chose (and every deviation from this spec) is recorded in [`docs/decisions.md`](./docs/decisions.md).

| Decision | Default | Alternatives |
| :--- | :--- | :--- |
| Agent language | Python (ADK) | TypeScript ADK / Node |
| API language | Python (FastAPI) on Cloud Run | Node (Express) |
| Live state store | Firestore | Cloud SQL Postgres + WebSockets |
| UI kit | Twilio Paste | shadcn/ui + Tailwind |
| Graph store | Spanner Graph (BigQuery fallback) | Neo4j AuraDB |
| Thresholds | 0.15 / 0.85, 15-min subpoena timeout | per-tenant tuning |
| Primary channel | WhatsApp | SMS-first |

---

## 19. Glossary

| Term | Meaning |
| :--- | :--- |
| **Case / Evaluation** | One transaction under review by the courtroom. |
| **Docket** | The list of cases (Cases page). |
| **Finding** | A typed, citable piece of evidence produced by an Expert Witness. |
| **Struck claim** | An argument without a valid citation; hidden from the Judge. |
| **Subpoena** | A targeted question sent to the cardholder when evidence is deadlocked. |
| **Bailiff** | The witness-authentication step (Lookup + Verify). |
| **Testimony** | The cardholder's authenticated reply, converted to structured claims. |
| **Precedent** | A past ruling retrieved as context for a new case. |
| **Appeal / Override** | A human analyst changing a verdict. |
