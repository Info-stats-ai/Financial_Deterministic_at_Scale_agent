"""Caller-facing replay result contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReplayStatus(StrEnum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    RECOVERABLE_EXHAUSTED = "recoverable_exhausted"
    HARD_FAILURE = "hard_failure"
    INTERVENTION_REQUIRED = "intervention_required"


class FailureDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str | None
    step_index: int | None = Field(default=None, ge=0)
    code: str
    expected: str
    observed: str
    evidence_paths: list[str] = Field(default_factory=list)


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    capability_id: str
    capability_version: str
    status: ReplayStatus
    outputs: dict[str, Any] | None = None
    outcome_code: str | None = None
    outcome_message: str | None = None
    failure: FailureDetail | None = None
    completed_steps: int = Field(default=0, ge=0)
    duration_ms: int = Field(ge=0)

    @property
    def is_success(self) -> bool:
        return self.status == ReplayStatus.SUCCESS
