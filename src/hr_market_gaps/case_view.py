from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .case_package_v2 import CasePackageV2
from .engine import DeterministicEngine
from .joint_product import JointProductEngine, MarketGapGateEngine
from .models import CalculationBreakdown, CalculationTerm, GateState


class CaseViewMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: Decimal | None
    unit: str = ""
    state: str = "MODELED"
    breakdown: CalculationBreakdown


class CaseViewGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    state: GateState
    note: str = Field(min_length=1)


class CaseViewArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    href: str = Field(min_length=1)
    kind: str = Field(min_length=1)


class CaseViewModel(BaseModel):
    """Client-facing case reading with calculations supplied by Python."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    maturity: str | None = None
    visibility: str = Field(min_length=1)
    summary: str | None = None
    modules: list[str] = Field(default_factory=list)
    metrics: list[CaseViewMetric] = Field(default_factory=list)
    gates: list[CaseViewGate] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    artifacts: list[CaseViewArtifact] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


MODULE_LABELS = {
    "aggregate_scenario": "Economics",
    "joint_product_scenario": "Joint-product economics",
    "network_market_design": "Network architecture",
    "public_record": "Public record",
    "site": "Site",
    "concept": "Concept",
    "operating_model": "Operating model",
    "composition": "Case structure",
    "demand_surface": "Demand",
    "product_catalog": "Products",
    "fixed_costs": "Fixed costs",
    "economic_scenarios": "Scenarios",
    "assets_revenue": "Assets",
    "revenue_adapters": "Revenue streams",
    "funding": "Funding",
    "contracts": "Contracts",
    "staffing": "Staffing",
    "decision_plan": "Decision gates",
    "structural_experiments": "Experiments",
}


def _aggregate_metrics(package: CasePackageV2) -> list[CaseViewMetric]:
    scenario = package.modules.aggregate_scenario
    if scenario is None:
        return []
    result = DeterministicEngine().run(scenario)
    values = {
        "monthly_sales": result.monthly_sales,
        "monthly_db1": result.monthly_db1,
        "core_cash_result": result.core_cash_result,
        "break_even_visits_per_day": result.break_even_visits_per_day,
    }
    return [
        CaseViewMetric(
            metric_id=metric_id,
            label=result.breakdowns[metric_id].label,
            value=value,
            unit=result.breakdowns[metric_id].unit,
            breakdown=result.breakdowns[metric_id],
        )
        for metric_id, value in values.items()
    ]


def _joint_product_metrics(package: CasePackageV2) -> list[CaseViewMetric]:
    scenario = package.modules.joint_product_scenario
    if scenario is None:
        return []
    result = JointProductEngine().run(scenario)
    currency = scenario.currency
    breakdowns = {
        "weekly_sales": CalculationBreakdown(
            label="Weekly planned sales",
            formula="planned sales/open day × opening days/week",
            terms=[
                CalculationTerm(
                    label="Planned sales/open day",
                    value=scenario.planned_sales_per_open_day,
                    unit="sales/day",
                ),
                CalculationTerm(
                    label="Opening days/week",
                    value=scenario.opening_days_per_week,
                    unit="days/week",
                ),
            ],
            result=result.weekly_sales,
            unit="sales/week",
        ),
        "gross_menu_revenue_weekly": CalculationBreakdown(
            label="Weekly gross menu revenue",
            formula="weekly sales × gross price/sale",
            terms=[
                CalculationTerm(
                    label="Weekly sales",
                    value=result.weekly_sales,
                    unit="sales/week",
                ),
                CalculationTerm(
                    label="Gross price/sale",
                    value=scenario.sale_price_gross,
                    unit=currency,
                ),
            ],
            result=result.gross_menu_revenue_weekly,
            unit=currency,
        ),
        "economic_surplus_weekly": CalculationBreakdown(
            label="Weekly modeled economic surplus",
            formula="net menu revenue + secondary contribution - modeled economic cost",
            terms=[
                CalculationTerm(
                    label="Net menu revenue",
                    value=result.net_menu_revenue_weekly,
                    unit=currency,
                ),
                CalculationTerm(
                    label="Secondary contribution",
                    value=result.secondary_contribution_weekly,
                    unit=currency,
                ),
                CalculationTerm(
                    label="Modeled economic cost",
                    value=result.total_economic_cost_weekly,
                    unit=currency,
                ),
            ],
            result=result.economic_surplus_weekly,
            unit=currency,
        ),
        "required_secondary_contribution_per_unit": CalculationBreakdown(
            label="Required secondary contribution",
            formula="uncovered modeled cost ÷ secondary output",
            terms=[
                CalculationTerm(
                    label="Modeled economic cost",
                    value=result.total_economic_cost_weekly,
                    unit=currency,
                ),
                CalculationTerm(
                    label="Net menu revenue",
                    value=result.net_menu_revenue_weekly,
                    unit=currency,
                ),
                CalculationTerm(
                    label="Secondary output",
                    value=result.secondary_output_weekly,
                    unit=scenario.secondary_output_unit_label,
                ),
            ],
            result=result.required_secondary_contribution_per_unit,
            unit=f"{currency}/{scenario.secondary_output_unit_label}",
        ),
    }
    values = {
        "weekly_sales": result.weekly_sales,
        "gross_menu_revenue_weekly": result.gross_menu_revenue_weekly,
        "economic_surplus_weekly": result.economic_surplus_weekly,
        "required_secondary_contribution_per_unit": (
            result.required_secondary_contribution_per_unit
        ),
    }
    return [
        CaseViewMetric(
            metric_id=metric_id,
            label=breakdowns[metric_id].label,
            value=value,
            unit=breakdowns[metric_id].unit,
            state="MODELED_NOT_VALIDATED",
            breakdown=breakdowns[metric_id],
        )
        for metric_id, value in values.items()
    ]


def build_case_view(package: CasePackageV2) -> CaseViewModel:
    present_modules = [
        module_id
        for module_id in MODULE_LABELS
        if getattr(package.modules, module_id) is not None
    ]
    public_record = package.modules.public_record
    metrics = _aggregate_metrics(package) + _joint_product_metrics(package)
    gates: list[CaseViewGate] = []
    notices: list[str] = []

    if package.modules.joint_product_scenario is not None:
        scenario = package.modules.joint_product_scenario
        result = JointProductEngine().run(scenario)
        gates = [
            CaseViewGate(
                gate_id=gate.gate_id,
                label=gate.label,
                state=gate.state,
                note=gate.note,
            )
            for gate in MarketGapGateEngine().evaluate(scenario, result)
        ]

    if package.modules.network_market_design is not None:
        notices.append(
            "Design-only network case: no canonical runnable economics are "
            "available, so the app does not invent aggregate business results."
        )

    if not metrics and package.modules.network_market_design is None:
        notices.append("No supported calculation module is present.")

    return CaseViewModel(
        case_id=package.metadata.case_id,
        title=public_record.title if public_record else package.metadata.label,
        kind=package.metadata.kind.value,
        status=public_record.status if public_record else package.metadata.status,
        maturity=(
            public_record.maturity if public_record else package.metadata.maturity
        ),
        visibility=package.metadata.visibility.value,
        summary=public_record.summary if public_record else package.metadata.description,
        modules=[MODULE_LABELS[module_id] for module_id in present_modules],
        metrics=metrics,
        gates=gates,
        boundaries=public_record.boundaries if public_record else [],
        artifacts=(
            [
                CaseViewArtifact(
                    label=artifact.label,
                    href=artifact.href,
                    kind=artifact.kind,
                )
                for artifact in public_record.artifacts
            ]
            if public_record
            else []
        ),
        notices=notices,
    )

