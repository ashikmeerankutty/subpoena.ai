#!/usr/bin/env bash
# Deploy Subpoena.ai to Google Cloud (idempotent). Everything scales to zero when idle.
#
#   infra/gcp/deploy.sh [PROJECT_ID] [REGION]
#
# Services (Cloud Run): api (public, API-key auth), console (public, key login),
# mcp (private), courtroom (private; Pub/Sub push + Cloud Tasks with OIDC).
set -euo pipefail

PROJECT=${1:-subpoena-ai}
REGION=${2:-us-central1}
REPO="$REGION-docker.pkg.dev/$PROJECT/subpoena"
TAG=${TAG:-$(date +%Y%m%d-%H%M%S)}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
G="gcloud --project=$PROJECT --quiet"
sa() { echo "$1@$PROJECT.iam.gserviceaccount.com"; }

echo "==> APIs"
$G services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  cloudtasks.googleapis.com secretmanager.googleapis.com iam.googleapis.com pubsub.googleapis.com \
  firestore.googleapis.com bigquery.googleapis.com aiplatform.googleapis.com

echo "==> Artifact Registry"
$G artifacts repositories describe subpoena --location="$REGION" >/dev/null 2>&1 ||
  $G artifacts repositories create subpoena --repository-format=docker --location="$REGION"

echo "==> Secrets"
for s in api-key-pepper agent-token-secret webhook-signing-secret; do
  $G secrets describe "$s" >/dev/null 2>&1 ||
    openssl rand -hex 32 | tr -d '\n' | $G secrets create "$s" --data-file=- --replication-policy=automatic
done

echo "==> Service accounts"
for a in sp-api sp-mcp sp-court sp-console sp-invoker; do
  $G iam service-accounts describe "$(sa $a)" >/dev/null 2>&1 ||
    $G iam service-accounts create "$a" --display-name="Subpoena.ai $a"
