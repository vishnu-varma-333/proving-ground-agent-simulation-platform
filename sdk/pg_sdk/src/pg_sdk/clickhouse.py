"""ClickHouse client for evaluation results (Milestone 8 - ClickHouse's
first real write in this project; Milestone 1 stood the cluster up for
exactly this purpose - the spec's data model table names CheckResult and
JudgeScore as ClickHouse tables - but nothing wrote to it before now).

Uses ClickHouse's plain HTTP interface directly (JSONEachRow over POST)
rather than pulling in a dedicated client library: these are simple
one-shot inserts and a couple of aggregate reads, not a hot path, so raw
httpx is enough and keeps pg_sdk's dependency list unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS check_results (
        sim_id String,
        description String,
        service String,
        passed UInt8,
        detail String,
        recorded_at DateTime DEFAULT now()
    ) ENGINE = MergeTree ORDER BY (sim_id, description)
    """,
    """
    CREATE TABLE IF NOT EXISTS judge_scores (
        sim_id String,
        resolved UInt8,
        score UInt8,
        rationale String,
        model String,
        recorded_at DateTime DEFAULT now()
    ) ENGINE = MergeTree ORDER BY (sim_id)
    """,
)


@dataclass(frozen=True)
class ClickHouseConfig:
    url: str
    database: str
    user: str
    password: str

    @staticmethod
    def from_env() -> ClickHouseConfig:
        return ClickHouseConfig(
            url=os.environ.get("CLICKHOUSE_URL", "http://localhost:28123"),
            database=os.environ.get("CLICKHOUSE_DB", "proving_ground"),
            user=os.environ.get("CLICKHOUSE_USER", "proving_ground"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", "proving-ground-local-dev"),
        )


class ClickHouseClient:
    def __init__(self, config: ClickHouseConfig | None = None) -> None:
        self._config = config or ClickHouseConfig.from_env()

    def _execute(self, query: str, body: str = "") -> str:
        response = httpx.post(
            self._config.url,
            params={"database": self._config.database, "query": query},
            content=body.encode() if body else None,
            auth=(self._config.user, self._config.password),
            timeout=10.0,
        )
        response.raise_for_status()
        return response.text

    def apply_schema(self) -> None:
        for statement in SCHEMA_STATEMENTS:
            self._execute(statement)

    def _insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        body = "\n".join(json.dumps(row) for row in rows)
        self._execute(f"INSERT INTO {table} FORMAT JSONEachRow", body=body)

    def insert_check_results(self, sim_id: str, results: list[Any]) -> None:
        self._insert(
            "check_results",
            [
                {
                    "sim_id": sim_id,
                    "description": r.description,
                    "service": r.service,
                    "passed": 1 if r.passed else 0,
                    "detail": r.detail,
                }
                for r in results
            ],
        )

    def insert_judge_score(
        self, sim_id: str, resolved: bool, score: int, rationale: str, model: str
    ) -> None:
        self._insert(
            "judge_scores",
            [
                {
                    "sim_id": sim_id,
                    "resolved": 1 if resolved else 0,
                    "score": score,
                    "rationale": rationale,
                    "model": model,
                }
            ],
        )
