from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AggregateScenario
from .assets import AssetRevenueLayer
from .costs import FixedCostSet
from .contracts import ContractSet
from .demand import DemandSurface
from .economics import EconomicScenarioSet
from .experiments import StructuralExperimentSet
from .funding import FundingStack
from .gates import DecisionPlan
from .joint_product import BoundedJointProductScenario
from .product import ProductCatalog
from .revenue import RevenueAdapterConfig, RevenueAdapterSet
from .slots import OperatingSchedule
from .staffing import StaffingPlan


def _load_yaml(path: str | Path) -> Any:
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_aggregate_scenario(path: str | Path) -> AggregateScenario:
    raw = _load_yaml(path)
    return AggregateScenario.model_validate(raw)


def load_revenue_adapters(path: str | Path) -> list[RevenueAdapterConfig]:
    raw = _load_yaml(path)
    if raw is None:
        raw = {"adapters": []}
    return RevenueAdapterSet.model_validate(raw).adapters


def dump_revenue_adapters_yaml(adapters: list[RevenueAdapterConfig]) -> str:
    validated = RevenueAdapterSet(adapters=adapters)
    payload = validated.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def load_operating_schedule(path: str | Path) -> OperatingSchedule:
    raw = _load_yaml(path)
    return OperatingSchedule.model_validate(raw)


def dump_operating_schedule_yaml(schedule: OperatingSchedule) -> str:
    payload = schedule.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def load_joint_product_scenario(path: str | Path) -> BoundedJointProductScenario:
    raw = _load_yaml(path)
    return BoundedJointProductScenario.model_validate(raw)


def load_product_catalog(path: str | Path) -> ProductCatalog:
    raw = _load_yaml(path)
    return ProductCatalog.model_validate(raw)


def load_demand_surface(path: str | Path) -> DemandSurface:
    raw = _load_yaml(path)
    return DemandSurface.model_validate(raw)


def load_fixed_cost_set(path: str | Path) -> FixedCostSet:
    raw = _load_yaml(path)
    return FixedCostSet.model_validate(raw)


def load_economic_scenario_set(path: str | Path) -> EconomicScenarioSet:
    raw = _load_yaml(path)
    return EconomicScenarioSet.model_validate(raw)


def load_asset_revenue_layer(path: str | Path) -> AssetRevenueLayer:
    raw = _load_yaml(path)
    return AssetRevenueLayer.model_validate(raw)


def load_funding_stack(path: str | Path) -> FundingStack:
    raw = _load_yaml(path)
    return FundingStack.model_validate(raw)


def load_contract_set(path: str | Path) -> ContractSet:
    raw = _load_yaml(path)
    return ContractSet.model_validate(raw)


def load_staffing_plan(path: str | Path) -> StaffingPlan:
    raw = _load_yaml(path)
    return StaffingPlan.model_validate(raw)


def load_decision_plan(path: str | Path) -> DecisionPlan:
    raw = _load_yaml(path)
    return DecisionPlan.model_validate(raw)


def load_structural_experiment_set(path: str | Path) -> StructuralExperimentSet:
    raw = _load_yaml(path)
    return StructuralExperimentSet.model_validate(raw)


def load_site_definition(path: str | Path):
    from .composition import SiteDefinition

    return SiteDefinition.model_validate(_load_yaml(path))


def load_concept_definition(path: str | Path):
    from .composition import ConceptDefinition

    return ConceptDefinition.model_validate(_load_yaml(path))


def load_operating_model_definition(path: str | Path):
    from .composition import OperatingModelDefinition

    return OperatingModelDefinition.model_validate(_load_yaml(path))


def load_case_composition(path: str | Path):
    from .composition import CaseComposition

    return CaseComposition.model_validate(_load_yaml(path))
