from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CapacityPoint(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    point_id: str = Field(min_length=1)
    visits_per_day: Decimal = Field(ge=0)
    average_idle_minutes_per_hour: Decimal = Field(ge=0)
    peak_comfort_workers: int = Field(ge=0)
    active_labour_hours_per_day: Decimal = Field(ge=0)
    status: str = Field(min_length=1)
    note: str | None = None


class StaffingLayer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    layer_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    safe_activation_visits_per_day: Decimal = Field(ge=0)
    status: str = Field(min_length=1)
    note: str | None = None


class StaffingPlan(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    staffing_plan_id: str = Field(min_length=1)
    capacity_points: list[CapacityPoint] = Field(default_factory=list)
    staffing_layers: list[StaffingLayer] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_unique(self) -> "StaffingPlan":
        capacity_ids = [point.point_id for point in self.capacity_points]
        if len(capacity_ids) != len(set(capacity_ids)):
            raise ValueError("capacity point_id values must be unique")
        layer_ids = [layer.layer_id for layer in self.staffing_layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("staffing layer_id values must be unique")
        return self
