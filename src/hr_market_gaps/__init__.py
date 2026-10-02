"""HR Market Gaps Engine core package.

Core modules have no dependency on Streamlit, FastAPI, Tauri, React or SQLite UI
concerns. Client surfaces call the same runtime boundary.
"""

from .version import __version__

from .composition import (
    CaseComposition,
    ConceptDefinition,
    OperatingMode,
    OperatingModelDefinition,
    SiteDefinition,
)
from .engine import DeterministicEngine
from .books import (
    EntityBooksEngine,
    EntityBookSummary,
    RentComparisonEngine,
    RentComparisonResult,
    SiteBooksResult,
)
from .joint_product import (
    BoundedJointProductScenario,
    JointProductEngine,
    JointProductResult,
    MarketGapGateEngine,
    MarketGapGateResult,
)
from .models import AggregateScenario, ScenarioResult
from .assets import (
    AssetDefinition,
    AssetRevenueLayer,
    CapexPortfolioEngine,
    CapexPortfolioResult,
    CaseRevenueStream,
    EntityCapexSummary,
)
from .costs import CostCalculationType, CostObject, FixedCostScenario, FixedCostSet
from .contracts import (
    ContractScenario,
    ContractSet,
    ContractStructureKind,
    RentComparisonScenario,
)
from .demand import DemandSource, DemandSurface, FunnelStep
from .economics import EconomicScenarioPoint, EconomicScenarioSet
from .experiments import ExperimentLearningItem, StructuralExperiment, StructuralExperimentSet
from .funding import FundingRequirement, FundingRisk, FundingSource, FundingStack
from .gates import DecisionGate, DecisionPlan, ExperimentMeasurement, FailureGate, StakeholderQuestion
from .product import (
    CoreIncomeMode,
    DirectCostComponent,
    ProductCatalog,
    ProductItem,
    ProductLineResult,
    ProductMixEngine,
    ProductMixResult,
    ProductVolumeScenario,
)
from .registry import CaseKind, CaseRegistry, CaseRegistryEntry, CaseStatus
from .revenue import (
    RevenueAdapterEngine,
    RevenueAdapterSet,
    RevenueEntitySummary,
    RevenueStreamResult,
    validate_adapter_owners,
)
from .runtime import CaseNotRunnableError, CaseRunner
from .slots import (
    OperatingSchedule,
    OperatingSlot,
    OperatingSlotEngine,
    SitePortfolioResult,
    Weekday,
)
from .staffing import CapacityPoint, StaffingLayer, StaffingPlan

__all__ = [
    "__version__",
    "AggregateScenario",
    "ScenarioResult",
    "AssetDefinition",
    "AssetRevenueLayer",
    "CapexPortfolioEngine",
    "CapexPortfolioResult",
    "CaseRevenueStream",
    "EntityCapexSummary",
    "CostCalculationType",
    "CostObject",
    "FixedCostScenario",
    "FixedCostSet",
    "ContractScenario",
    "ContractSet",
    "ContractStructureKind",
    "DemandSource",
    "DemandSurface",
    "FunnelStep",
    "EconomicScenarioPoint",
    "EconomicScenarioSet",
    "ExperimentLearningItem",
    "StructuralExperiment",
    "StructuralExperimentSet",
    "FundingRequirement",
    "FundingRisk",
    "FundingSource",
    "FundingStack",
    "DecisionGate",
    "DecisionPlan",
    "ExperimentMeasurement",
    "FailureGate",
    "StakeholderQuestion",
    "CoreIncomeMode",
    "DirectCostComponent",
    "ProductCatalog",
    "ProductItem",
    "ProductLineResult",
    "ProductMixEngine",
    "ProductMixResult",
    "ProductVolumeScenario",
    "CapacityPoint",
    "StaffingLayer",
    "StaffingPlan",
    "DeterministicEngine",
    "EntityBooksEngine",
    "EntityBookSummary",
    "SiteBooksResult",
    "RentComparisonEngine",
    "RentComparisonResult",
    "RentComparisonScenario",
    "RevenueAdapterEngine",
    "RevenueAdapterSet",
    "RevenueEntitySummary",
    "RevenueStreamResult",
    "validate_adapter_owners",
    "BoundedJointProductScenario",
    "JointProductEngine",
    "JointProductResult",
    "MarketGapGateEngine",
    "MarketGapGateResult",
    "OperatingSchedule",
    "OperatingSlot",
    "OperatingSlotEngine",
    "SitePortfolioResult",
    "Weekday",
    "SiteDefinition",
    "ConceptDefinition",
    "OperatingModelDefinition",
    "OperatingMode",
    "CaseComposition",
    "CaseKind",
    "CaseStatus",
    "CaseRegistry",
    "CaseRegistryEntry",
    "CaseRunner",
    "CaseNotRunnableError",
]
