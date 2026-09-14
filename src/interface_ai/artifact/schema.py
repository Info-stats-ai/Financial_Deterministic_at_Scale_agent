"""Typed, versioned contract produced by discovery and consumed by replay."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Forbid silent schema drift at every contract boundary."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class SurfaceKind(StrEnum):
    WEB = "web"
    DESKTOP = "desktop"


class ValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    MONEY = "money"


class RiskClass(StrEnum):
    SAFE = "safe"
    REVERSIBLE = "reversible"
    RISKY = "risky"
    IRREVERSIBLE = "irreversible"


class ActionType(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    WAIT = "wait"
    EXTRACT = "extract"
    DISMISS_DIALOG = "dismiss_dialog"


class LocatorKind(StrEnum):
    ROLE_NAME = "role_name"
    LABEL = "label"
    TEXT = "text"
    CSS = "css"
    XPATH = "xpath"
    COORDINATES = "coordinates"


class CheckpointKind(StrEnum):
    URL_MATCHES = "url_matches"
    TEXT_VISIBLE = "text_visible"
    ELEMENT_VISIBLE = "element_visible"
    ELEMENT_ABSENT = "element_absent"
    VALUE_MATCHES = "value_matches"


class OutcomeClass(StrEnum):
    BUSINESS = "business_outcome"
    RECOVERABLE = "recoverable"
    HARD_FAILURE = "hard_failure"


class RecoveryAction(StrEnum):
    RETRY = "retry"
    WAIT = "wait"
    DISMISS = "dismiss"
    REAUTHENTICATE = "reauthenticate"
    ESCALATE = "escalate"
    STOP = "stop"


class ParameterSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: ValueType
    description: str
    required: bool = True
    default: Any | None = None
    pattern: str | None = None
    examples: list[Any] = Field(default_factory=list)
    sensitive: bool = False

    @model_validator(mode="after")
    def required_parameter_has_no_default(self) -> Self:
        if self.required and self.default is not None:
            raise ValueError("required parameters cannot declare a default")
        return self


class CredentialReference(StrictModel):
    """A name resolved at runtime; never the credential value."""

    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    purpose: str


class CoordinatePoint(StrictModel):
    """Viewport-normalized coordinates survive pixel-size changes, not layout drift."""

    x_ratio: float = Field(ge=0, le=1)
    y_ratio: float = Field(ge=0, le=1)
    recorded_viewport_width: int = Field(gt=0)
    recorded_viewport_height: int = Field(gt=0)


class LocatorStrategy(StrictModel):
    kind: LocatorKind
    rank: int = Field(ge=1, le=100)
    reasoning: str = Field(min_length=8)
    value: str | None = None
    role: str | None = None
    name: str | None = None
    frame_path: list[str] = Field(default_factory=list)
    anchor_text: str | None = None
    coordinates: CoordinatePoint | None = None

    @model_validator(mode="after")
    def validate_payload_for_kind(self) -> Self:
        if self.kind == LocatorKind.ROLE_NAME and (not self.role or not self.name):
            raise ValueError("role_name requires role and name")
        if self.kind == LocatorKind.COORDINATES and self.coordinates is None:
            raise ValueError("coordinates locator requires coordinates")
        if self.kind not in {LocatorKind.ROLE_NAME, LocatorKind.COORDINATES} and not self.value:
            raise ValueError(f"{self.kind} locator requires value")
        return self


class Checkpoint(StrictModel):
    kind: CheckpointKind
    description: str
    expected: str | bool
    locator: LocatorStrategy | None = None
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)

    @model_validator(mode="after")
    def locator_required_for_element_checks(self) -> Self:
        element_kinds = {
            CheckpointKind.ELEMENT_VISIBLE,
            CheckpointKind.ELEMENT_ABSENT,
            CheckpointKind.VALUE_MATCHES,
        }
        if self.kind in element_kinds and self.locator is None:
            raise ValueError(f"{self.kind} checkpoint requires a locator")
        return self


class RetryPolicy(StrictModel):
    max_attempts: int = Field(default=2, ge=1, le=5)
    initial_delay_ms: int = Field(default=250, ge=0, le=30_000)
    backoff_multiplier: float = Field(default=2.0, ge=1, le=5)
    jitter_ratio: float = Field(default=0.1, ge=0, le=1)


class ObservationRule(StrictModel):
    """Maps deterministic UI evidence to caller-visible semantics."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    classification: OutcomeClass
    description: str
    when: Checkpoint
    recovery: RecoveryAction
    retry_policy: RetryPolicy | None = None

    @model_validator(mode="after")
    def recoverable_rules_have_retry_policy(self) -> Self:
        if self.classification == OutcomeClass.RECOVERABLE and self.retry_policy is None:
            raise ValueError("recoverable rules require a retry_policy")
        return self


