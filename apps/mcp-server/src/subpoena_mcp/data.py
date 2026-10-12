"""Read-only bank data behind the MCP resources and tools.

``SeedData`` serves ``data/seed`` (local dev, tests). ``BigQueryData`` reads transactions,
users and the entity graph from BigQuery. Reference data (IP intelligence, merchant
registry, precedents) ships with the seed in both modes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from subpoena_schemas import UserBaseline


class DataSource(Protocol):
    def baseline(self, user_id: str) -> UserBaseline | None: ...
    def user(self, user_id: str) -> dict[str, Any] | None: ...
    def user_by_phone(self, phone: str) -> dict[str, Any] | None: ...
    def recent_transactions(
        self, user_id: str, limit: int = 50, before: datetime | None = None
    ) -> list[dict[str, Any]]: ...
    def graph_neighbors(self, entity_id: str) -> dict[str, Any]: ...
    def ip_info(self, ip: str) -> dict[str, Any] | None: ...
    def merchant(self, name: str) -> dict[str, Any] | None: ...
    def precedents(self, query: str, limit: int = 3) -> list[dict[str, Any]]: ...


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class _ReferenceData:
    def __init__(self, seed_dir: Path) -> None:
        def load(name: str) -> Any:
            return json.loads((seed_dir / name).read_text())

        self._ip = load("ip_geo.json")
        self._merchants = {_norm(m["name"]): m for m in load("merchants.json")}
        self._precedents: list[dict[str, Any]] = load("precedents.json")
        self._baselines = {
            b["user_id"]: UserBaseline.model_validate(b) for b in load("baselines.json")
        }

    def ip_info(self, ip: str) -> dict[str, Any] | None:
        info = self._ip.get(ip)
        return dict(info) if info else None

    def merchant(self, name: str) -> dict[str, Any] | None:
        return self._merchants.get(_norm(name))

    def baseline(self, user_id: str) -> UserBaseline | None:
        return self._baselines.get(user_id)

    def precedents(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Keyword-overlap ranking; stands in for vector search over past rulings."""
        words = set(re.findall(r"[a-z0-9_]+", query.lower()))

        def score(p: dict[str, Any]) -> int:
            text = set(re.findall(r"[a-z0-9_]+", p["summary"].lower())) | set(p["tags"])
            return len(words & text)

        ranked = sorted(self._precedents, key=score, reverse=True)
        return [p for p in ranked if score(p) > 0][:limit]


class SeedData(_ReferenceData):
    def __init__(self, seed_dir: Path) -> None:
        super().__init__(seed_dir)
        self._users = {u["user_id"]: u for u in json.loads((seed_dir / "users.json").read_text())}
        self._txns: dict[str, list[dict[str, Any]]] = {}
        with (seed_dir / "transactions.jsonl").open() as f:
            for line in f:
                row = json.loads(line)
                self._txns.setdefault(row["user_id"], []).append(row)
        graph = json.loads((seed_dir / "graph.json").read_text())
        self._edges: list[dict[str, str]] = graph["edges"]
        self._flags = {n["id"]: n for n in graph["nodes"]["flagged"]}

    def user(self, user_id: str) -> dict[str, Any] | None:
        return self._users.get(user_id)

    def user_by_phone(self, phone: str) -> dict[str, Any] | None:
        return next((u for u in self._users.values() if u["phone"] == phone), None)

    def recent_transactions(
        self, user_id: str, limit: int = 50, before: datetime | None = None
    ) -> list[dict[str, Any]]:
        rows = self._txns.get(user_id, [])
        if before is not None:
            cutoff = before.isoformat().replace("+00:00", "Z")
            rows = [r for r in rows if r["occurred_at"] < cutoff]
        return list(reversed(rows[-limit:]))

    def graph_neighbors(self, entity_id: str) -> dict[str, Any]:
        neighbors = []
        for e in self._edges:
            if entity_id in (e["src"], e["dst"]):
                other = e["dst"] if e["src"] == entity_id else e["src"]
                neighbors.append(
                    {"id": other, "edge": e["type"], "flag": self._flags.get(other, {}).get("flag")}
                )
        return {
            "entity": entity_id,
            "flag": self._flags.get(entity_id, {}).get("flag"),
            "neighbors": neighbors,
        }


class BigQueryData(_ReferenceData):
    def __init__(self, seed_dir: Path, project: str, dataset: str) -> None:
        from google.cloud import bigquery

        super().__init__(seed_dir)
        self._bq = bigquery.Client(project=project)
        self._ds = f"`{project}.{dataset}`"
        self._bigquery = bigquery

    def _query(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        bq = self._bigquery
        qp = [
            bq.ScalarQueryParameter(
                k,
                "TIMESTAMP"
                if isinstance(v, datetime)
                else "INT64"
                if isinstance(v, int)
                else "STRING",
                v,
            )
            for k, v in params.items()
        ]
        job = self._bq.query(
            sql.replace("{ds}", self._ds), job_config=bq.QueryJobConfig(query_parameters=qp)
        )
        return [json.loads(json.dumps(dict(r), default=str)) for r in job.result()]

    def user(self, user_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM {ds}.users WHERE user_id = @u", u=user_id)
        return rows[0] if rows else None

    def user_by_phone(self, phone: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM {ds}.users WHERE phone = @p", p=phone)
        return rows[0] if rows else None

    def recent_transactions(
        self, user_id: str, limit: int = 50, before: datetime | None = None
    ) -> list[dict[str, Any]]:
        where = "user_id = @u" + (" AND occurred_at < @before" if before else "")
        params: dict[str, Any] = {"u": user_id, "n": limit}
        if before:
            params["before"] = before
        return self._query(
            f"SELECT * FROM {{ds}}.transactions WHERE {where} ORDER BY occurred_at DESC LIMIT @n",
            **params,
        )

    def graph_neighbors(self, entity_id: str) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT IF(e.src = @id, e.dst, e.src) AS id, e.type AS edge, f.flag
            FROM {ds}.graph_edges e
            LEFT JOIN {ds}.graph_flags f ON f.id = IF(e.src = @id, e.dst, e.src)
            WHERE @id IN (e.src, e.dst)
            """,
            id=entity_id,
        )
        flag = self._query("SELECT flag FROM {ds}.graph_flags WHERE id = @id", id=entity_id)
        return {"entity": entity_id, "flag": flag[0]["flag"] if flag else None, "neighbors": rows}
