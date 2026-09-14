"""Attack and operator scenarios for the claims-lookup capability."""

from __future__ import annotations

from interface_ai.eval.score import EvalScenario
from interface_ai.replay.result import ReplayStatus


def default_healthcare_scenarios() -> list[EvalScenario]:
    """Happy path plus the runtime attacks a servicing clerk actually hits."""

    return [
        EvalScenario(
            name="happy_path",
            parameters={"member_id": "MRN-10042"},
            expected_status=ReplayStatus.SUCCESS,
            expect_outputs=True,
        ),
        EvalScenario(
            name="not_found",
            parameters={"member_id": "MRN-99999"},
            expected_status=ReplayStatus.BUSINESS_OUTCOME,
            expected_outcome_code="PATIENT_NOT_FOUND",
        ),
        EvalScenario(
            name="not_found_alt",
            parameters={"member_id": "MRN-00000"},
            expected_status=ReplayStatus.BUSINESS_OUTCOME,
            expected_outcome_code="PATIENT_NOT_FOUND",
        ),
        EvalScenario(
            name="invalid_mrn",
            parameters={"member_id": "not-an-mrn"},
            expected_status=ReplayStatus.HARD_FAILURE,
            expected_failure_code="INVALID_INPUT",
        ),
        EvalScenario(
            name="bad_credentials",
            parameters={"member_id": "MRN-10042"},
            expected_status=ReplayStatus.HARD_FAILURE,
            credentials_override={"DEMO_PASSWORD": "wrong-demo-value"},
        ),
        EvalScenario(
            name="policy_egress",
            parameters={"member_id": "MRN-10042"},
            expected_status=ReplayStatus.HARD_FAILURE,
            expected_failure_code="ORIGIN_NOT_ALLOWED",
            mutate_entry_url="https://evil.example/xpath-cascade-healthcare",
        ),
        EvalScenario(
            name="human_recovery",
            parameters={"member_id": "MRN-10042"},
            expected_status=ReplayStatus.SUCCESS,
            expect_outputs=True,
            credentials_override={"DEMO_PASSWORD": "wrong-demo-value"},
            use_handoff=True,
            live=True,
        ),
    ]
