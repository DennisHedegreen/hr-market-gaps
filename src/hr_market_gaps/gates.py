from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import GateState


class FailureGate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    gate_id: str
    label: str
    state: GateState
    severity: str
    why: str
    evidence_needed: str | None = None


class ExperimentMeasurement(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    measurement_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    before_experiment_basis: str = Field(min_length=1)
    during_experiment_evidence: str = Field(min_length=1)
    status: str = Field(min_length=1)
    note: str | None = None


class DecisionGate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    gate_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    state: GateState
    severity: str = Field(min_length=1)
    why: str = Field(min_length=1)
    evidence_needed: str | None = None
    owner_entity_id: str | None = None


class StakeholderQuestion(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question_id: str = Field(min_length=1)
    stakeholder_entity_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str = Field(min_length=1)
    note: str | None = None


class DecisionPlan(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision_plan_id: str = Field(min_length=1)
    measurements: list[ExperimentMeasurement] = Field(default_factory=list)
    gates: list[DecisionGate] = Field(default_factory=list)
    stakeholder_questions: list[StakeholderQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_unique(self) -> "DecisionPlan":
        measurement_ids = [item.measurement_id for item in self.measurements]
        if len(measurement_ids) != len(set(measurement_ids)):
            raise ValueError("measurement_id values must be unique")
        gate_ids = [item.gate_id for item in self.gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("decision gate_id values must be unique")
        question_ids = [item.question_id for item in self.stakeholder_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question_id values must be unique")
        return self


# Codex: replace snapshot loading with evaluated gates as workbook modules are ported.
