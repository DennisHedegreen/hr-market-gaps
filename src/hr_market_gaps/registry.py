from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class CaseKind(StrEnum):
    AGGREGATE = "aggregate"
    JOINT_PRODUCT = "joint_product"
    NETWORK_MARKET = "network_market"


class CaseStatus(StrEnum):
    RUNNABLE = "runnable"
    DESIGN_ONLY = "design_only"
    BLOCKED = "blocked"


class CaseRegistryEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: CaseKind
    status: CaseStatus
    path: str | None = None
    display_in_ui: bool = True
    site_id: str | None = None
    concept_id: str | None = None
    operating_model_id: str | None = None
    note: str | None = None


class CaseRegistry(BaseModel):
    cases: list[CaseRegistryEntry]

    def by_id(self, case_id: str) -> CaseRegistryEntry:
        for entry in self.cases:
            if entry.case_id == case_id:
                return entry
        raise KeyError(case_id)


def load_case_registry(path: str | Path) -> CaseRegistry:
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    registry = CaseRegistry.model_validate(raw)
    ids = [entry.case_id for entry in registry.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case registry contains duplicate case_id values")
    cases_root = path.parent.resolve()
    for entry in registry.cases:
        if entry.status == CaseStatus.RUNNABLE and not entry.path:
            raise ValueError(f"runnable case {entry.case_id} requires path")
        if entry.path:
            relative = Path(entry.path)
            if relative.is_absolute():
                raise ValueError(f"case {entry.case_id} path must be relative to cases/")
            resolved = (cases_root / relative).resolve()
            try:
                resolved.relative_to(cases_root)
            except ValueError as exc:
                raise ValueError(
                    f"case {entry.case_id} path escapes the cases directory"
                ) from exc
            if entry.status == CaseStatus.RUNNABLE and not resolved.is_file():
                raise ValueError(
                    f"runnable case {entry.case_id} path does not exist: {entry.path}"
                )
    return registry
