"""Fail-closed policy gate shared by discovery and replay."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field

from interface_ai.artifact.schema import ActionType, CapabilityStep, RiskClass


class NetworkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_origins: list[str] = Field(min_length=1)
    allowed_path_patterns: list[str] = Field(min_length=1)
    block_downloads: bool = True
    block_popups_to_unlisted_origins: bool = True


class ActionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: list[ActionType] = Field(min_length=1)
    risky_text_patterns: list[str] = Field(default_factory=list)
    risky_requires: str = "human_approval"


class RedactionPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    regex: str


class RedactionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensitive_keys: list[str] = Field(default_factory=list)
    patterns: list[RedactionPattern] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    network: NetworkPolicy
    actions: ActionPolicy
    redaction: RedactionPolicy


class PolicyVerdict(BaseModel):
    allowed: bool
    requires_human_approval: bool = False
    code: str
    reason: str
    policy_version: str


def load_policy(path: Path) -> PolicyConfig:
    with path.open(encoding="utf-8") as stream:
        return PolicyConfig.model_validate(yaml.safe_load(stream))


class PolicyGate:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    def check_url(self, url: str) -> PolicyVerdict:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.config.network.allowed_origins:
            return PolicyVerdict(
                allowed=False,
                code="ORIGIN_NOT_ALLOWED",
                reason=f"origin {origin!r} is not allowlisted",
                policy_version=self.config.version,
            )
        if not any(
            re.fullmatch(pattern, parsed.path)
            for pattern in self.config.network.allowed_path_patterns
        ):
            return PolicyVerdict(
                allowed=False,
                code="ROUTE_NOT_ALLOWED",
                reason=f"path {parsed.path!r} is not allowlisted",
                policy_version=self.config.version,
            )
        return PolicyVerdict(
            allowed=True,
            code="URL_ALLOWED",
            reason="origin and route are allowlisted",
            policy_version=self.config.version,
        )

    def check_step(
        self,
        step: CapabilityStep,
        *,
        current_url: str,
        navigation_url: str | None = None,
    ) -> PolicyVerdict:
        url_verdict = self.check_url(navigation_url or current_url)
        if not url_verdict.allowed:
            return url_verdict

        action = ActionType(step.action)
        allowed_actions = {ActionType(item) for item in self.config.actions.allowed}
        if action not in allowed_actions:
            return PolicyVerdict(
                allowed=False,
                code="ACTION_NOT_ALLOWED",
                reason=f"action {action.value!r} is not allowlisted",
                policy_version=self.config.version,
            )

        risk = RiskClass(step.risk_class)
        searchable = " ".join(
            [
                step.description,
                *[
                    value
                    for locator in step.locators
                    for value in (locator.value, locator.name)
                    if value
                ],
            ]
        )
        text_is_risky = any(
            re.search(pattern, searchable) for pattern in self.config.actions.risky_text_patterns
        )
        if risk in {RiskClass.RISKY, RiskClass.IRREVERSIBLE} or text_is_risky:
            return PolicyVerdict(
                allowed=True,
                requires_human_approval=True,
                code="HUMAN_APPROVAL_REQUIRED",
                reason=(
                    f"step risk={risk.value}; risky text match={text_is_risky}; "
                    f"policy requires {self.config.actions.risky_requires}"
                ),
                policy_version=self.config.version,
            )

        return PolicyVerdict(
            allowed=True,
            code="ACTION_ALLOWED",
            reason=f"{risk.value} action is allowlisted",
            policy_version=self.config.version,
        )
