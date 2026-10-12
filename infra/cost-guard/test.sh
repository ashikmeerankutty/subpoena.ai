#!/usr/bin/env bash
# Publish a fake over-budget notification and show the function's reaction.
# Safe while DRY_RUN=true (logs "would disable"); DO NOT run after arm.sh.
set -euo pipefail
PROJECT_ID=$1
gcloud pubsub topics publish budget-alerts --project="$PROJECT_ID" \
  --message='{"costAmount": 25.0, "budgetAmount": 20.0, "currencyCode": "USD"}'
sleep 20
gcloud functions logs read cost-guard --gen2 --region=us-central1 --project="$PROJECT_ID" --limit=10