done
bind() { $G projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$(sa "$1")" --role="$2" --condition=None >/dev/null; }
bind sp-api roles/datastore.user
bind sp-api roles/pubsub.publisher
bind sp-mcp roles/datastore.user
bind sp-mcp roles/bigquery.dataViewer
bind sp-mcp roles/bigquery.jobUser
bind sp-court roles/datastore.user
bind sp-court roles/aiplatform.user
bind sp-court roles/cloudtasks.enqueuer
for s in api-key-pepper webhook-signing-secret; do
  $G secrets add-iam-policy-binding "$s" --member="serviceAccount:$(sa sp-api)" --role=roles/secretmanager.secretAccessor >/dev/null
done
for s in agent-token-secret webhook-signing-secret; do
  $G secrets add-iam-policy-binding "$s" --member="serviceAccount:$(sa sp-court)" --role=roles/secretmanager.secretAccessor >/dev/null
done
$G secrets add-iam-policy-binding agent-token-secret --member="serviceAccount:$(sa sp-mcp)" --role=roles/secretmanager.secretAccessor >/dev/null
# The courtroom mints OIDC tokens as sp-invoker for Cloud Tasks.
$G iam service-accounts add-iam-policy-binding "$(sa sp-invoker)" --member="serviceAccount:$(sa sp-court)" --role=roles/iam.serviceAccountUser >/dev/null
NUM=$($G projects describe "$PROJECT" --format='value(projectNumber)')
$G iam service-accounts add-iam-policy-binding "$(sa sp-invoker)" \
  --member="serviceAccount:service-$NUM@gcp-sa-pubsub.iam.gserviceaccount.com" --role=roles/iam.serviceAccountTokenCreator >/dev/null

echo "==> Firestore indexes (async)"
for extra in "" status verdict transaction.user_id; do
  args=(--collection-group=evaluations --field-config=field-path=workspace_id,order=ascending)
  [ -n "$extra" ] && args+=(--field-config=field-path=$extra,order=ascending)
  $G firestore indexes composite create "${args[@]}" --field-config=field-path=_created_at,order=descending \
    --field-config=field-path=evaluation_id,order=descending --async >/dev/null 2>&1 || true
done

echo "==> Build images ($TAG)"
if [ -z "${SKIP_BUILD:-}" ]; then
  $G builds submit "$ROOT" --config="$ROOT/infra/gcp/cloudbuild.yaml" --substitutions="_TAG=$TAG,_REPO=$REPO"
fi

COMMON=(--region="$REGION" --image="$REPO/backend:$TAG" --min-instances=0 --cpu=1)
ENV="SUBPOENA_ENV=demo,SUBPOENA_GCP_PROJECT=$PROJECT,SUBPOENA_STORE=firestore"

echo "==> MCP server"
$G run deploy subpoena-mcp "${COMMON[@]}" --service-account="$(sa sp-mcp)" --no-allow-unauthenticated \
  --memory=512Mi --max-instances=3 --concurrency=40 \
  --set-env-vars="APP=subpoena_mcp.app:create_app,$ENV,SUBPOENA_DATA=bigquery,SUBPOENA_WITNESS_CHANNEL=simulator" \
  --set-secrets="SUBPOENA_AGENT_TOKEN_SECRET=agent-token-secret:latest"
MCP_URL=$($G run services describe subpoena-mcp --region="$REGION" --format='value(status.url)')
$G run services add-iam-policy-binding subpoena-mcp --region="$REGION" --member="serviceAccount:$(sa sp-court)" --role=roles/run.invoker >/dev/null

echo "==> Cloud Tasks queue"
$G tasks queues describe subpoena-timeouts --location="$REGION" >/dev/null 2>&1 ||
  $G tasks queues create subpoena-timeouts --location="$REGION" --max-attempts=5

echo "==> Courtroom"
$G run deploy subpoena-courtroom "${COMMON[@]}" --service-account="$(sa sp-court)" --no-allow-unauthenticated \
  --memory=1Gi --max-instances=2 --concurrency=10 --timeout=600 \
  --set-env-vars="APP=subpoena_agents.service:create_app,$ENV,SUBPOENA_LLM=gemini,SUBPOENA_MCP=http,SUBPOENA_MCP_URL=$MCP_URL,SUBPOENA_MCP_AUDIENCE=$MCP_URL,SUBPOENA_TASKS_QUEUE=subpoena-timeouts,SUBPOENA_TASKS_LOCATION=$REGION,SUBPOENA_TASKS_SERVICE_ACCOUNT=$(sa sp-invoker),SUBPOENA_COURTROOM_URL=pending" \
  --set-secrets="SUBPOENA_AGENT_TOKEN_SECRET=agent-token-secret:latest,SUBPOENA_WEBHOOK_SIGNING_SECRET=webhook-signing-secret:latest"
COURT_URL=$($G run services describe subpoena-courtroom --region="$REGION" --format='value(status.url)')
$G run services update subpoena-courtroom --region="$REGION" --update-env-vars="SUBPOENA_COURTROOM_URL=$COURT_URL" >/dev/null
$G run services add-iam-policy-binding subpoena-courtroom --region="$REGION" --member="serviceAccount:$(sa sp-invoker)" --role=roles/run.invoker >/dev/null

echo "==> Pub/Sub push to courtroom"
$G pubsub topics describe subpoena.activity >/dev/null 2>&1 || $G pubsub topics create subpoena.activity
$G pubsub topics describe evaluations.created >/dev/null 2>&1 || $G pubsub topics create evaluations.created
$G pubsub subscriptions delete courtroom >/dev/null 2>&1 || true  # old pull subscription
for pair in "court-evaluations:evaluations.created" "court-activity:subpoena.activity"; do
  sub=${pair%%:*}; topic=${pair##*:}
  if $G pubsub subscriptions describe "$sub" >/dev/null 2>&1; then
    $G pubsub subscriptions update "$sub" --push-endpoint="$COURT_URL/pubsub/push" \
      --push-auth-service-account="$(sa sp-invoker)" --push-auth-token-audience="$COURT_URL" >/dev/null
  else
    $G pubsub subscriptions create "$sub" --topic="$topic" --push-endpoint="$COURT_URL/pubsub/push" \
      --push-auth-service-account="$(sa sp-invoker)" --push-auth-token-audience="$COURT_URL" \
      --ack-deadline=600 --message-retention-duration=1d --expiration-period=never \
      --min-retry-delay=10s --max-retry-delay=120s >/dev/null
  fi
done

echo "==> API"
$G run deploy subpoena-api "${COMMON[@]}" --service-account="$(sa sp-api)" --no-invoker-iam-check \
  --memory=512Mi --max-instances=3 --concurrency=80 \
  --set-env-vars="APP=subpoena_api.main:create_app,$ENV,SUBPOENA_PUBLISHER=pubsub,SUBPOENA_BASELINES=firestore,SUBPOENA_WITNESS_SIMULATOR=true" \
  --set-secrets="SUBPOENA_API_KEY_PEPPER=api-key-pepper:latest,SUBPOENA_WEBHOOK_SIGNING_SECRET=webhook-signing-secret:latest"
API_URL=$($G run services describe subpoena-api --region="$REGION" --format='value(status.url)')
$G run services update subpoena-api --region="$REGION" --update-env-vars="SUBPOENA_PUBLIC_BASE_URL=$API_URL" >/dev/null

echo "==> Console"
$G run deploy subpoena-console --region="$REGION" --image="$REPO/console:$TAG" --service-account="$(sa sp-console)" \
  --allow-unauthenticated --min-instances=0 --max-instances=2 --memory=512Mi \
  --set-env-vars="SUBPOENA_API_URL=$API_URL"
CONSOLE_URL=$($G run services describe subpoena-console --region="$REGION" --format='value(status.url)')

cat <<OUT

Deployed $TAG
  API       $API_URL
  Console   $CONSOLE_URL
  Courtroom $COURT_URL (private)
  MCP       $MCP_URL (private)

Bootstrap a workspace (prints an admin key once):
  SUBPOENA_STORE=firestore SUBPOENA_GCP_PROJECT=$PROJECT \\
  SUBPOENA_API_KEY_PEPPER=\$(gcloud secrets versions access latest --secret=api-key-pepper --project=$PROJECT) \\
  uv run python -m subpoena_api.admin create-workspace "Acme Bank"
OUT
