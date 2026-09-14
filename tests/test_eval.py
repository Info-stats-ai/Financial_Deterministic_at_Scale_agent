import json
from pathlib import Path

from interface_ai.artifact.io import load_artifact
from interface_ai.eval.score import (
    EVAL_GATES,
    TrialRecord,
    score_contract,
    score_trials,
)
from interface_ai.replay.result import ReplayStatus


def test_golden_contract_beats_draft_and_meets_static_gates() -> None:
    golden = load_artifact(Path("evidence/artifacts/lookup_patient_recent_claims.v1.json"))
    draft = load_artifact(Path("evidence/discovery/discovery-live/artifact.json"))

    golden_score = score_contract(golden)
    draft_score = score_contract(draft)

    assert golden_score["has_business_rule"] == 1.0
    assert golden_score["parameterized_locators"] == 1.0
    assert golden_score["coordinate_rank1_count"] == 0.0
    assert golden_score["locator_quality"] >= EVAL_GATES["locator_quality_min"]
    assert golden_score["contract_score"] >= EVAL_GATES["contract_score_min"]
    assert golden_score["contract_score"] > draft_score["contract_score"]
    assert draft_score["has_business_rule"] == 0.0
    draft_report = json.loads(Path("evidence/eval/discovery-live.contract.json").read_text())
    assert draft_report["passed"] is False



def test_trial_score_approves_perfect_offline_pattern() -> None:
    artifact = load_artifact(Path("evidence/artifacts/lookup_patient_recent_claims.v1.json"))
    happy = TrialRecord(
        scenario="happy_path",
        status=ReplayStatus.SUCCESS,
        outputs={"patient_status": "Active", "latest_claim": "CLM-1"},
        duration_ms=2000,
        locator_kinds=["role_name", "xpath", "role_name"],
    )
    missing = TrialRecord(
        scenario="not_found",
        status=ReplayStatus.BUSINESS_OUTCOME,
        outcome_code="PATIENT_NOT_FOUND",
        duration_ms=1800,
        locator_kinds=["role_name"],
    )
    report = score_trials(
        artifact,
        [happy, happy, missing, missing],
        repeats=2,
    )

    assert report.passed
    assert report.recommendation == "approve_unattended_replay"
    assert report.metrics["happy_path_success_rate"] == 1.0
    assert report.metrics["business_outcome_fidelity"] == 1.0
    assert report.metrics["output_determinism"] == 1.0
    assert report.composite >= EVAL_GATES["composite_min"]


def _trial(**kwargs: object) -> TrialRecord:
    payload = {
        "scenario": "happy_path",
        "status": ReplayStatus.SUCCESS,
        "duration_ms": 1,
        "locator_kinds": ["role_name"],
    }
    payload.update(kwargs)
    return TrialRecord.model_validate(payload)


def test_attack_and_hitl_trials_are_gated() -> None:
    artifact = load_artifact(Path("evidence/artifacts/lookup_patient_recent_claims.v1.json"))
    report = score_trials(
        artifact,
        [
            _trial(scenario="happy_path", outputs={"patient_status": "Active"}),
            _trial(
                scenario="not_found",
                status=ReplayStatus.BUSINESS_OUTCOME,
                outcome_code="PATIENT_NOT_FOUND",
            ),
            _trial(
                scenario="invalid_mrn",
                status=ReplayStatus.HARD_FAILURE,
                failure_code="INVALID_INPUT",
            ),
            _trial(scenario="bad_credentials", status=ReplayStatus.HARD_FAILURE),
            _trial(
                scenario="policy_egress",
                status=ReplayStatus.HARD_FAILURE,
                failure_code="ORIGIN_NOT_ALLOWED",
            ),
            _trial(
                scenario="human_recovery",
                status=ReplayStatus.SUCCESS,
                outputs={"patient_status": "Active"},
                handoff_used=True,
                human_action_count=2,
            ),
        ],
        repeats=1,
    )
    assert report.passed
    assert report.gates["hitl_recovery_rate"] is True
    assert report.gates["invalid_mrn_fidelity"] is True
    assert report.metrics["trial_count"] == 6


def test_nondeterministic_outputs_fail_gates() -> None:
    artifact = load_artifact(Path("evidence/artifacts/lookup_patient_recent_claims.v1.json"))
    trials = [
        TrialRecord(
            scenario="happy_path",
            status=ReplayStatus.SUCCESS,
            outputs={"patient_status": "Active", "latest_claim": "A"},
            duration_ms=1,
            locator_kinds=["role_name"],
        ),
        TrialRecord(
            scenario="happy_path",
            status=ReplayStatus.SUCCESS,
            outputs={"patient_status": "Active", "latest_claim": "B"},
            duration_ms=1,
            locator_kinds=["role_name"],
        ),
        TrialRecord(
            scenario="not_found",
            status=ReplayStatus.BUSINESS_OUTCOME,
            outcome_code="PATIENT_NOT_FOUND",
            duration_ms=1,
            locator_kinds=["role_name"],
        ),
    ]
    report = score_trials(artifact, trials, repeats=2)
    assert report.gates["output_determinism"] is False
    assert report.passed is False
    assert report.recommendation == "keep_draft_review_locators_or_outcomes"
