from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EvidenceState


class CostCalculationType(StrEnum):
    FIXED_MONTHLY = "fixed_monthly"
    PER_UNIT = "per_unit"
    STEPPED_MONTHLY = "stepped_monthly"
    HYBRID = "hybrid"
    CAPEX = "capex"


class CostObject(BaseModel):
    """An attributable cost input with an optional volume activation threshold."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    category: str = Field(min_length=1)
    calculation_type: CostCalculationType = CostCalculationType.FIXED_MONTHLY
    owner_entity_id: str = Field(min_length=1)
    payer_entity_id: str = Field(min_length=1)
    recipient_entity_id: str | None = None
    active: bool = False
    monthly_amount: Decimal | None = Field(default=None, ge=0)
    unit_amount: Decimal | None = Field(default=None, ge=0)
    units_per_day_override: Decimal | None = Field(default=None, ge=0)
    days_per_month: Decimal = Field(default=Decimal("30.4166667"), gt=0)
    activation_threshold_visits_per_day: Decimal | None = Field(default=None, ge=0)
    evidence_state: EvidenceState = EvidenceState.BLOCKED
    source: str | None = None
    note: str | None = None
    contract_ref: str | None = None
    asset_ref: str | None = None
    activation_dependency: str | None = None
    capacity_dependency: str | None = None
    legacy_residual: bool = False

    @model_validator(mode="after")
    def stepped_cost_has_threshold(self) -> "CostObject":
        if (
            self.calculation_type == CostCalculationType.STEPPED_MONTHLY
            and self.activation_threshold_visits_per_day is None
        ):
            raise ValueError("stepped_monthly costs require an activation threshold")
        return self

    def effective_monthly_amount(self, visits_per_day: Decimal) -> Decimal | None:
        if not self.active:
            return Decimal("0")
        if self.calculation_type == CostCalculationType.FIXED_MONTHLY:
            return self.monthly_amount
        activity = (
            self.units_per_day_override
            if self.units_per_day_override is not None
            else visits_per_day
        )
        variable_amount = (
            None
            if self.unit_amount is None
            else self.unit_amount * activity * self.days_per_month
        )
        if self.calculation_type == CostCalculationType.PER_UNIT:
            return variable_amount
        if self.calculation_type == CostCalculationType.HYBRID:
            if self.monthly_amount is None or variable_amount is None:
                return None
            return self.monthly_amount + variable_amount
        if self.calculation_type == CostCalculationType.STEPPED_MONTHLY:
            assert self.activation_threshold_visits_per_day is not None
            if visits_per_day < self.activation_threshold_visits_per_day:
                return Decimal("0")
            return self.monthly_amount
        return None


class FixedCostScenario(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    monthly_amount: Decimal = Field(ge=0)
    currency: str = Field(default="SEK", min_length=1, max_length=12)
    status: str = Field(min_length=1)
    note: str | None = None


class FixedCostSet(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    fixed_cost_set_id: str = Field(min_length=1)
    selected_scenario_id: str = Field(min_length=1)
    scenarios: list[FixedCostScenario] = Field(min_length=1)
    cost_objects: list[CostObject] = Field(default_factory=list)

    @model_validator(mode="after")
    def scenario_ids_are_valid(self) -> "FixedCostSet":
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario_id values must be unique")
        if self.selected_scenario_id not in ids:
            raise ValueError("selected_scenario_id must reference an existing scenario")
        object_ids = [cost.cost_id for cost in self.cost_objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("cost_id values must be unique")
        if sum(cost.legacy_residual for cost in self.cost_objects) > 1:
            raise ValueError("only one cost object can be the legacy residual")
        return self

    @property
    def selected_scenario(self) -> FixedCostScenario:
        return next(
            scenario
            for scenario in self.scenarios
            if scenario.scenario_id == self.selected_scenario_id
        )

    @property
    def active_fixed_monthly_total(self) -> Decimal:
        return sum(
            (
                cost.monthly_amount
                for cost in self.cost_objects
                if cost.active
                and cost.calculation_type == CostCalculationType.FIXED_MONTHLY
                and cost.monthly_amount is not None
            ),
            Decimal("0"),
        )

    def active_fixed_monthly_total_for_payer(self, payer_entity_id: str) -> Decimal:
        return sum(
            (
                cost.monthly_amount
                for cost in self.cost_objects
                if cost.active
                and cost.payer_entity_id == payer_entity_id
                and cost.calculation_type == CostCalculationType.FIXED_MONTHLY
                and cost.monthly_amount is not None
            ),
            Decimal("0"),
        )

    def active_monthly_total(
        self,
        visits_per_day: Decimal,
        payer_entity_id: str | None = None,
    ) -> Decimal:
        return sum(
            (
                amount
                for cost in self.cost_objects
                if (payer_entity_id is None or cost.payer_entity_id == payer_entity_id)
                and (amount := cost.effective_monthly_amount(visits_per_day)) is not None
            ),
            Decimal("0"),
        )

    def unresolved_active_cost_ids_at(self, visits_per_day: Decimal) -> list[str]:
        return [
            cost.cost_id
            for cost in self.cost_objects
            if cost.active and cost.effective_monthly_amount(visits_per_day) is None
        ]

    @property
    def unresolved_active_cost_ids(self) -> list[str]:
        return [
            cost.cost_id
            for cost in self.cost_objects
            if cost.active
            and (
                cost.effective_monthly_amount(Decimal("0")) is None
                or (
                    cost.calculation_type
                    in {CostCalculationType.PER_UNIT, CostCalculationType.HYBRID}
                    and cost.unit_amount is None
                )
            )
        ]

    def sync_selected_scenario_total(
        self,
        payer_entity_id: str | None = None,
        visits_per_day: Decimal | None = None,
    ) -> Decimal:
        if visits_per_day is None:
            total = (
                self.active_fixed_monthly_total
                if payer_entity_id is None
                else self.active_fixed_monthly_total_for_payer(payer_entity_id)
            )
        else:
            total = self.active_monthly_total(visits_per_day, payer_entity_id)
        self.selected_scenario.monthly_amount = total
        return total

    def set_active_fixed_monthly_total(
        self,
        target: Decimal,
        visits_per_day: Decimal | None = None,
    ) -> None:
        residual = next(
            (
                cost
                for cost in self.cost_objects
                if cost.active and cost.legacy_residual
            ),
            None,
        )
        if residual is None:
            raise ValueError("A legacy residual cost is required to set the aggregate target")
        other_total = sum(
            (
                cost.monthly_amount
                for cost in self.cost_objects
                if cost.active
                and cost.cost_id != residual.cost_id
                and cost.payer_entity_id == residual.payer_entity_id
                and cost.calculation_type == CostCalculationType.FIXED_MONTHLY
                and cost.monthly_amount is not None
            ),
            Decimal("0"),
        )
        if target < other_total:
            raise ValueError("Target fixed cost is below the other active cost objects")
        residual.monthly_amount = target - other_total
        self.sync_selected_scenario_total(residual.payer_entity_id)
