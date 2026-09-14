"""Deterministic scoring of artifact contracts and replay trials."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from interface_ai.artifact.schema import CapabilityArtifact, LocatorKind, OutcomeClass
from interface_ai.replay.result import ReplayStatus

# Gates for unattended replay. Chosen to match the brief: happy path, exceptional
# business states, determinism, and no pixel-only targeting.
EVAL_GATES: dict[str, float] = {
    "happy_path_success_rate": 1.0,
    "business_outcome_fidelity": 1.0,
    "output_determinism": 1.0,
    "coordinate_fallback_rate_max": 0.0,
    "locator_quality_min": 0.70,
    "contract_score_min": 0.80,
    "composite_min": 90.0,
    "attack_fidelity_min": 1.0,
    "hitl_recovery_min": 1.0,
}

_SEMANTIC = {"role_name", "label", "text"}
_COORDINATES = {"coordinates"}


class EvalScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    parameters: dict[str, str]
    expected_status: ReplayStatus
    expected_outcome_code: str | None = None
    expected_failure_code: str | None = None
    expect_outputs: bool = False
    credentials_override: dict[str, str] | None = None
    mutate_entry_url: str | None = None
    use_handoff: bool = False
    live: bool = False


class TrialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str
    status: ReplayStatus
    outcome_code: str | None = None
    outputs: dict[str, Any] | None = None
    duration_ms: int
    locator_kinds: list[str] = Field(default_factory=list)
    policy_denied: bool = False
    failure_code: str | None = None
    handoff_used: bool = False
    human_action_count: int = 0


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_name: str
    capability_version: str
    artifact_hash: str | None
    evaluated_at: datetime
    repeats: int
    metrics: dict[str, float]
    gates: dict[str, bool]
    passed: bool
    composite: float
    recommendation: str
    trials: list[TrialRecord]
    notes: list[str] = Field(default_factory=list)


def locator_kind_score(kind: str, value: str | None = None) -> float:
    normalized = str(kind).lower()
    if normalized in _SEMANTIC:
        return 1.0
    if normalized in _COORDINATES:
        return 0.1
    blob = f"{normalized} {value or ''}".lower()
    if "data-column" in blob or "{member_id}" in blob:
        return 0.85
    if "nth-of-type" in blob or "nth-child" in blob:
        return 0.35
    if normalized in {"xpath", "css"}:
        return 0.45
    return 0.5


def score_contract(artifact: CapabilityArtifact) -> dict[str, float]:
    """Static quality of the authored skill. Independent of a browser run."""

    rank1_scores: list[float] = []
    coordinate_rank1 = 0
    locator_count = 0
    for step in artifact.steps:
        for locator in step.locators:
            locator_count += 1
            if locator.rank == 1:
                rank1_scores.append(locator_kind_score(str(locator.kind), locator.value))
                if LocatorKind(locator.kind) == LocatorKind.COORDINATES:
                    coordinate_rank1 += 1
    for spec in artifact.outputs:
        for locator in spec.extraction.locators:
            locator_count += 1
            if locator.rank == 1:
                rank1_scores.append(locator_kind_score(str(locator.kind), locator.value))

    has_business_rule = any(
        OutcomeClass(rule.classification) == OutcomeClass.BUSINESS
        for step in artifact.steps
        for rule in step.observation_rules
    )
    parameterized = any(
        "{member_id}" in (locator.value or "")
        for step in artifact.steps
        for locator in step.locators
    )
    has_checkpoint = artifact.success_checkpoint is not None
    hashed = bool(artifact.content_hash)

    locator_quality = mean(rank1_scores) if rank1_scores else 0.0
    contract_score = mean(
        [
            locator_quality,
            1.0 if has_business_rule else 0.0,
            1.0 if parameterized else 0.4,
            1.0 if has_checkpoint else 0.0,
            1.0 if hashed else 0.0,
            0.0 if coordinate_rank1 else 1.0,
        ]
    )
    return {
        "locator_quality": round(locator_quality, 4),
        "contract_score": round(contract_score, 4),
        "has_business_rule": 1.0 if has_business_rule else 0.0,
        "parameterized_locators": 1.0 if parameterized else 0.0,
        "coordinate_rank1_count": float(coordinate_rank1),
        "locator_count": float(locator_count),
    }


def _rate(matches: int, total: int) -> float:
    if total == 0:
        return 0.0
    return matches / total


def score_trials(
    artifact: CapabilityArtifact,
    trials: list[TrialRecord],
    *,
    repeats: int,
) -> EvalReport:
    contract = score_contract(artifact)
    happy = [item for item in trials if item.scenario == "happy_path"]
    missing = [item for item in trials if item.scenario.startswith("not_found")]
    invalid = [item for item in trials if item.scenario == "invalid_mrn"]
    bad_login = [item for item in trials if item.scenario == "bad_credentials"]
    policy = [item for item in trials if item.scenario == "policy_egress"]
    hitl = [item for item in trials if item.scenario == "human_recovery"]
    happy_ok = sum(item.status == ReplayStatus.SUCCESS for item in happy)
    missing_ok = sum(
        item.status == ReplayStatus.BUSINESS_OUTCOME
        and item.outcome_code == "PATIENT_NOT_FOUND"
        for item in missing
    )
    invalid_ok = sum(
        item.status == ReplayStatus.HARD_FAILURE and item.failure_code == "INVALID_INPUT"
        for item in invalid
    )
    bad_login_ok = sum(item.status == ReplayStatus.HARD_FAILURE for item in bad_login)
    policy_ok = sum(
        item.status == ReplayStatus.HARD_FAILURE and item.failure_code == "ORIGIN_NOT_ALLOWED"
        for item in policy
    )
    hitl_ok = sum(
        item.status == ReplayStatus.SUCCESS and item.handoff_used for item in hitl
    )
    happy_outputs = [
        json.dumps(item.outputs, sort_keys=True, default=str)
        for item in happy
        if item.status == ReplayStatus.SUCCESS and item.outputs is not None
    ]
    unique_outputs = len(set(happy_outputs))
    determinism = 1.0 if unique_outputs <= 1 and happy_outputs else 0.0
    kinds = [kind for item in trials for kind in item.locator_kinds]
    coord_rate = _rate(sum(kind == "coordinates" for kind in kinds), len(kinds)) if kinds else 0.0
    durations = [item.duration_ms for item in trials]
    locator_quality_runtime = (
        mean(locator_kind_score(kind) for kind in kinds) if kinds else contract["locator_quality"]
    )

    happy_rate = _rate(happy_ok, len(happy))
    fidelity = _rate(missing_ok, len(missing))
    locator_quality = min(contract["locator_quality"], locator_quality_runtime)
    unexpected_policy = sum(
        item.policy_denied for item in trials if item.scenario != "policy_egress"
    )
    attack_rates = {
        "invalid_mrn_fidelity": (_rate(invalid_ok, len(invalid)) if invalid else None),
        "bad_credentials_fidelity": (_rate(bad_login_ok, len(bad_login)) if bad_login else None),
        "policy_egress_fidelity": (_rate(policy_ok, len(policy)) if policy else None),
        "hitl_recovery_rate": (_rate(hitl_ok, len(hitl)) if hitl else None),
    }
    attack_values = [value for value in attack_rates.values() if value is not None]
    attack_fidelity = mean(attack_values) if attack_values else 1.0
    composite = round(
        100
        * (
            0.28 * happy_rate
            + 0.18 * fidelity
            + 0.14 * determinism
            + 0.18 * attack_fidelity
            + 0.10 * (1.0 - coord_rate)
            + 0.12 * contract["contract_score"]
        ),
        2,
    )
    gates = {
        "happy_path_success_rate": happy_rate >= EVAL_GATES["happy_path_success_rate"],
        "business_outcome_fidelity": fidelity >= EVAL_GATES["business_outcome_fidelity"],
        "output_determinism": determinism >= EVAL_GATES["output_determinism"],
        "coordinate_fallback": coord_rate <= EVAL_GATES["coordinate_fallback_rate_max"],
        "locator_quality": locator_quality >= EVAL_GATES["locator_quality_min"],
        "contract_score": contract["contract_score"] >= EVAL_GATES["contract_score_min"],
        "composite": composite >= EVAL_GATES["composite_min"],
        "no_unexpected_policy_denials": unexpected_policy == 0,
    }
    if invalid:
        invalid_rate = attack_rates["invalid_mrn_fidelity"]
        assert invalid_rate is not None
        gates["invalid_mrn_fidelity"] = invalid_rate >= EVAL_GATES["attack_fidelity_min"]
    if bad_login:
        bad_login_rate = attack_rates["bad_credentials_fidelity"]
        assert bad_login_rate is not None
        gates["bad_credentials_fidelity"] = bad_login_rate >= EVAL_GATES["attack_fidelity_min"]
    if policy:
        policy_rate = attack_rates["policy_egress_fidelity"]
        assert policy_rate is not None
        gates["policy_egress_fidelity"] = policy_rate >= EVAL_GATES["attack_fidelity_min"]
    if hitl:
        hitl_rate = attack_rates["hitl_recovery_rate"]
        assert hitl_rate is not None
        gates["hitl_recovery_rate"] = hitl_rate >= EVAL_GATES["hitl_recovery_min"]
    passed = all(gates.values())
    recommendation = (
        "approve_unattended_replay"
        if passed
        else "keep_draft_review_locators_or_outcomes"
    )
    notes = [
        f"happy_path {happy_ok}/{len(happy)} success",
        f"not_found {missing_ok}/{len(missing)} PATIENT_NOT_FOUND",
        f"invalid_mrn {invalid_ok}/{len(invalid)}" if invalid else "invalid_mrn not run",
        (
            f"bad_credentials {bad_login_ok}/{len(bad_login)}"
            if bad_login
            else "bad_credentials not run"
        ),
        f"policy_egress {policy_ok}/{len(policy)}" if policy else "policy_egress not run",
        f"human_recovery {hitl_ok}/{len(hitl)} same-session" if hitl else "human_recovery not run",
        f"unique successful output fingerprints={unique_outputs}",
        f"locator kinds={dict(Counter(kinds))}" if kinds else "no runtime locator events",
    ]
    metrics = {
        "happy_path_success_rate": round(happy_rate, 4),
        "business_outcome_fidelity": round(fidelity, 4),
        "output_determinism": determinism,
        "coordinate_fallback_rate": round(coord_rate, 4),
        "locator_quality": round(locator_quality, 4),
        "contract_score": contract["contract_score"],
        "mean_duration_ms": round(mean(durations), 1) if durations else 0.0,
        "unexpected_policy_denials": float(unexpected_policy),
        "attack_fidelity": round(attack_fidelity, 4),
        "composite": composite,
        "trial_count": float(len(trials)),
        **{
            key: round(value, 4)
            for key, value in attack_rates.items()
            if value is not None
        },
        **{f"contract_{key}": value for key, value in contract.items()},
    }
    return EvalReport(
        capability_name=artifact.name,
        capability_version=artifact.capability_version,
        artifact_hash=artifact.content_hash,
        evaluated_at=datetime.now(UTC),
        repeats=repeats,
        metrics=metrics,
        gates=gates,
        passed=passed,
        composite=composite,
        recommendation=recommendation,
        trials=trials,
        notes=notes,
    )
