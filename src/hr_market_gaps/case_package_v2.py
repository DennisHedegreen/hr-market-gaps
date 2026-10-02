from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .assets import AssetRevenueLayer
from .case_package import CasePackage, CaseWorkspace
from .composition import (
    CaseComposition,
    ConceptDefinition,
    OperatingModelDefinition,
    SiteDefinition,
)
from .contracts import ContractSet
from .costs import FixedCostSet
from .demand import DemandSurface
from .economics import EconomicScenarioSet
from .experiments import StructuralExperimentSet
from .funding import FundingStack
from .gates import DecisionPlan
from .joint_product import BoundedJointProductScenario
from .models import AggregateScenario, Visibility
from .product import ProductCatalog
from .revenue import RevenueAdapterSet
from .staffing import StaffingPlan

CASE_PACKAGE_V2_SCHEMA = "hr-market-gaps.case-package"
CASE_PACKAGE_V2_VERSION = 2


class CasePackageV2Error(ValueError):
    """A modular case package cannot be decoded or safely interpreted."""


class CaseKind(StrEnum):
    SITE_BUSINESS = "site_business"
    JOINT_PRODUCT = "joint_product"
    NETWORK_MARKET = "network_market"
    GENERIC_BUSINESS = "generic_business"


class CaseCapability(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    module_id: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    required: bool = True


class PublicArtifact(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: str = Field(min_length=1)
    href: str = Field(min_length=1)
    kind: str = Field(default="link", min_length=1)


class PublicCaseRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    registry_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: str = Field(min_length=1)
    maturity: str | None = None
    summary: str = Field(min_length=1)
    boundaries: list[str] = Field(default_factory=list)
    artifacts: list[PublicArtifact] = Field(default_factory=list)


class NetworkMarketDesign(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    case_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: Literal["design_only"] = "design_only"
    kind: Literal["network_market"] = "network_market"
    note: str = Field(min_length=1)


class CasePackageV2Metadata(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    case_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: CaseKind
    status: str = Field(default="Draft", min_length=1)
    maturity: str | None = None
    visibility: Visibility = Visibility.PRIVATE
    description: str | None = None


class CasePackageModules(BaseModel):
    """Known typed modules. A case carries only the modules it actually supports."""

    model_config = ConfigDict(extra="forbid")

    aggregate_scenario: AggregateScenario | None = None
    joint_product_scenario: BoundedJointProductScenario | None = None
    network_market_design: NetworkMarketDesign | None = None
    public_record: PublicCaseRecord | None = None

    site: SiteDefinition | None = None
    concept: ConceptDefinition | None = None
    operating_model: OperatingModelDefinition | None = None
    composition: CaseComposition | None = None
    demand_surface: DemandSurface | None = None
    product_catalog: ProductCatalog | None = None
    fixed_costs: FixedCostSet | None = None
    economic_scenarios: EconomicScenarioSet | None = None
    assets_revenue: AssetRevenueLayer | None = None
    revenue_adapters: RevenueAdapterSet | None = None
    funding: FundingStack | None = None
    contracts: ContractSet | None = None
    staffing: StaffingPlan | None = None
    decision_plan: DecisionPlan | None = None
    structural_experiments: StructuralExperimentSet | None = None


KNOWN_MODULES = frozenset(CasePackageModules.model_fields)


class CasePackageV2(BaseModel):
    """Portable modular package shared by public readers and private workspaces."""

    model_config = ConfigDict(extra="forbid")

    schema_name: Literal["hr-market-gaps.case-package"] = CASE_PACKAGE_V2_SCHEMA
    schema_version: Literal[2] = CASE_PACKAGE_V2_VERSION
    metadata: CasePackageV2Metadata
    capabilities: list[CaseCapability]
    modules: CasePackageModules
    workspace: CaseWorkspace = Field(default_factory=CaseWorkspace)
    extensions: dict[str, Any] = Field(default_factory=dict)
    migrated_from_schema_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def capabilities_match_payload(self) -> "CasePackageV2":
        ids = [capability.module_id for capability in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("capability module_id values must be unique")

        declared = set(ids)
        present = {
            module_id
            for module_id in KNOWN_MODULES
            if getattr(self.modules, module_id) is not None
        }
        undeclared = present - declared
        if undeclared:
            raise ValueError(
                "module payload is not declared in capabilities: "
                + ", ".join(sorted(undeclared))
            )

        for capability in self.capabilities:
            if capability.module_id in KNOWN_MODULES:
                if capability.schema_version != 1 and capability.module_id in present:
                    raise ValueError(
                        f"unsupported populated module version: "
                        f"{capability.module_id}@{capability.schema_version}"
                    )
                if capability.required and capability.module_id not in present:
                    raise ValueError(
                        f"required module payload is missing: {capability.module_id}"
                    )
            elif capability.required:
                raise ValueError(
                    f"unsupported required capability: {capability.module_id}"
                )

        extension_ids = set(self.extensions)
        if not extension_ids <= (declared - KNOWN_MODULES):
            invalid = extension_ids - (declared - KNOWN_MODULES)
            raise ValueError(
                "extension payload lacks an unknown optional capability: "
                + ", ".join(sorted(invalid))
            )

        required_by_kind = {
            CaseKind.SITE_BUSINESS: {"site", "concept"},
            CaseKind.JOINT_PRODUCT: {"joint_product_scenario"},
            CaseKind.NETWORK_MARKET: {"network_market_design"},
            CaseKind.GENERIC_BUSINESS: set(),
        }
        missing_kind_modules = required_by_kind[self.metadata.kind] - present
        if missing_kind_modules:
            raise ValueError(
                f"{self.metadata.kind.value} package is missing its core module: "
                + ", ".join(sorted(missing_kind_modules))
            )

        if (
            self.metadata.visibility == Visibility.PUBLIC
            and self.modules.public_record is None
        ):
            raise ValueError("public package requires a public_record module")
        if (
            self.metadata.visibility == Visibility.PUBLIC
            and self.workspace != CaseWorkspace()
        ):
            raise ValueError(
                "public package cannot contain private workspace content"
            )
        return self


def dump_case_package_v2_json(package: CasePackageV2) -> str:
    payload = package.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def load_case_package_v2_json(payload: str | bytes | bytearray) -> CasePackageV2:
    try:
        raw: Any = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        message = getattr(exc, "msg", str(exc))
        raise CasePackageV2Error(
            f"Case package is not valid JSON: {message}"
        ) from exc

    if not isinstance(raw, dict):
        raise CasePackageV2Error("Case package root must be a JSON object")
    if raw.get("schema_name") != CASE_PACKAGE_V2_SCHEMA:
        raise CasePackageV2Error(
            f"Unsupported case package schema: {raw.get('schema_name')!r}"
        )
    if raw.get("schema_version") != CASE_PACKAGE_V2_VERSION:
        raise CasePackageV2Error(
            "Unsupported modular case package version: "
            f"{raw.get('schema_version')!r}; expected {CASE_PACKAGE_V2_VERSION}"
        )
    try:
        return CasePackageV2.model_validate(raw)
    except ValueError as exc:
        raise CasePackageV2Error(
            f"Case package validation failed: {exc}"
        ) from exc


def migrate_v1_package(package: CasePackage) -> CasePackageV2:
    modules = CasePackageModules(
        aggregate_scenario=package.aggregate_scenario,
        site=package.site,
        concept=package.concept,
        operating_model=package.operating_model,
        composition=package.composition,
        demand_surface=package.demand_surface,
        product_catalog=package.product_catalog,
        fixed_costs=package.fixed_costs,
        economic_scenarios=package.economic_scenarios,
        assets_revenue=package.assets_revenue,
        revenue_adapters=package.revenue_adapters,
        funding=package.funding,
        contracts=package.contracts,
        staffing=package.staffing,
        decision_plan=package.decision_plan,
        structural_experiments=package.structural_experiments,
    )
    capabilities = [
        CaseCapability(module_id=module_id)
        for module_id in sorted(KNOWN_MODULES)
        if getattr(modules, module_id) is not None
    ]
    return CasePackageV2(
        metadata=CasePackageV2Metadata(
            case_id=package.metadata.case_id,
            label=package.metadata.label,
            kind=CaseKind.SITE_BUSINESS,
            status=package.metadata.status,
            visibility=package.metadata.visibility,
            description=package.metadata.description,
        ),
        capabilities=capabilities,
        modules=modules,
        workspace=package.workspace,
        migrated_from_schema_version=package.schema_version,
    )


def build_joint_product_v2_package(
    scenario: BoundedJointProductScenario,
    *,
    record: PublicCaseRecord | None = None,
) -> CasePackageV2:
    modules = CasePackageModules(
        joint_product_scenario=scenario,
        public_record=record,
    )
    capabilities = [CaseCapability(module_id="joint_product_scenario")]
    if record is not None:
        capabilities.append(CaseCapability(module_id="public_record"))
    return CasePackageV2(
        metadata=CasePackageV2Metadata(
            case_id=scenario.case_id,
            label=scenario.label,
            kind=CaseKind.JOINT_PRODUCT,
            status="Public case" if record is not None else "Draft",
            maturity=scenario.evidence_maturity,
            visibility=Visibility.PUBLIC if record is not None else Visibility.PRIVATE,
            description=scenario.note,
        ),
        capabilities=capabilities,
        modules=modules,
    )


def build_network_market_v2_package(
    design: NetworkMarketDesign,
    *,
    record: PublicCaseRecord | None = None,
) -> CasePackageV2:
    modules = CasePackageModules(
        network_market_design=design,
        public_record=record,
    )
    capabilities = [CaseCapability(module_id="network_market_design")]
    if record is not None:
        capabilities.append(CaseCapability(module_id="public_record"))
    return CasePackageV2(
        metadata=CasePackageV2Metadata(
            case_id=design.case_id,
            label=design.label,
            kind=CaseKind.NETWORK_MARKET,
            status=design.status,
            visibility=Visibility.PUBLIC if record is not None else Visibility.PRIVATE,
            description=design.note,
        ),
        capabilities=capabilities,
        modules=modules,
    )

