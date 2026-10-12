#!/usr/bin/env bash
# Hard spend cap for the demo project.
#
#   infra/cost-guard/setup.sh <PROJECT_ID> <BILLING_ACCOUNT_ID> [BUDGET_USD=20]
#
# 1. Budget with email alerts at 25/50/75/90/100% of actual and 100% of forecast spend.
# 2. Budget notifications -> Pub/Sub -> Cloud Function that unlinks billing at 100%.
# The function is deployed with DRY_RUN=true; run `arm.sh` after testing to make it live.
set -euo pipefail

PROJECT_ID=$1
BILLING_ACCOUNT=$2
BUDGET=${3:-20}
REGION=us-central1
TOPIC=budget-alerts
SA=cost-guard@${PROJECT_ID}.iam.gserviceaccount.com
HERE=$(cd "$(dirname "$0")" && pwd)

gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling APIs"
gcloud services enable cloudbilling.googleapis.com billingbudgets.googleapis.com \
  pubsub.googleapis.com cloudfunctions.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com eventarc.googleapis.com artifactregistry.googleapis.com

echo "==> Pub/Sub topic"
gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"

echo "==> Service account with permission to unlink billing"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 ||
  gcloud iam service-accounts create cost-guard --display-name="Billing kill switch"
gcloud billing accounts add-iam-policy-binding "$BILLING_ACCOUNT" \
  --member="serviceAccount:$SA" --role=roles/billing.admin >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA" --role=roles/billing.projectManager --condition=None >/dev/null

echo "==> Deploying function (DRY_RUN=true)"
gcloud functions deploy cost-guard --gen2 --region="$REGION" --runtime=python312 \
  --source="$HERE" --entry-point=stop_billing --trigger-topic="$TOPIC" \
  --service-account="$SA" --run-service-account="$SA" \
  --max-instances=1 --memory=256Mi \
  --set-env-vars="PROJECT_ID=$PROJECT_ID,DRY_RUN=true" --quiet

echo "==> Budget: \$$BUDGET"
if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" \
    --format="value(displayName)" | grep -qx "subpoena-ai cap"; then
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
    --display-name="subpoena-ai cap" --budget-amount="${BUDGET}USD" \
    --filter-projects="projects/$PROJECT_ID" --calendar-period=month \
    --threshold-rule=percent=0.25 --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.75 --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0 --threshold-rule=percent=1.0,basis=forecasted-spend \
    --notifications-rule-pubsub-topic="projects/$PROJECT_ID/topics/$TOPIC"
fi
echo "Done. Test with test.sh, then arm with arm.sh."
