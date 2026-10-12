"""Drive the Spec §17 demo against a running API, using only public endpoints.

  uv run python -m subpoena_agents.demo --api https://...run.app --key sk_live_...

1. coffee            -> approved at Tier 0
2. auto parts        -> courtroom deadlock -> subpoena -> witness replies + code -> APPROVE
3. SIM swap          -> Bailiff lookup fails -> BLOCK + ESCALATE
4. clear fraud       -> BLOCK without a subpoena
5. sanctioned        -> Tier 0 hard rule

Each run uses fresh transaction IDs, so it can be repeated; for a clean Console start a new
workspace with ``python -m subpoena_api.admin create-workspace``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

SEED = Path(__file__).resolve().parents[4] / "data" / "seed" / "scenarios.json"
FINAL = {"RULED", "ESCALATED", "APPEALED"}


class Demo:
    def __init__(self, api: str, key: str) -> None:
        self.http = httpx.Client(
            base_url=api.rstrip("/") + "/v1", headers={"Authorization": f"Bearer {key}"}, timeout=60
        )
        self.scenarios = {s["name"]: s for s in json.loads(SEED.read_text())}

    def send(self, name: str) -> dict[str, Any]:
        req = dict(self.scenarios[name]["request"])
        req["transaction_id"] = f"{req['transaction_id']}_{uuid.uuid4().hex[:6]}"
        r = self.http.post("/evaluations", json=req, headers={"Idempotency-Key": str(uuid.uuid4())})
        r.raise_for_status()
        return dict(r.json())

    def wait(self, eid: str, until: set[str], timeout: float = 180) -> dict[str, Any]:
        end = time.time() + timeout
        while time.time() < end:
            ev: dict[str, Any] = self.http.get(f"/evaluations/{eid}").json()
            if ev["status"] in until:
                return ev
            time.sleep(2)
        raise TimeoutError(f"{eid} stuck in {ev['status']}")

    def reply(self, phone: str, body: str) -> None:
        self.http.post(
            "/simulator/witness-reply", json={"phone": phone, "body": body}
        ).raise_for_status()

    def code_for(self, subpoena_id: str) -> str:
        for _ in range(30):
            sub = self.http.get(f"/subpoenas/{subpoena_id}").json()
            for m in reversed(sub["messages"]):
                if "code is " in m["body"]:
                    return str(m["body"].split("code is ")[1][:6])
            time.sleep(1)
        raise TimeoutError("no verification code delivered")


def line(step: str, ev: dict[str, Any], expect: str) -> bool:
    got = f"{ev['status']}/{ev['verdict']}"
    ok = got == expect
    p = ev.get("p_fraud")
    print(
        f"  {'✓' if ok else '✗'} {step:<28} {got:<22} p_fraud={p if p is not None else '—':<5} "
        f"expected {expect}  {ev['evaluation_id']}"
    )
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--key", required=True)
    a = ap.parse_args()
    d = Demo(a.api, a.key)
    results = []

    print("1. Clear case")
    results.append(line("coffee", d.send("coffee"), "RULED/APPROVE"))

    print("2. The deadlock + 3. the witness + 4. the verdict")
    ev = d.wait(d.send("auto_parts_deadlock")["evaluation_id"], FINAL | {"AWAITING_TESTIMONY"})
    print(
        f"    courtroom: {ev['status']} p_fraud={ev['p_fraud']} subpoena={ev['subpoena'] and ev['subpoena']['id']}"
    )
    if ev["status"] == "AWAITING_TESTIMONY":
        phone = d.scenarios["auto_parts_deadlock"]["request"]["witness"]["phone"]
        d.reply(phone, "Yes, parts for my BMW E36 project")
        d.reply(phone, d.code_for(ev["subpoena"]["id"]))
        ev = d.wait(ev["evaluation_id"], FINAL)
    results.append(line("auto parts after testimony", ev, "RULED/APPROVE"))

    print("5. The attack (SIM swap)")
    ev = d.wait(d.send("sim_swap")["evaluation_id"], FINAL)
    results.append(line("sim swap", ev, "ESCALATED/BLOCK"))

    print("Extra: clear fraud and sanctioned merchant")
    ev = d.wait(d.send("clear_fraud")["evaluation_id"], FINAL)
    results.append(line("clear fraud", ev, "RULED/BLOCK"))
    results.append(line("sanctioned country", d.send("sanctioned_country"), "RULED/BLOCK"))

    stats = d.http.get("/stats/overview?hours=1").json()
    print(
        f"6. Overview: {stats['evaluations']} evaluations, {stats['false_positives_avoided']} false "
        f"positive(s) avoided, cost/case {stats['cost_per_courtroom_case_usd']}"
    )
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
