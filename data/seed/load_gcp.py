"""Load seed data into Google Cloud.

  BigQuery  dataset ``subpoena``: transactions, baselines, users, graph_edges, graph_flags
  Firestore ``baselines/{user_id}`` (low-latency Tier 0 reads)

Idempotent: tables are truncated and reloaded, Firestore docs overwritten.
Loading into BigQuery is free; storage for this data is far inside the free tier.

Usage: uv run python data/seed/load_gcp.py --project subpoena-ai [--location US]
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

from google.cloud import bigquery, firestore

SEED = Path(__file__).resolve().parent
DATASET = "subpoena"

F = bigquery.SchemaField
MERCHANT = F(
    "merchant",
    "RECORD",
    fields=[F("name", "STRING"), F("mcc", "STRING"), F("country", "STRING")],
)
METADATA = F(
    "metadata",
    "RECORD",
    fields=[F("ip_address", "STRING"), F("device_fingerprint", "STRING")],
)
HOME = F(
    "home",
    "RECORD",
    fields=[F("lat", "FLOAT64"), F("lng", "FLOAT64"), F("city", "STRING"), F("country", "STRING")],
)

SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    "transactions": [
        F("transaction_id", "STRING", "REQUIRED"),
        F("user_id", "STRING", "REQUIRED"),
        F("amount", "NUMERIC", "REQUIRED"),
        F("currency", "STRING"),
        F("type", "STRING"),
        F("occurred_at", "TIMESTAMP", "REQUIRED"),
        MERCHANT,
        METADATA,
        F("label", "STRING"),
    ],
    "baselines": [
        F("user_id", "STRING", "REQUIRED"),
        HOME,
        F("utc_offset_hours", "INT64"),
        F("known_devices", "STRING", "REPEATED"),
        F("known_ips", "STRING", "REPEATED"),
        F("avg_amount", "NUMERIC"),
        F("p95_amount", "NUMERIC"),
        F("txn_per_day", "FLOAT64"),
        F("active_hours", "INT64", "REPEATED"),
        F("common_mccs", "STRING", "REPEATED"),
        F("window_days", "INT64"),
        F("computed_at", "TIMESTAMP"),
    ],
    "users": [
        F("user_id", "STRING", "REQUIRED"),
        F("name", "STRING"),
        F("phone", "STRING"),
        HOME,
        F("utc_offset_hours", "INT64"),
        F("devices", "STRING", "REPEATED"),
        F("ips", "STRING", "REPEATED"),
        F("sim_swap_hours_ago", "INT64"),
        F("tags", "STRING", "REPEATED"),
    ],
    "graph_edges": [F("src", "STRING"), F("dst", "STRING"), F("type", "STRING")],
    "graph_flags": [
        F("id", "STRING"),
        F("kind", "STRING"),
        F("flag", "STRING"),
        F("since", "DATE"),
    ],
}


def rows() -> dict[str, list[dict[str, Any]]]:
    graph = json.loads((SEED / "graph.json").read_text())
    return {
        "transactions": [json.loads(line) for line in (SEED / "transactions.jsonl").open()],
        "baselines": json.loads((SEED / "baselines.json").read_text()),
        "users": json.loads((SEED / "users.json").read_text()),
        "graph_edges": graph["edges"],
        "graph_flags": graph["nodes"]["flagged"],
    }


def load_bigquery(project: str, location: str, data: dict[str, list[dict[str, Any]]]) -> None:
    client = bigquery.Client(project=project)
    dataset = bigquery.Dataset(f"{project}.{DATASET}")
    dataset.location = location
    client.create_dataset(dataset, exists_ok=True)
    for table, items in data.items():
        payload = "\n".join(json.dumps(r) for r in items).encode()
        job = client.load_table_from_file(
            io.BytesIO(payload),
            f"{project}.{DATASET}.{table}",
            job_config=bigquery.LoadJobConfig(
                schema=SCHEMAS[table],
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            ),
        )
        job.result()
        print(f"bigquery {DATASET}.{table}: {job.output_rows} rows")


def load_firestore(project: str, baselines: list[dict[str, Any]]) -> None:
    db = firestore.Client(project=project)
    batch = db.batch()
    for b in baselines:
        batch.set(db.collection("baselines").document(b["user_id"]), b)
    batch.commit()
    print(f"firestore baselines: {len(baselines)} docs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="US")
    args = parser.parse_args()
    data = rows()
    load_bigquery(args.project, args.location, data)
    load_firestore(args.project, data["baselines"])


if __name__ == "__main__":
    main()
