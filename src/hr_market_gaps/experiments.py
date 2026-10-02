from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExperimentLearningItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    learning_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str = Field(min_length=1)
    note: str | None = None


class StructuralExperiment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    experiment_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    linked_operating_model_id: str | None = None
    status: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    coverage_caption: str | None = None
    learning_items: list[ExperimentLearningItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def learning_ids_are_unique(self) -> "StructuralExperiment":
        ids = [item.learning_id for item in self.learning_items]
        if len(ids) != len(set(ids)):
            raise ValueError("learning_id values must be unique")
        return self


class StructuralExperimentSet(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    experiment_set_id: str = Field(min_length=1)
    experiments: list[StructuralExperiment] = Field(default_factory=list)

    @model_validator(mode="after")
    def experiment_ids_are_unique(self) -> "StructuralExperimentSet":
        ids = [experiment.experiment_id for experiment in self.experiments]
        if len(ids) != len(set(ids)):
            raise ValueError("experiment_id values must be unique")
        return self
