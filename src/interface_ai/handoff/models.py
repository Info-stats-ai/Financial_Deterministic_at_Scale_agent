"""Human-intervention contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class InterventionReason(StrEnum):
    DISCOVERY_STUCK = "discovery_stuck"
    REPLAY_UNRECOVERABLE = "replay_unrecoverable"
    RISKY_ACTION = "risky_action"
    SESSION_EXPIRED = "session_expired"


class InterventionRequest(BaseModel):
    intervention_id: str
    run_id: str
    reason: InterventionReason
    summary: str
    goal_or_capability: str
    current_step: str | None
    current_url: str
    screenshot_path: str
    expected_state: str | None = None
    observed_state: str | None = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HumanAction(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str
    url: str
    target: dict[str, Any] = Field(default_factory=dict)
    value_was_entered: bool = False


class HandoffResolution(BaseModel):
    intervention_id: str
    resumed: bool
    human_actions: list[HumanAction] = Field(default_factory=list)
    reason: str | None = None
