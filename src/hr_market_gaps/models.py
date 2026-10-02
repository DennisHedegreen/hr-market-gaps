from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceState(StrEnum):
    FACT = "FACT"
    OBSERVED = "OBSERVED"
    HYPOTHESIS = "HYPOTHESIS"
    DESIGN_TARGET = "DESIGN_TARGET"
    MODEL_POLICY = "MODEL_POLICY"
    LEGACY_HYPOTHESIS = "LEGACY_HYPOTHESIS"
    FORMULA = "FORMULA"
    BLOCKED = "BLOCKED"


class GateState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Visibility(StrEnum):
    PUBLIC = "PUBLIC"
    AGGREGATED = "AGGREGATED"
    DELAYED = "DELAYED"
    PRIVATE = "PRIVATE"
    CONTRACT_CONFIDENTIAL = "CONTRACT-CONFIDENTIAL"
    PERMISSIONED = "PERMISSIONED"


class AggregateScenario(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    """Bridge schema for the first runnable control surface.

    The full v0.1 parity port should extend this into product/mix/staffing/CAPEX
    domain models while preserving a small generic scenario API for fast tests.
    """

    case_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    currency: str = Field(default="SEK", min_length=1, max_length=12)
    core_entity_id: str = Field(default="operator", min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    visits_per_day: Decimal = Field(ge=0)
    days_per_month: Decimal = Field(default=Decimal("30.4166667"), gt=0)
    revenue_per_visit: Decimal = Field(ge=0)
    db1_per_visit: Decimal = Field(ge=0)
    fixed_overhead_monthly: Decimal = Field(ge=0)
    opening_hours: Decimal = Field(gt=0, le=24)
    service_minutes_per_order: Decimal = Field(ge=0)
    background_active_hours_per_day: Decimal = Field(ge=0)
    peak_multiplier: Decimal = Field(gt=0)
    comfort_utilisation: Decimal = Field(gt=0, le=1)
    activity_label: str = Field(default="purchase visits", min_length=1)
    activity_unit: str = Field(default="purchase visits/day", min_length=1)

    @model_validator(mode="after")
    def entity_registry_is_valid(self) -> "AggregateScenario":
        if not self.entity_ids:
            self.entity_ids = [self.core_entity_id]
        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("entity_ids must be unique")
        if any(not entity_id.strip() for entity_id in self.entity_ids):
            raise ValueError("entity_ids cannot contain blank values")
        if self.core_entity_id not in self.entity_ids:
            raise ValueError("core_entity_id must be present in entity_ids")
        if self.db1_per_visit > self.revenue_per_visit:
            raise ValueError("db1_per_visit cannot exceed revenue_per_visit")
        return self


class ScenarioResult(BaseModel):
    monthly_visits: Decimal
    monthly_sales: Decimal
    monthly_db1: Decimal
    core_cash_result: Decimal
    break_even_visits_per_day: Decimal | None
    average_orders_per_hour: Decimal
    active_labour_hours_per_day: Decimal
    average_idle_minutes_per_hour: Decimal
    peak_comfort_workers: int
    breakdowns: dict[str, "CalculationBreakdown"] = Field(default_factory=dict)


class CalculationTerm(BaseModel):
    label: str = Field(min_length=1)
    value: Decimal
    unit: str = Field(default="", max_length=32)


class CalculationBreakdown(BaseModel):
    label: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    terms: list[CalculationTerm] = Field(default_factory=list)
    result: Decimal | None
    unit: str = Field(default="", max_length=32)
