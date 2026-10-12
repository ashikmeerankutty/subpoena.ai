# Decisions & deviations from the spec

The spec (`subpoena_ai_api_specification.md`) is the target; this page records where the
hackathon build differs, why, and what it would take to close the gap.

| Area | Spec | Built | Why / how to close |
| :--- | :--- | :--- | :--- |
| Agent hosting | Vertex AI Agent Engine | ADK `LlmAgent`s run inside a Cloud Run worker | Agent Engine bills for always-on compute; Cloud Run scales to zero. The agents are plain ADK agents and can be moved to Agent Engine unchanged. |
| A2A | Agent-to-agent messages over A2A | Every inter-agent message is a persisted `PipelineEvent` with A2A-style from/to/type; agents run in one orchestrator | One process keeps latency and cost down. Exposing experts as remote A2A agents (ADK `RemoteA2aAgent`) is the path for third-party expert witnesses. |
| Clerk | Gemini Flash | Deterministic code reading MCP resources | Normalisation and fetching need no model; saves a call per case. |
| Expert witnesses | LLM with tools | Each expert calls *its own* MCP tools, code derives candidate signals, Gemini reviews them and writes findings | Grounds every finding in tool output and keeps runs reproducible; the model can still adjust severity and wording. |
| Verdict | Judge returns verdict | Judge returns `p_fraud` (+ rationale, citations, question); the verdict is always computed by `decide()` from the active policy | Guarantees "every p_fraud maps to exactly one outcome" and makes thresholds auditable. |
| Graph store | Spanner Graph | BigQuery tables (`graph_edges`, `graph_flags`) behind `graph://{id}/neighbors` | The spec's own fallback; Spanner has a ~$65/month floor. |
| Precedents | Vertex Vector Search | Vertex `text-embedding-005` embeddings with exact cosine search over the seed library plus every ruled courtroom case in the workspace (stored with its embedding in Firestore; analyst overrides relabel it). Console Precedents page and "Similar cases" per case. | Exact search is fine for thousands of precedents per workspace; beyond that, Firestore vector indexes (`find_nearest`) or Vertex Vector Search are drop-in replacements for `PrecedentLibrary.search`. |
| Merchant validation | Places API | Seed merchant registry (`merchants.json`) | Keeps the demo free and deterministic; `validate_merchant` is the single place to add Places. |
| IP geolocation | Maps / IP geolocation | Seed IP intelligence (`ip_geo.json`) | Maps does not geolocate IPs; a commercial IP-intel feed would plug into `DataSource.ip_info`. |
| Twilio | WhatsApp/SMS, Verify, Lookup | Live Twilio for the numbers in `TWILIO_LIVE_NUMBERS` (WhatsApp sandbox for the question, Verify SMS for the code, Lookup v2 for line type/SIM swap, signature-validated webhooks); seeded demo witnesses stay on the simulator so the scripted demo still runs. Verified end to end on a real phone: WhatsApp question → reply + Verify code → admitted → APPROVE | Lookup SIM-swap data needs carrier approval and is unsupported for Indian numbers, so the deployment sets `SIM_SWAP_REQUIRED=false` (unknown status is otherwise treated as a swap). `TWILIO_MESSAGE_FALLBACK=true` delivers a question Twilio rejects to the Console phone instead. Production needs a WhatsApp Sender and an approved template (`SUBPOENA_TWILIO_WHATSAPP_CONTENT_SID`) for business-initiated messages. |
| Model Armor | Screening of testimony | `ModelArmorScreener` implemented (falls back to heuristics); deployment uses the heuristic screener | Needs a Model Armor template: set `SUBPOENA_SCREENING=model_armor` and `SUBPOENA_MODEL_ARMOR_TEMPLATE`. Flagged testimony can never auto-approve. |
| Console auth | Identity Platform + Google SSO | Google sign-in (OpenID Connect code flow with PKCE, state and nonce) run by the Console; the API verifies the ID token and issues a 12-hour session credential scoped from the member's role (ADMIN/ANALYST/VIEWER). Members and roles are managed in Settings; API-key login remains for automation and break-glass. | Direct Google OIDC needs no Identity Platform tenant. Enable it by creating a Web OAuth client and adding `.env.google` (see `deploy.sh`). |
| Live updates | Firestore listeners in the browser | Server-sent events from the API, proxied by the Console | No Firebase client config or security rules needed; works with the in-memory store too. |
| Infra as code | Terraform | Idempotent `infra/gcp/deploy.sh` (gcloud) | Terraform was not available on the build machine; the script is a direct map to resources. |
| Stretch items | Destinations, Precedents page, Audit Log, Settings, receipt photos, voice | Built: Destinations (signed webhooks, Slack, Pub/Sub, BigQuery export, delivery log), Precedents, Audit Log (append-only, CSV export), Settings (members, roles, PII masking for viewers), receipt-photo testimony (Gemini vision + deterministic match), voice subpoenas and two-way SMS with channel fallback. | Calls use plain TwiML `<Gather>` (keypad code, then speech-to-text), not ConversationRelay: the courtroom only needs one answer, the transcript goes through the same untrusted-testimony path as a message, and there is no live LLM on the call to talk into anything. Follow-ups to a voice witness go by SMS. A failed or unanswered subpoena moves to the next channel in the policy's order; the code and the deadline stay the same. |

## Debate shape

`max_rounds = 2` means opening arguments plus one rebuttal round. The citation rule strikes any
claim with no valid finding (`F#`) or precedent (`P#`) ID before the Judge sees it; struck
claims are kept in the transcript (`CLAIM_STRUCK`).

## Receipt photos

The vision model only *reads* the photo (merchant, total, currency, date, order number) and is
never shown the transaction, so it cannot be led; `receipts.compare` decides MATCH, PARTIAL,
MISMATCH, NOT_A_RECEIPT or UNREADABLE. A MISMATCH can never auto-approve. Photos are stored per
workspace in a private bucket that deletes them after 30 days.

## Testimony safety

1. Twilio signature validation (or the authenticated simulator endpoint).
2. The reply is only *stored* by the API; a 6-digit code in it goes to the Bailiff.
3. Admission requires Lookup (no SIM swap within 7 days) **and** a verified one-time code.
4. Screening (Model Armor or heuristics), then a tool-less extractor turns text into
   `TestimonyClaims`. The Judge sees the claims and, only if unflagged, the raw text inside
   `<untrusted>` markers. Testimony cannot call tools, and flagged testimony cannot auto-approve.

## Cost

Every Cloud Run service has `min-instances=0`; Pub/Sub, Firestore, BigQuery, Cloud Tasks and
Secret Manager stay within free tiers at demo volume. The variable cost is Gemini: about
**$0.03 per courtroom case** (Flash for experts/advocates/stenographer, Pro for the Judge with a
512-token thinking budget), shown per case in the Console. Tier 0 resolves clear cases without
any model call.