class CapabilityStep(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str
    action: ActionType
    locators: list[LocatorStrategy] = Field(default_factory=list)
    value_template: str | None = None
    credential_ref: str | None = None
    preconditions: list[Checkpoint] = Field(default_factory=list)
    postconditions: list[Checkpoint] = Field(default_factory=list)
    observation_rules: list[ObservationRule] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    risk_class: RiskClass = RiskClass.SAFE

    @model_validator(mode="after")
    def validate_step_shape(self) -> Self:
        needs_target = {
            ActionType.CLICK,
            ActionType.TYPE,
            ActionType.SELECT,
            ActionType.EXTRACT,
        }
        if self.action in needs_target and not self.locators:
            raise ValueError(f"{self.action} step requires at least one locator")
        if self.action == ActionType.TYPE and not (self.value_template or self.credential_ref):
            raise ValueError("type step requires value_template or credential_ref")
        ranks = [locator.rank for locator in self.locators]
        if len(ranks) != len(set(ranks)):
            raise ValueError("locator ranks must be unique within a step")
        return self


class ExtractionSpec(StrictModel):
    locators: list[LocatorStrategy] = Field(min_length=1)
    attribute: str = "text_content"
    transform: str | None = None


class OutputSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: ValueType
    description: str
    required: bool = True
    extraction: ExtractionSpec


class TargetSpec(StrictModel):
    app_id: str
    vendor_product: str
    surface: SurfaceKind
    entry_url_template: str
    allowed_origin: str
    product_version: str | None = None


class ArtifactMetadata(StrictModel):
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: str = "llm_discovery"
    source_run_id: str
    approved_for_unattended_replay: bool = False
    tags: list[str] = Field(default_factory=list)


class CapabilityArtifact(StrictModel):
    schema_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    capability_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    capability_id: UUID
    name: str
    description: str
    target: TargetSpec
    input_parameters: list[ParameterSpec] = Field(default_factory=list)
    credential_references: list[CredentialReference] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    steps: list[CapabilityStep] = Field(min_length=1)
    success_checkpoint: Checkpoint
    metadata: ArtifactMetadata
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        for label, values in (
            ("parameter", [item.name for item in self.input_parameters]),
            ("credential reference", [item.name for item in self.credential_references]),
            ("output", [item.name for item in self.outputs]),
            ("step", [item.id for item in self.steps]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} names are not allowed")

        parameter_names = {item.name for item in self.input_parameters}
        credential_names = {item.name for item in self.credential_references}
        for step in self.steps:
            if step.credential_ref and step.credential_ref not in credential_names:
                raise ValueError(f"unknown credential reference: {step.credential_ref}")
            if step.value_template:
                placeholders = set(re.findall(r"\{([a-z][a-z0-9_]*)\}", step.value_template))
                unknown = placeholders - parameter_names
                if unknown:
                    raise ValueError(f"unknown parameter placeholders: {sorted(unknown)}")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def calculate_content_hash(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":")
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def with_content_hash(self) -> CapabilityArtifact:
        return self.model_copy(update={"content_hash": self.calculate_content_hash()})

    def verify_content_hash(self) -> bool:
        return self.content_hash is not None and self.content_hash == self.calculate_content_hash()

    def agent_input_schema(self) -> dict[str, Any]:
        """Export a compact JSON Schema suitable for tool/function calling."""

        type_map = {
            ValueType.STRING: "string",
            ValueType.INTEGER: "integer",
            ValueType.NUMBER: "number",
            ValueType.BOOLEAN: "boolean",
            ValueType.DATE: "string",
            ValueType.MONEY: "number",
        }
        properties: dict[str, Any] = {}
        required: list[str] = []
        for parameter in self.input_parameters:
            prop: dict[str, Any] = {
                "type": type_map[ValueType(parameter.type)],
                "description": parameter.description,
            }
            if parameter.type == ValueType.DATE:
                prop["format"] = "date"
            if parameter.pattern:
                prop["pattern"] = parameter.pattern
            if parameter.examples:
                prop["examples"] = parameter.examples
            if not parameter.required:
                prop["default"] = parameter.default
            else:
                required.append(parameter.name)
            properties[parameter.name] = prop
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }
