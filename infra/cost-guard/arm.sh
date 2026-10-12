#!/usr/bin/env bash
# Make the kill switch live: billing is unlinked when spend reaches the budget.
set -euo pipefail
PROJECT_ID=$1
gcloud functions deploy cost-guard --gen2 --region=us-central1 --project="$PROJECT_ID" \
  --update-env-vars=DRY_RUN=false --quiet --source="$(cd "$(dirname "$0")" && pwd)" \
  --entry-point=stop_billing --runtime=python312 --trigger-topic=budget-alerts
echo "Kill switch ARMED for $PROJECT_ID"
