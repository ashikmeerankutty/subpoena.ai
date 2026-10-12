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
| Precedents | Vertex Vector Search | Keyword-overlap ranking over a seed precedent library | Vector Search endpoints bill per hour. BigQuery `VECTOR_SEARCH` over Gemini embeddings is the cheap upgrade. |
| Merchant validation | Places API | Seed merchant registry (`merchants.json`) | Keeps the demo free and deterministic; `validate_merchant` is the single place to add Places. |
| IP geolocation | Maps / IP geolocation | Seed IP intelligence (`ip_geo.json`) | Maps does not geolocate IPs; a commercial IP-intel feed would plug into `DataSource.ip_info`. |
| Twilio | WhatsApp/SMS, Verify, Lookup | Live Twilio for the numbers in `TWILIO_LIVE_NUMBERS` (WhatsApp sandbox for the question, Verify SMS for the code, Lookup v2 for line type/SIM swap, signature-validated webhooks); seeded demo witnesses stay on the simulator so the scripted demo still runs. Verified end to end on a real phone: WhatsApp question → reply + Verify code → admitted → APPROVE | Lookup SIM-swap data needs carrier approval and is unsupported for Indian numbers, so the deployment sets `SIM_SWAP_REQUIRED=false` (unknown status is otherwise treated as a swap). `TWILIO_MESSAGE_FALLBACK=true` delivers a question Twilio rejects to the Console phone instead. Production needs a WhatsApp Sender and an approved template (`SUBPOENA_TWILIO_WHATSAPP_CONTENT_SID`) for business-initiated messages. |
| Model Armor | Screening of testimony | `ModelArmorScreener` implemented (falls back to heuristics); deployment uses the heuristic screener | Needs a Model Armor template: set `SUBPOENA_SCREENING=model_armor` and `SUBPOENA_MODEL_ARMOR_TEMPLATE`. Flagged testimony can never auto-approve. |
| Console auth | Identity Platform + Google SSO | Sign in with a workspace API key; role derived from key scopes (`admin` → ADMIN, `evaluations:override` → ANALYST, else VIEWER); key kept in an httpOnly cookie, never in the browser | Google SSO needs an OAuth client configured in the Cloud Console. |
| Live updates | Firestore listeners in the browser | Server-sent events from the API, proxied by the Console | No Firebase client config or security rules needed; works with the in-memory store too. |
| Infra as code | Terraform | Idempotent `infra/gcp/deploy.sh` (gcloud) | Terraform was not available on the build machine; the script is a direct map to resources. |
| Stretch items | Destinations, Precedents page, Audit Log, Settings, receipt photos, voice | Not built | Out of the core scope (plan M5). Outbound webhooks with HMAC signatures and retries exist per evaluation (`options.callback_url`). |

## Debate shape

`max_rounds = 2` means opening arguments plus one rebuttal round. The citation rule strikes any
claim with no valid finding (`F#`) or precedent (`P#`) ID before the Judge sees it; struck
claims are kept in the transcript (`CLAIM_STRUCK`).

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
