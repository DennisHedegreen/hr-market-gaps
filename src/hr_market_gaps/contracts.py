from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractStructureKind(StrEnum):
    FIXED_PAYMENT = "fixed_payment"
    TURNOVER_SHARE = "turnover_share"
    INVESTMENT_PARTNERSHIP = "investment_partnership"
    HYBRID = "hybrid"


class ContractScenario(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: ContractStructureKind
    parties: list[str] = Field(min_length=2)
    payer_entity_id: str | None = None
    recipient_entity_id: str | None = None
    fixed_payment_monthly: Decimal | None = Field(default=None, ge=0)
    revenue_share_rate: Decimal | None = Field(default=None, ge=0, le=1)
    minimum_guarantee_monthly: Decimal | None = Field(default=None, ge=0)
    one_time_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="SEK", min_length=1, max_length=12)
    status: str = Field(min_length=1)
    note: str | None = None


class RentComparisonScenario(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: Literal["fixed", "stepped", "turnover_share", "hybrid", "service_credit"] = "fixed"
    payer_entity_id: str = Field(min_length=1)
    recipient_entity_id: str = Field(min_length=1)
    base_rent_monthly: Decimal = Field(ge=0)
    threshold_visits_per_day: Decimal | None = Field(default=None, ge=0)
    stepped_rent_monthly: Decimal | None = Field(default=None, ge=0)
    revenue_share_rate: Decimal | None = Field(default=None, ge=0, le=1)
    property_service_credit_monthly: Decimal | None = Field(default=None, ge=0)
    status: str = Field(default="Comparison only", min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def stepped_fields_are_complete(self) -> "RentComparisonScenario":
        if self.kind == "stepped":
            if self.threshold_visits_per_day is None or self.stepped_rent_monthly is None:
                raise ValueError("stepped rent requires threshold and stepped amount")
            if self.stepped_rent_monthly < self.base_rent_monthly:
                raise ValueError("stepped rent cannot be below base rent")
        elif self.threshold_visits_per_day is not None or self.stepped_rent_monthly is not None:
            raise ValueError("only stepped rent can carry stepped fields")
        if self.kind in {"turnover_share", "hybrid"}:
            if self.revenue_share_rate is None:
                raise ValueError("turnover-share rent requires a revenue share rate")
        elif self.revenue_share_rate is not None:
            raise ValueError(
                "fixed, stepped and service-credit rent cannot carry a revenue share rate"
            )
        if (
            self.kind != "service_credit"
            and self.property_service_credit_monthly is not None
        ):
            raise ValueError("only service-credit rent can carry a property service credit")
        return self

    def effective_rent(
        self,
        visits_per_day: Decimal,
        monthly_core_sales: Decimal | None = None,
    ) -> Decimal:
        if (
            self.kind == "stepped"
            and self.threshold_visits_per_day is not None
            and self.stepped_rent_monthly is not None
            and visits_per_day >= self.threshold_visits_per_day
        ):
            return self.stepped_rent_monthly
        if self.kind in {"turnover_share", "hybrid"}:
            if monthly_core_sales is None or self.revenue_share_rate is None:
                raise ValueError("turnover-share rent requires monthly core sales")
            share = monthly_core_sales * self.revenue_share_rate
            if self.kind == "turnover_share":
                return max(self.base_rent_monthly, share)
            return self.base_rent_monthly + share
        return self.base_rent_monthly


class ContractSet(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_set_id: str = Field(min_length=1)
    scenarios: list[ContractScenario] = Field(default_factory=list)
    rent_comparisons: list[RentComparisonScenario] = Field(default_factory=list)

    @model_validator(mode="after")
    def contract_ids_are_unique(self) -> "ContractSet":
        ids = [scenario.contract_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("contract_id values must be unique")
        comparison_ids = [scenario.scenario_id for scenario in self.rent_comparisons]
        if len(comparison_ids) != len(set(comparison_ids)):
            raise ValueError("rent comparison scenario_id values must be unique")
        return self
