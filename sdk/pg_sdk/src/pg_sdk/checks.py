"""Deterministic state checks (Milestone 8's first half of core feature
#8): assertions against a simulation's *final* mock-service data, run
after the agent has finished - e.g. the spec's own example, "refund
issued exactly once". These are plain SQL assertions against the
service's own SQLite file inside the simulation's forked data_dir
(Milestone 7's fork_environment output), not a new mock-service API -
the check author already knows the schema (services/*/src/*/db.py), so
a general SQL+expected-row check covers every real assertion this
project needs without inventing a bespoke check-type taxonomy.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CheckSpec:
    description: str
    service: str
    sql: str
    params: tuple[Any, ...] = ()
    expect: dict[str, Any] | None = None

    @staticmethod
    def from_dict(data: dict) -> CheckSpec:
        return CheckSpec(
            description=data["description"],
            service=data["service"],
            sql=data["sql"],
            params=tuple(data.get("params", ())),
            expect=data.get("expect"),
        )


@dataclass(frozen=True)
class CheckResult:
    description: str
    service: str
    passed: bool
    actual: dict[str, Any] | None
    detail: str


def run_check(data_dir: Path, check: CheckSpec) -> CheckResult:
    db_path = data_dir / f"{check.service}.db"
    if not db_path.exists():
        return CheckResult(
            description=check.description,
            service=check.service,
            passed=False,
            actual=None,
            detail=f"no such service database: {db_path.name}",
        )

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(check.sql, check.params).fetchone()
    finally:
        conn.close()

    actual = dict(row) if row is not None else None
    if check.expect is None:
        passed = row is not None
        detail = "row found" if passed else "no matching row"
    elif actual is None:
        passed = False
        detail = "query returned no row to compare against `expect`"
    else:
        mismatches = {
            key: (actual.get(key), expected_value)
            for key, expected_value in check.expect.items()
            if actual.get(key) != expected_value
        }
        passed = not mismatches
        detail = "matched expect" if passed else f"mismatches: {mismatches}"

    return CheckResult(
        description=check.description,
        service=check.service,
        passed=passed,
        actual=actual,
        detail=detail,
    )


def run_checks(data_dir: Path, checks: list[CheckSpec]) -> list[CheckResult]:
    return [run_check(data_dir, check) for check in checks]
