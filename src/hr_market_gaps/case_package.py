from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .assets import AssetRevenueLayer
from .composition import CaseComposition, ConceptDefinition, OperatingModelDefinition, SiteDefinition
from .contracts import ContractSet
from .costs import FixedCostSet
from .demand import DemandSurface
from .economics import EconomicScenarioSet
from .experiments import StructuralExperimentSet
from .funding import FundingStack
from .gates import DecisionPlan
from .loader import (
    load_aggregate_scenario,
    load_asset_revenue_layer,
    load_case_composition,
    load_concept_definition,
    load_contract_set,
    load_decision_plan,
    load_demand_surface,
    load_economic_scenario_set,
    load_fixed_cost_set,
    load_funding_stack,
    load_operating_model_definition,
    load_product_catalog,
    load_revenue_adapters,
    load_site_definition,
    load_staffing_plan,
    load_structural_experiment_set,
)
from .models import AggregateScenario, Visibility
from .product import ProductCatalog
from .revenue import RevenueAdapterSet
from .staffing import StaffingPlan

CASE_PACKAGE_SCHEMA = "hr-market-gaps.case-package"
CASE_PACKAGE_VERSION = 1


class CasePackageError(ValueError):
    """A case package cannot be decoded or is not supported by this runtime."""


class CasePackageMetadata(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    case_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str = Field(default="Draft", min_length=1)
    visibility: Visibility = Visibility.PRIVATE
    description: str | None = None


class CaseWorkspace(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    meeting_brief_markdown: str = ""
    meeting_notes: str = ""
    stakeholder_answers: dict[str, str] = Field(default_factory=dict)


class CasePackage(BaseModel):
    """Portable, local-first case state shared by replaceable clients."""

    model_config = ConfigDict(extra="forbid")

    schema_name: Literal["hr-market-gaps.case-package"] = CASE_PACKAGE_SCHEMA
    schema_version: Literal[1] = CASE_PACKAGE_VERSION
    metadata: CasePackageMetadata
    aggregate_scenario: AggregateScenario
    site: SiteDefinition
    concept: ConceptDefinition
    operating_model: OperatingModelDefinition
    composition: CaseComposition
    demand_surface: DemandSurface
    product_catalog: ProductCatalog
    fixed_costs: FixedCostSet
    economic_scenarios: EconomicScenarioSet
    assets_revenue: AssetRevenueLayer
    revenue_adapters: RevenueAdapterSet
    funding: FundingStack
    contracts: ContractSet
    staffing: StaffingPlan
    decision_plan: DecisionPlan
    structural_experiments: StructuralExperimentSet
    workspace: CaseWorkspace = Field(default_factory=CaseWorkspace)


def dump_case_package_json(package: CasePackage) -> str:
    payload = package.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def load_case_package_json(payload: str | bytes | bytearray) -> CasePackage:
    try:
        raw: Any = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        message = getattr(exc, "msg", str(exc))
        raise CasePackageError(f"Case package is not valid JSON: {message}") from exc

    if not isinstance(raw, dict):
        raise CasePackageError("Case package root must be a JSON object")
    if raw.get("schema_name") != CASE_PACKAGE_SCHEMA:
        raise CasePackageError(
            f"Unsupported case package schema: {raw.get('schema_name')!r}"
        )
    if raw.get("schema_version") != CASE_PACKAGE_VERSION:
        raise CasePackageError(
            "Unsupported case package version: "
            f"{raw.get('schema_version')!r}; expected {CASE_PACKAGE_VERSION}"
        )
    try:
        return CasePackage.model_validate(raw)
    except ValidationError as exc:
        raise CasePackageError(f"Case package validation failed: {exc}") from exc


def build_case_package(
    case_directory: str | Path,
    *,
    case_id: str,
    label: str,
    concept_path: str | Path,
    operating_model_path: str | Path,
    meeting_brief_path: str | Path | None = None,
    status: str = "Draft",
    description: str | None = None,
) -> CasePackage:
    """Build a portable package from the conventional case data files."""

    case_directory = Path(case_directory)
    brief = ""
    if meeting_brief_path is not None:
        brief = Path(meeting_brief_path).read_text(encoding="utf-8")

    return CasePackage(
        metadata=CasePackageMetadata(
            case_id=case_id,
            label=label,
            status=status,
            visibility=Visibility.PRIVATE,
            description=description,
        ),
        aggregate_scenario=load_aggregate_scenario(case_directory / "snapshot.yaml"),
        site=load_site_definition(case_directory / "site.yaml"),
        concept=load_concept_definition(concept_path),
        operating_model=load_operating_model_definition(operating_model_path),
        composition=load_case_composition(case_directory / "composition.yaml"),
        demand_surface=load_demand_surface(case_directory / "demand_surface.yaml"),
        product_catalog=load_product_catalog(case_directory / "product_catalog.yaml"),
        fixed_costs=load_fixed_cost_set(case_directory / "fixed_costs.yaml"),
        economic_scenarios=load_economic_scenario_set(case_directory / "economic_scenarios.yaml"),
        assets_revenue=load_asset_revenue_layer(case_directory / "assets_revenue.yaml"),
        revenue_adapters=RevenueAdapterSet(
            adapters=load_revenue_adapters(case_directory / "revenue_adapters.yaml")
        ),
        funding=load_funding_stack(case_directory / "funding.yaml"),
        contracts=load_contract_set(case_directory / "contracts.yaml"),
        staffing=load_staffing_plan(case_directory / "staffing.yaml"),
        decision_plan=load_decision_plan(case_directory / "decision_plan.yaml"),
        structural_experiments=load_structural_experiment_set(
            case_directory / "structural_experiments.yaml"
        ),
        workspace=CaseWorkspace(meeting_brief_markdown=brief),
    )
