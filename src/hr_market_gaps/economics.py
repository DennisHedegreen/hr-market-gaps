from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EconomicScenarioPoint(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    visits_per_day: Decimal = Field(ge=0)
    monthly_gross_sales: Decimal = Field(ge=0)
    monthly_contribution: Decimal
    monthly_core_result: Decimal
    currency: str = Field(default="SEK", min_length=1, max_length=12)
    status: str = Field(min_length=1)
    note: str | None = None


class EconomicScenarioSet(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_set_id: str = Field(min_length=1)
    selected_scenario_id: str | None = None
    simulation_uncertainty_scenario_ids: list[str] = Field(default_factory=list)
    scenarios: list[EconomicScenarioPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_valid(self) -> "EconomicScenarioSet":
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("economic scenario_id values must be unique")
        known = set(ids)
        if self.selected_scenario_id is not None and self.selected_scenario_id not in known:
            raise ValueError("selected_scenario_id must reference a known economic scenario")
        unknown_simulation_ids = [
            scenario_id
            for scenario_id in self.simulation_uncertainty_scenario_ids
            if scenario_id not in known
        ]
        if unknown_simulation_ids:
            raise ValueError(
                "simulation_uncertainty_scenario_ids must reference known economic scenarios: "
                + ", ".join(unknown_simulation_ids)
            )
        return self
