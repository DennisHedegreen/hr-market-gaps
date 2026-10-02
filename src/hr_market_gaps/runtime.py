from __future__ import annotations

from pathlib import Path
from typing import Any

from .engine import DeterministicEngine
from .joint_product import JointProductEngine
from .loader import load_aggregate_scenario, load_joint_product_scenario
from .registry import CaseKind, CaseRegistryEntry, CaseStatus, load_case_registry


class CaseNotRunnableError(RuntimeError):
    pass


class CaseRunner:
    """Stable application boundary used by CLI/API/desktop clients."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.registry_path = self.repo_root / "cases" / "registry.yaml"
        self.registry = load_case_registry(self.registry_path)

    def list_cases(self, *, visible_only: bool = False) -> list[CaseRegistryEntry]:
        cases = self.registry.cases
        if visible_only:
            cases = [entry for entry in cases if entry.display_in_ui]
        return cases

    def run(self, case_id: str) -> dict[str, Any]:
        entry = self.registry.by_id(case_id)
        if entry.status != CaseStatus.RUNNABLE:
            raise CaseNotRunnableError(
                f"{entry.case_id} is {entry.status.value}; it has no canonical runnable model yet"
            )
        assert entry.path is not None
        case_path = self.repo_root / "cases" / entry.path

        if entry.kind == CaseKind.AGGREGATE:
            scenario = load_aggregate_scenario(case_path)
            result = DeterministicEngine().run(scenario)
        elif entry.kind == CaseKind.JOINT_PRODUCT:
            scenario = load_joint_product_scenario(case_path)
            result = JointProductEngine().run(scenario)
        else:
            raise CaseNotRunnableError(
                f"No runner implemented for case kind {entry.kind.value}"
            )

        return {
            "case": entry.model_dump(mode="json"),
            "input": scenario.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }
