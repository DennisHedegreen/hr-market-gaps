from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import AggregateScenario, EvidenceState

ZERO = Decimal("0")


class CoreIncomeMode(StrEnum):
    LEGACY_BRIDGE = "legacy_bridge"
    PRODUCT_MIX = "product_mix"


class DirectCostComponent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1)
    low: Decimal | None = Field(default=None, ge=0)
    mid: Decimal | None = Field(default=None, ge=0)
    high: Decimal | None = Field(default=None, ge=0)
    unit: str = Field(default="currency", min_length=1)
    status: str = Field(default="Estimated", min_length=1)


class ProductItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    active: bool = True
    selling_price_gross: Decimal | None = Field(default=None, ge=0)
    direct_cost_gross: Decimal | None = Field(default=None, ge=0)
    waste_rate: Decimal = Field(default=ZERO, ge=0, le=1)
    contribution_per_unit: Decimal | None = None
    contribution_margin: Decimal | None = Field(default=None, ge=0, le=1)
    status: str = Field(default="Estimated", min_length=1)
    price_evidence_state: EvidenceState = EvidenceState.HYPOTHESIS
    direct_cost_evidence_state: EvidenceState = EvidenceState.HYPOTHESIS
    volume_evidence_state: EvidenceState = EvidenceState.HYPOTHESIS
    components: list[DirectCostComponent] = Field(default_factory=list)
    notes: str | None = None

    @property
    def derived_direct_cost_per_unit(self) -> Decimal | None:
        if self.direct_cost_gross is None:
            return None
        return self.direct_cost_gross * (Decimal("1") + self.waste_rate)

    @property
    def derived_contribution_per_unit(self) -> Decimal | None:
        direct_cost = self.derived_direct_cost_per_unit
        if self.selling_price_gross is None or direct_cost is None:
            return None
        return self.selling_price_gross - direct_cost


class ProductVolumeScenario(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str = Field(default="Hypothesis", min_length=1)
    operating_days_per_month: Decimal = Field(default=Decimal("30.4166667"), gt=0, le=31)
    quantities_per_day: dict[str, Decimal] = Field(default_factory=dict)
    note: str | None = None

    @model_validator(mode="after")
    def quantities_are_non_negative(self) -> "ProductVolumeScenario":
        invalid = sorted(
            product_id
            for product_id, quantity in self.quantities_per_day.items()
            if quantity < ZERO
        )
        if invalid:
            raise ValueError(
                "product quantities cannot be negative: " + ", ".join(invalid)
            )
        return self


class ProductCatalog(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    catalog_id: str = Field(min_length=1)
    currency: str = Field(default="SEK", min_length=1, max_length=12)
    adapter_id: str = Field(default="core_product_mix", min_length=1)
    entity_id: str = Field(default="food_operator", min_length=1)
    income_mode: CoreIncomeMode = CoreIncomeMode.LEGACY_BRIDGE
    products: list[ProductItem] = Field(min_length=1)
    volume_scenarios: list[ProductVolumeScenario] = Field(default_factory=list)
    selected_volume_scenario_id: str | None = None

    @model_validator(mode="after")
    def product_structure_is_valid(self) -> "ProductCatalog":
        ids = [product.product_id for product in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("product_id values must be unique")
        scenario_ids = [scenario.scenario_id for scenario in self.volume_scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("product volume scenario_id values must be unique")
        known = set(ids)
        for scenario in self.volume_scenarios:
            unknown = set(scenario.quantities_per_day) - known
            if unknown:
                raise ValueError(
                    f"product scenario {scenario.scenario_id} references unknown products: "
                    + ", ".join(sorted(unknown))
                )
        if self.income_mode == CoreIncomeMode.PRODUCT_MIX:
            if not self.volume_scenarios:
                raise ValueError("product_mix mode requires at least one volume scenario")
            if self.selected_volume_scenario_id not in set(scenario_ids):
                raise ValueError(
                    "product_mix mode requires a selected volume scenario"
                )
        return self

    @property
    def selected_volume_scenario(self) -> ProductVolumeScenario | None:
        if self.selected_volume_scenario_id is None:
            return None
        return next(
            (
                scenario
                for scenario in self.volume_scenarios
                if scenario.scenario_id == self.selected_volume_scenario_id
            ),
            None,
        )


class ProductLineResult(BaseModel):
    product_id: str
    label: str
    active: bool
    units_per_day: Decimal = Field(ge=0)
    gross_revenue_monthly: Decimal | None = None
    direct_cost_monthly: Decimal | None = None
    contribution_monthly: Decimal | None = None
    contribution_per_unit: Decimal | None = None
    unresolved_fields: list[str] = Field(default_factory=list)


class ProductMixResult(BaseModel):
    adapter_id: str
    entity_id: str
    scenario_id: str
    scenario_label: str
    evidence_status: str
    operating_days_per_month: Decimal
    total_units_per_day: Decimal = Field(ge=0)
    gross_revenue_monthly: Decimal
    direct_cost_monthly: Decimal
    contribution_monthly: Decimal
    effective_revenue_per_unit: Decimal | None = None
    effective_contribution_per_unit: Decimal | None = None
    unresolved_fields: list[str] = Field(default_factory=list)
    lines: list[ProductLineResult] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unresolved_fields


class ProductMixEngine:
    """Calculate one explicit product-volume scenario without upgrading evidence."""

    def run(self, catalog: ProductCatalog) -> ProductMixResult:
        if catalog.income_mode != CoreIncomeMode.PRODUCT_MIX:
            raise ValueError("product mix engine requires product_mix income mode")
        scenario = catalog.selected_volume_scenario
        if scenario is None:
            raise ValueError("selected product volume scenario is missing")

        gross = ZERO
        direct_cost = ZERO
        total_units = ZERO
        unresolved: list[str] = []
        lines: list[ProductLineResult] = []

        for product in catalog.products:
            units = scenario.quantities_per_day.get(product.product_id, ZERO)
            if product.active:
                total_units += units
            line_unresolved: list[str] = []
            if product.active and units > ZERO:
                if product.selling_price_gross is None:
                    line_unresolved.append("selling_price_gross")
                if product.direct_cost_gross is None:
                    line_unresolved.append("direct_cost_gross")

            if not product.active or units == ZERO:
                line_gross = ZERO
                line_cost = ZERO
                line_contribution = ZERO
            elif line_unresolved:
                line_gross = None
                line_cost = None
                line_contribution = None
            else:
                assert product.selling_price_gross is not None
                effective_cost = product.derived_direct_cost_per_unit
                assert effective_cost is not None
                monthly_units = units * scenario.operating_days_per_month
                line_gross = monthly_units * product.selling_price_gross
                line_cost = monthly_units * effective_cost
                line_contribution = line_gross - line_cost
                gross += line_gross
                direct_cost += line_cost

            unresolved.extend(
                f"{product.product_id}.{field}" for field in line_unresolved
            )
            lines.append(
                ProductLineResult(
                    product_id=product.product_id,
                    label=product.label,
                    active=product.active,
                    units_per_day=units,
                    gross_revenue_monthly=line_gross,
                    direct_cost_monthly=line_cost,
                    contribution_monthly=line_contribution,
                    contribution_per_unit=product.derived_contribution_per_unit,
                    unresolved_fields=line_unresolved,
                )
            )

        contribution = gross - direct_cost
        return ProductMixResult(
            adapter_id=catalog.adapter_id,
            entity_id=catalog.entity_id,
            scenario_id=scenario.scenario_id,
            scenario_label=scenario.label,
            evidence_status=scenario.status,
            operating_days_per_month=scenario.operating_days_per_month,
            total_units_per_day=total_units,
            gross_revenue_monthly=gross,
            direct_cost_monthly=direct_cost,
            contribution_monthly=contribution,
            effective_revenue_per_unit=(
                gross / (total_units * scenario.operating_days_per_month)
                if total_units > ZERO
                else None
            ),
            effective_contribution_per_unit=(
                contribution / (total_units * scenario.operating_days_per_month)
                if total_units > ZERO
                else None
            ),
            unresolved_fields=unresolved,
            lines=lines,
        )

    def scenario_for_mix(
        self, base: AggregateScenario, catalog: ProductCatalog
    ) -> tuple[AggregateScenario, ProductMixResult]:
        result = self.run(catalog)
        if not result.complete:
            raise ValueError(
                "product mix has unresolved fields: "
                + ", ".join(result.unresolved_fields)
            )
        return (
            base.model_copy(
                update={
                    "visits_per_day": result.total_units_per_day,
                    "days_per_month": result.operating_days_per_month,
                    "revenue_per_visit": result.effective_revenue_per_unit or ZERO,
                    "db1_per_visit": result.effective_contribution_per_unit or ZERO,
                    "activity_label": "product units",
                    "activity_unit": "product units/day",
                }
            ),
            result,
        )
