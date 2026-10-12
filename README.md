# subpoena.ai

The API-first multi-agent fraud defense engine that calls the user as a witness.

A bank sends an ambiguous transaction to the API. A **courtroom of agents** (Clerk, five Expert
Witnesses, Prosecutor, Defense, Judge) gathers evidence through an **MCP server** and debates
it; every claim must cite evidence or it is struck. The Judge outputs a calibrated `p_fraud`
and the bank's **policy** maps it to APPROVE, BLOCK, ESCALATE or **SUBPOENA**: the cardholder is
asked over WhatsApp/SMS, authenticated by the **Bailiff** (SIM-swap lookup + one-time code),
and their reply is admitted as screened, structured testimony. Everything is streamed to the
**Courthouse Console**.

- [API Specification](./subpoena_ai_api_specification.md) — architecture, agents, API, data model, dashboard
- [Implementation Plan](./docs/implementation-plan.md) — milestones, setup, testing, risks
- [Decisions & deviations](./docs/decisions.md) — what was built differently from the spec, and why

## Repository

| Path | What |
| :--- | :--- |
| `packages/schemas` | Pydantic schemas shared by every service, agent structured outputs, and the decision policy (`decide`, `decide_after_testimony`). JSON Schema exports in `packages/schemas/json`. |
| `packages/store` | One `Store` protocol with in-memory and Firestore implementations (contract-tested on both). |
| `apps/api` | FastAPI: API keys, idempotency, RFC 9457 errors, Tier 0 pre-screen, evaluations, SSE event stream, overrides, Twilio webhooks, witness simulator, Console read models, signed outbound webhooks. |
| `apps/mcp-server` | MCP server (official SDK v2): resources and tools per Spec §7, one endpoint per agent so the allow-list is enforced by construction; Twilio or simulator witness channel. |
| `apps/agents` | The courtroom: ADK `LlmAgent`s on Vertex AI Gemini with response schemas, debate protocol with citation striking, Bailiff, testimony screening, re-ruling, timeouts; Cloud Run worker for Pub/Sub push and Cloud Tasks. |
| `apps/console` | Courthouse Console: Next.js + Twilio Paste, Segment-style. Overview, Sources, Transactions (live debugger), Cases, Pipeline view (React Flow graph, live SSE transcript, replay), Subpoenas (mirrored WhatsApp + phone simulator), Policies (simulate + publish). |
| `data/seed` | Deterministic synthetic users, 90 days of transactions, baselines, entity graph with a mule ring, IP intel, merchant registry, precedents and the demo scenarios. |
| `infra/gcp` | `deploy.sh` (idempotent gcloud deployment) and Cloud Build config. |
| `infra/cost-guard` | Optional billing kill switch (budget → Pub/Sub → function that unlinks billing). |

## Run everything locally (no cloud needed)

Requires [uv](https://docs.astral.sh/uv/) and Node 20+ with pnpm.

```bash
uv sync
# API + courtroom + MCP in one process, deterministic "scripted" agents, in-memory store
SUBPOENA_LOCAL_ADMIN_KEY=sk_test_local_demo_admin_000000000001 \
  uv run uvicorn subpoena_agents.local:app --factory --port 8000

# Console (another terminal)
cd apps/console && pnpm install && SUBPOENA_API_URL=http://localhost:8000 pnpm dev
```

Open http://localhost:3000, sign in with the key above and use **Send test event**.
To run the real Gemini courtroom locally add `SUBPOENA_LLM=gemini SUBPOENA_GCP_PROJECT=<project>`
(needs `gcloud auth application-default login` and Vertex AI enabled).

Single scenario from the terminal, printing the full agent transcript:

```bash
uv run python -m subpoena_agents.cli auto_parts_deadlock --llm gemini --reply "Yes, parts for my BMW E36 project"
```

## Tests and checks

```bash
uv run pytest                      # schemas, store, API, MCP, courtroom, end-to-end over HTTP
uv run ruff check . && uv run mypy packages/schemas/src packages/store/src apps/api/src apps/mcp-server/src apps/agents/src
cd apps/console && pnpm typecheck && pnpm build

# Same API/store tests against the Firestore emulator
gcloud emulators firestore start --host-port=127.0.0.1:8081 &
FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 SUBPOENA_TEST_STORE=firestore uv run pytest apps/api packages/store
```

## Deploy to Google Cloud

```bash
infra/gcp/deploy.sh <project-id> us-central1
uv run python data/seed/load_gcp.py --project <project-id>     # BigQuery + Firestore baselines
```

The script prints the API and Console URLs and the command to bootstrap a workspace admin key.
All services scale to zero; see [docs/decisions.md](./docs/decisions.md#cost) for the cost posture.

### Live witness on a real phone

Put `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID` and
`TWILIO_LIVE_NUMBERS=+<your number>` in `.env.twilio`, join the Twilio WhatsApp sandbox from that
phone, set the sandbox's inbound URL to `$API/v1/webhooks/twilio/inbound` and rerun `deploy.sh`.
Then `uv run python -m subpoena_agents.demo --api $API --key $KEY --live-phone +<your number>`
sends the auto-parts subpoena to WhatsApp; reply and send the SMS code in the same chat.

## Calling the API

```bash
curl -X POST "$API/v1/evaluations" -H "Authorization: Bearer $KEY" -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' -d @<(jq '.[1].request' data/seed/scenarios.json)
```

`200` when resolved within `options.sync_timeout_ms` (Tier 0 or a fast courtroom), otherwise `202`
with the live status; follow `GET /v1/evaluations/{id}/events` with `Accept: text/event-stream`.
OpenAPI docs are served at `/docs`.
