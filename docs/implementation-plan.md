# Implementation Plan: Subpoena.ai

**Companion to:** [`subpoena_ai_api_specification.md`](../subpoena_ai_api_specification.md)
**Target Event:** Google Cloud AI Builder Cup
**Version:** 1.0 · **Last updated:** 2026-10-09

---

## Table of Contents
1. [Purpose & Scope](#1-purpose--scope)
2. [Requirements Traceability](#2-requirements-traceability)
3. [Repository Layout](#3-repository-layout)
4. [Environments & Setup](#4-environments--setup)
5. [Milestones](#5-milestones)
6. [Definition of Done](#6-definition-of-done)
7. [Testing & Verification](#7-testing--verification)
8. [Risks & Mitigations](#8-risks--mitigations)
9. [Open Decisions](#9-open-decisions)

---

## 1. Purpose & Scope

This document describes **how** Subpoena.ai will be built. The **what** — architecture, agents, API, data model and dashboard — is defined in the specification; section references below (e.g. *Spec §8*) point there.

**In scope (hackathon):**
- REST API with API keys, Tier 0 pre-screen and evaluation lifecycle (*Spec §3, §8*).
- ADK multi-agent courtroom with MCP server and pipeline events (*Spec §4, §7*).
- Subpoena loop over WhatsApp/SMS with witness authentication (*Spec §6*).
- Courthouse Console: Overview, Sources, Transactions, Cases, Pipeline view, Subpoenas (*Spec §10*).

**Stretch:** Destinations, Policies + simulator, Precedents, receipt-photo evidence, voice subpoena (*Spec §15*).

**Out of scope:** production multi-region deployment, CMEK, real bank data.

---

## 2. Requirements Traceability

| Requirement | Spec section | Milestone |
| :--- | :--- | :---: |
| API info is stored (API keys, sources, integrations) | §8 Conventions, §9 ApiKey/Source, §10 Sources | M1, M4 |
| Transactions visible on the UI | §9 Transaction, §10 Transactions | M1, M4 |
| Multi-agent communication pipeline | §4, §10 Pipeline view | M2, M4 |
| Subpoena information | §6, §9 Subpoena/Testimony, §10 Subpoenas | M3, M4 |
| Dedicated, Segment-style dashboard | §10 | M4 |
| Google Cloud resources | §11 | M0–M5 |
| Decision policy covers every score | §5 | M2 |
| Witness authentication & prompt-injection safety | §6, §12 | M3 |

---

## 3. Repository Layout

```text
subpoena.ai/
├── apps/
│   ├── api/          # Cloud Run REST API (validation, Tier 0, webhooks)
│   ├── agents/       # ADK courtroom (Clerk, Experts, Prosecutor, Defense, Judge, Stenographer)
│   ├── mcp-server/   # MCP resources & tools (BigQuery, Graph, Maps, Twilio)
│   └── console/      # Next.js + Twilio Paste dashboard
├── packages/
│   └── schemas/      # Shared JSON schemas (Evaluation, PipelineEvent, Finding, Testimony)
├── data/seed/        # Synthetic users, baselines, transactions, demo scenarios
├── infra/terraform/  # GCP resources
├── docs/             # Implementation plan, diagrams, ADRs
├── subpoena_ai_api_specification.md
└── README.md
```

**Conventions**
- Shared schemas in `packages/schemas` are the single source of truth for API payloads, agent structured outputs and Firestore documents.
- Config (thresholds, model IDs, channels) is read from Policy documents / environment — never hard-coded.
- Secrets live only in Secret Manager; `.env.example` lists required variables without values.

---

## 4. Environments & Setup

| Environment | Purpose | Notes |
| :--- | :--- | :--- |
| `local` | Development | Firestore & Pub/Sub emulators, Twilio test credentials, ngrok for inbound webhooks |
| `demo` | Hackathon presentation | Single GCP project, Cloud Run services, seeded BigQuery, real WhatsApp sandbox / sender |

**GCP project bootstrap (M0)**
- Enable APIs: Vertex AI, Cloud Run, Pub/Sub, Cloud Tasks, Firestore, BigQuery, Secret Manager, Model Armor, Identity Platform, Maps (Geocoding, Places), Cloud Trace.
- Service accounts per service (`api`, `agents`, `mcp-server`, `console`) with least-privilege roles.
- Terraform state in a GCS bucket.

**Twilio setup (M0)**
- WhatsApp sender (or sandbox) + approved subpoena template with quick-reply buttons.
- Messaging Service with SMS fallback, Verify Service, Lookup (Line Type + SIM Swap) access.
- Inbound and status webhooks pointing at `apps/api`.

---

## 5. Milestones

### M0 — Project Bootstrap
- [ ] Monorepo scaffold per §3, linting/formatting, CI (lint + unit tests).
- [ ] Terraform for core GCP resources and service accounts.
- [ ] Twilio accounts, sender and template submitted for approval (long lead time — start first).

**Exit criteria:** `terraform apply` creates the demo project; CI is green on an empty build.

### M1 — Foundation: API & Data
- [ ] `packages/schemas`: Evaluation, Transaction, PipelineEvent, EvidenceFinding, Subpoena, Testimony.
- [ ] `apps/api`: `POST /v1/evaluations`, `GET /v1/evaluations/{id}`, `GET /v1/evaluations` (*Spec §8*).
- [ ] API key auth (hashed keys, prefixes, scopes), `Idempotency-Key`, RFC 9457 errors, cursor pagination.
- [ ] Tier 0 pre-screen: hard rules + simple score; publish ambiguous cases to Pub/Sub.
- [ ] `data/seed`: synthetic users, baselines, 90 days of transactions, demo scenarios loaded into BigQuery.

**Exit criteria:** a cURL call with a valid key creates an evaluation in Firestore; Tier 0 approves the coffee scenario and routes the auto-parts scenario to Pub/Sub.

### M2 — Courtroom: Agents & MCP
- [ ] `apps/mcp-server`: resources and read tools from *Spec §7*, per-agent tool allow-list.
- [ ] `apps/agents` (ADK): Clerk, Expert Witnesses (parallel), Prosecutor, Defense, Judge, Stenographer with structured outputs.
- [ ] Debate protocol: rounds, citation rule (struck claims), retry-once-then-escalate (*Spec §4*).
- [ ] Decision policy from *Spec §5* implemented as a pure function with unit tests over the full `p_fraud` range.
- [ ] Every agent message written as a `PipelineEvent` to Firestore; OTel span per step.

**Exit criteria:** the demo deadlock scenario yields `SUBPOENA` with a full event transcript; the clear-fraud scenario yields `BLOCK` without a subpoena.

### M3 — Subpoena Loop
- [ ] `issue_subpoena` tool → WhatsApp template, SMS fallback; status callbacks recorded.
- [ ] Bailiff: Twilio Lookup SIM-swap check + Verify OTP (*Spec §6*).
- [ ] `POST /v1/webhooks/twilio/inbound` with signature validation → Model Armor → tool-less extractor → `TestimonyClaims`.
- [ ] Cloud Tasks timeout → `timeout_action`; Judge re-ruling with testimony.
- [ ] Outbound webhooks to the bank with HMAC signatures and retries.

**Exit criteria:** end-to-end on a real phone — subpoena received, OTP passed, reply leads to `APPROVE`; SIM-swap scenario leads to `BLOCK + ESCALATE`; an injection attempt in the reply is flagged and has no effect.

### M4 — Courthouse Console (core)
- [ ] Next.js app with Twilio Paste, Segment-style shell: sidebar, workspace switcher, tables, detail drawers (*Spec §10*).
- [ ] Identity Platform login with Google SSO; roles `ADMIN` / `ANALYST` / `VIEWER`.
- [ ] **Overview** KPI tiles and trends.
- [ ] **Sources**: API key create/rotate/revoke (secret shown once), integration snippets, ingest health.
- [ ] **Transactions**: live debugger via Firestore listeners, raw/enriched JSON toggle.
- [ ] **Cases**: docket table + case detail with findings, timeline, explanation, override.
- [ ] **Pipeline view**: React Flow agent graph, live transcript, citations, struck claims, per-step tokens/latency, replay.
- [ ] **Subpoenas**: delivery status, witness-auth result, testimony, mirrored WhatsApp view.

**Exit criteria:** the full demo (*Spec §17*) can be driven from the Console without touching logs or the terminal.

### M5 — Stretch & Polish
- [ ] Destinations (webhook, Slack, Pub/Sub, BigQuery export) with delivery log.
- [ ] Policies editor with versioning and simulate-against-history.
- [ ] Precedents library with vector search used by Defense/Judge.
- [ ] Receipt-photo testimony via Gemini vision.
- [ ] Voice subpoena via Twilio ConversationRelay.
- [ ] Audit Log and Settings pages.

### M6 — Demo Hardening
- [ ] Scripted demo scenarios with a reset command.
- [ ] Recorded fallback video of the full flow.
- [ ] Metrics slide from Overview (*Spec §14*).
- [ ] Load sanity check at 10 evaluations/s.

---

## 6. Definition of Done

A task is done when:
- Code matches the shared schemas and the referenced spec section.
- Unit tests cover the logic; new endpoints have an integration test.
- Errors follow RFC 9457; no secrets or raw PII in logs.
- Every new agent step emits a `PipelineEvent` and a trace span.
- The relevant Console view reflects the change (where applicable).
- The spec is updated if behaviour differs from it.

---

## 7. Testing & Verification

| Layer | Approach |
| :--- | :--- |
| Decision policy | Table-driven unit tests across `p_fraud` 0.00–1.00 and every post-testimony branch |
| API | Integration tests: auth, idempotency replay, pagination, error format, webhook signatures |
| Agents | Golden scenarios from `data/seed` with expected verdicts; schema-validation of every output |
| Safety | Prompt-injection test set against the testimony path; tool allow-list tests in MCP |
| Twilio | Test credentials locally; real-phone run of the demo scenarios on `demo` |
| Console | Component tests for tables/drawers; manual walkthrough of the demo script |
| Evals (stretch) | Vertex AI Gen AI Evaluation on labeled scenarios; track accuracy and Brier score |

**End-to-end check:** run *Spec §17* on the `demo` environment — coffee approved at Tier 0, auto-parts subpoenaed then approved after OTP + reply, SIM-swap case blocked and escalated, all visible live in the Console.

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| WhatsApp template approval delay | Subpoena demo blocked | Submit in M0; SMS fallback; WhatsApp sandbox |
| Gemini 3.x preview vs GA availability | Model unavailable / quota | Model IDs in config; fall back to latest GA model |
| LLM latency too high for live demo | Slow pipeline | Flash for all but Judge; parallel experts; cap rounds |
| Non-deterministic verdicts in demo | Wrong outcome on stage | Fixed seeds/temperature, golden scenarios, recorded fallback |
| Prompt injection through testimony | Manipulated verdict | Model Armor + tool-less extractor + untrusted markers |
| Lookup SIM-swap coverage by country/carrier | Auth check unavailable | Treat "unknown" per policy (default: require Verify) |
| Scope creep in the Console | Core pages unfinished | M4 core pages before any M5 work |

---

## 9. Open Decisions

See *Spec §18*. Defaults used by this plan: Python (ADK + FastAPI), Firestore for live state, Twilio Paste UI, Spanner Graph with BigQuery fallback, WhatsApp-first.
