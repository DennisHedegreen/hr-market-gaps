from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import EvidenceState
from .loader import load_aggregate_scenario
from .registry import CaseKind
from .version import __version__
from .runtime import CaseNotRunnableError, CaseRunner
from .storage import Observation, SQLiteStore


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hr-market-gaps")
    parser.add_argument("--root", default=".", help="repository root containing cases/")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-cases")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--all", action="store_true", help="include hidden/dev cases")

    p_run = sub.add_parser("run")
    p_run.add_argument("case_id")
    p_run.add_argument("--json", action="store_true")
    p_run.add_argument("--db", help="optional SQLite path to record the model run")

    p_db = sub.add_parser("init-db")
    p_db.add_argument("path")

    p_obs = sub.add_parser("observe")
    p_obs.add_argument("--db", required=True)
    p_obs.add_argument("--case", required=True, dest="case_id")
    p_obs.add_argument("--metric", required=True)
    p_obs.add_argument("--at", required=True, dest="observed_at")
    value = p_obs.add_mutually_exclusive_group(required=True)
    value.add_argument("--value", type=Decimal, dest="numeric_value")
    value.add_argument("--text", dest="text_value")
    p_obs.add_argument("--unit")
    p_obs.add_argument("--site")
    p_obs.add_argument("--entity")
    p_obs.add_argument("--source")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)

    if args.command == "list-cases":
        runner = CaseRunner(root)
        entries = runner.list_cases(visible_only=not args.all)
        if args.json:
            print(json.dumps([entry.model_dump(mode="json") for entry in entries], indent=2))
        else:
            for entry in entries:
                print(f"{entry.case_id}\t{entry.status.value}\t{entry.label}")
        return 0

    if args.command == "run":
        runner = CaseRunner(root)
        try:
            payload = runner.run(args.case_id)
        except KeyError:
            print(f"unknown case: {args.case_id}")
            return 2
        except CaseNotRunnableError as exc:
            print(str(exc))
            return 2
        if args.db:
            store = SQLiteStore(args.db)
            store.record_run(
                case_id=args.case_id,
                engine_kind=payload["case"]["kind"],
                input_payload=payload["input"],
                output_payload=payload["result"],
                engine_version=__version__,
            )
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
        else:
            print(f"case: {payload['case']['label']}")
            for key, value in payload["result"].items():
                print(f"{key}: {value}")
        return 0

    if args.command == "init-db":
        SQLiteStore(args.path).initialize()
        print(f"initialized: {args.path}")
        return 0

    if args.command == "observe":
        runner = CaseRunner(root)
        try:
            entry = runner.registry.by_id(args.case_id)
        except KeyError:
            print(f"unknown case: {args.case_id}")
            return 2

        site_id = args.site
        if entry.site_id:
            if site_id is None:
                site_id = entry.site_id
            elif site_id != entry.site_id:
                print(
                    f"site mismatch for {entry.case_id}: expected {entry.site_id}, got {site_id}"
                )
                return 2

        if args.entity and entry.kind == CaseKind.AGGREGATE and entry.path:
            scenario = load_aggregate_scenario(root / "cases" / entry.path)
            if args.entity not in scenario.entity_ids:
                print(
                    f"unknown entity for {entry.case_id}: {args.entity}; "
                    f"allowed: {', '.join(scenario.entity_ids)}"
                )
                return 2

        try:
            observation = Observation(
                case_id=args.case_id,
                site_id=site_id,
                entity_id=args.entity,
                observed_at=args.observed_at,
                metric=args.metric,
                numeric_value=args.numeric_value,
                text_value=args.text_value,
                unit=args.unit,
                source=args.source,
                evidence_state=EvidenceState.OBSERVED,
            )
        except ValueError as exc:
            print(f"invalid observation: {exc}")
            return 2

        store = SQLiteStore(args.db)
        observation_id = store.add_observation(observation)
        print(f"observation_id: {observation_id}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
