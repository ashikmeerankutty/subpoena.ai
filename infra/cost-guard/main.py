"""Billing kill switch: unlinks billing from the project once spend reaches the budget.

Triggered by Cloud Billing budget notifications on Pub/Sub. Budget data lags actual
usage by hours, so the budget is set below the real ceiling to leave headroom.

Disabling billing stops every paid service in the project. Resources may be deleted
if billing stays off, which is acceptable here: all demo data can be re-seeded.
"""

from __future__ import annotations

import base64
import json
import logging
import os

import functions_framework
from cloudevents.http import CloudEvent
from googleapiclient import discovery

PROJECT_ID = os.environ["PROJECT_ID"]
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cost-guard")


def _billing():  # type: ignore[no-untyped-def]
    return discovery.build("cloudbilling", "v1", cache_discovery=False)


def billing_enabled(project_name: str) -> bool:
    info = _billing().projects().getBillingInfo(name=project_name).execute()
    return bool(info.get("billingEnabled"))


@functions_framework.cloud_event
def stop_billing(event: CloudEvent) -> None:
    data = json.loads(base64.b64decode(event.data["message"]["data"]).decode())
    cost, budget = float(data["costAmount"]), float(data["budgetAmount"])
    log.info(
        "budget notification: cost=%.2f budget=%.2f %s", cost, budget, data.get("currencyCode")
    )
    if cost < budget:
        return

    name = f"projects/{PROJECT_ID}"
    if not billing_enabled(name):
        log.info("billing already disabled for %s", PROJECT_ID)
        return
    if DRY_RUN:
        log.warning(
            "DRY_RUN: would disable billing for %s (cost %.2f >= %.2f)", PROJECT_ID, cost, budget
        )
        return
    _billing().projects().updateBillingInfo(name=name, body={"billingAccountName": ""}).execute()
    log.critical("billing DISABLED for %s (cost %.2f >= budget %.2f)", PROJECT_ID, cost, budget)
