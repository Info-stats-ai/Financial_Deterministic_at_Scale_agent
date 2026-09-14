"""Internal discovery records; deliberately separate from the saved artifact."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from interface_ai.surface.protocol import ElementFingerprint


class DiscoveryStatus(StrEnum):
    SUCCESS = "success"
    STUCK = "stuck"
    POLICY_BLOCKED = "policy_blocked"
    INTERVENTION_REQUIRED = "intervention_required"
    MAX_STEPS = "max_steps"
    TIMEOUT = "timeout"
    MODEL_ERROR = "model_error"


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    input: dict[str, Any]
    toolset_name: str | None = None


class ModelTurn(BaseModel):
    text: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw_content: list[dict[str, Any]]
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class RecordedAction(BaseModel):
    sequence: int
    tool_name: str
    tool_input: dict[str, Any]
    url_before: str
    url_after: str
    success: bool
    result: str
    state_before: str
    state_after: str
    target: ElementFingerprint | None = None


class CompletionPayload(BaseModel):
    summary: str
    final_checkpoint_text: str
    outputs: dict[str, str] = Field(
        default_factory=dict,
        description="Output name to exact value currently visible in the UI",
    )
