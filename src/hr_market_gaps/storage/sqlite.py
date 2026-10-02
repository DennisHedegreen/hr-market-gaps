from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..models import EvidenceState


SCHEMA_VERSION = 1


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _validate_offset_aware_iso8601(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be a valid ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone offset or Z")


@dataclass(frozen=True)
class Observation:
    case_id: str
    observed_at: str
    metric: str
    numeric_value: Decimal | None = None
    text_value: str | None = None
    unit: str | None = None
    site_id: str | None = None
    entity_id: str | None = None
    source: str | None = None
    evidence_state: EvidenceState = EvidenceState.OBSERVED
    metadata: dict[str, Any] = field(default_factory=dict)
    observation_id: int | None = None

    def __post_init__(self) -> None:
        case_id = self.case_id.strip()
        metric = self.metric.strip()
        if not case_id:
            raise ValueError("observation case_id cannot be blank")
        if not metric:
            raise ValueError("observation metric cannot be blank")
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "metric", metric)
        for field_name in ("site_id", "entity_id", "unit", "source"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, value.strip() or None)
        _validate_offset_aware_iso8601(self.observed_at)
        if self.numeric_value is None and self.text_value is None:
            raise ValueError("observation requires numeric_value or text_value")
        if self.numeric_value is not None and self.text_value is not None:
            raise ValueError("observation cannot have both numeric_value and text_value")
        if self.numeric_value is not None and not self.numeric_value.is_finite():
            raise ValueError("observation numeric_value must be finite")


class SQLiteStore:
    """Local-first observation/run store for future digital-twin feedback loops."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    site_id TEXT,
                    entity_id TEXT,
                    observed_at TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    numeric_value TEXT,
                    text_value TEXT,
                    unit TEXT,
                    evidence_state TEXT NOT NULL,
                    source TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    CHECK ((numeric_value IS NULL) != (text_value IS NULL))
                );

                CREATE INDEX IF NOT EXISTS idx_observations_case_time
                ON observations(case_id, observed_at);

                CREATE INDEX IF NOT EXISTS idx_observations_metric
                ON observations(case_id, metric, observed_at);

                CREATE TABLE IF NOT EXISTS model_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    engine_kind TEXT NOT NULL,
                    ran_at TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    engine_version TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def add_observation(self, observation: Observation) -> int:
        self.initialize()
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO observations(
                    case_id, site_id, entity_id, observed_at, metric,
                    numeric_value, text_value, unit, evidence_state,
                    source, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.case_id,
                    observation.site_id,
                    observation.entity_id,
                    observation.observed_at,
                    observation.metric,
                    None if observation.numeric_value is None else str(observation.numeric_value),
                    observation.text_value,
                    observation.unit,
                    observation.evidence_state.value,
                    observation.source,
                    json.dumps(observation.metadata, sort_keys=True, ensure_ascii=False, default=_json_default),
                    created_at,
                ),
            )
            return int(cur.lastrowid)

    def list_observations(self, case_id: str, metric: str | None = None) -> list[Observation]:
        self.initialize()
        query = "SELECT * FROM observations WHERE case_id = ?"
        params: list[Any] = [case_id]
        if metric is not None:
            query += " AND metric = ?"
            params.append(metric)
        query += " ORDER BY julianday(observed_at), id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Observation(
                observation_id=row["id"],
                case_id=row["case_id"],
                site_id=row["site_id"],
                entity_id=row["entity_id"],
                observed_at=row["observed_at"],
                metric=row["metric"],
                numeric_value=(Decimal(row["numeric_value"]) if row["numeric_value"] is not None else None),
                text_value=row["text_value"],
                unit=row["unit"],
                evidence_state=EvidenceState(row["evidence_state"]),
                source=row["source"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def record_run(
        self,
        *,
        case_id: str,
        engine_kind: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        engine_version: str,
    ) -> int:
        self.initialize()
        ran_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO model_runs(case_id, engine_kind, ran_at, input_json, output_json, engine_version)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    engine_kind,
                    ran_at,
                    json.dumps(input_payload, sort_keys=True, ensure_ascii=False, default=_json_default),
                    json.dumps(output_payload, sort_keys=True, ensure_ascii=False, default=_json_default),
                    engine_version,
                ),
            )
            return int(cur.lastrowid)
