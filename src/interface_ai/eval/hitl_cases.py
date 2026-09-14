"""One hundred tracked HITL login-failure cases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from interface_ai.eval.operator import OperatorMode
from interface_ai.replay.result import ReplayStatus

HITL_CASE_COUNT = 100
RECOVER_COUNT = 70
ABANDON_COUNT = 15
FAIL_AGAIN_COUNT = 15


class HitlCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    index: int
    mode: OperatorMode
    member_id: str
    wrong_password: str
    operator_password: str
    expected_status: ReplayStatus
    expected_failure_code: str | None = None
    expected_recovered: bool
    sample: bool = False
    notes: str


class HitlCaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    mode: OperatorMode
    expected_status: ReplayStatus
    status: ReplayStatus
    failure_code: str | None = None
    recovered: bool
    took_control: bool
    resumed: bool
    same_session: bool
    context_id: int | None = None
    completed_steps: int
    duration_ms: int
    owner_trace: list[str] = Field(default_factory=list)
    matched_expected: bool
    evidence_dir: str | None = None


class HitlPackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int
    recovered: int
    abandoned: int
    failed_recovery: int
    matched_expected: int
    same_session: int
    same_session_rate: float
    passed: bool
    notes: list[str] = Field(default_factory=list)


def representative_hitl_cases() -> list[HitlCase]:
    cases = build_hitl_cases()
    return [next(item for item in cases if item.mode == mode) for mode in OperatorMode]


def build_hitl_cases() -> list[HitlCase]:
    cases: list[HitlCase] = []
    index = 1
    for _ in range(RECOVER_COUNT):
        cases.append(_case(index, OperatorMode.RECOVER, sample=index == 1))
        index += 1
    first_abandon = index
    for _ in range(ABANDON_COUNT):
        cases.append(_case(index, OperatorMode.ABANDON, sample=index == first_abandon))
        index += 1
    first_fail = index
    for _ in range(FAIL_AGAIN_COUNT):
        cases.append(_case(index, OperatorMode.FAIL_AGAIN, sample=index == first_fail))
        index += 1
    if len(cases) != HITL_CASE_COUNT:
        raise RuntimeError(f"expected {HITL_CASE_COUNT} HITL cases, built {len(cases)}")
    return cases


def _case(index: int, mode: OperatorMode, *, sample: bool) -> HitlCase:
    case_id = f"hitl-{index:04d}"
    wrong = f"wrong-login-{index:03d}"
    if mode == OperatorMode.RECOVER:
        return HitlCase(
            case_id=case_id,
            index=index,
            mode=mode,
            member_id="MRN-10042",
            wrong_password=wrong,
            operator_password="claims123",
            expected_status=ReplayStatus.SUCCESS,
            expected_recovered=True,
            sample=sample,
            notes="Failed login escalates; clerk types the real password on the same session.",
        )
    if mode == OperatorMode.ABANDON:
        return HitlCase(
            case_id=case_id,
            index=index,
            mode=mode,
            member_id="MRN-10042",
            wrong_password=wrong,
            operator_password="claims123",
            expected_status=ReplayStatus.INTERVENTION_REQUIRED,
            expected_failure_code="HANDOFF_NOT_RESUMED",
            expected_recovered=False,
            sample=sample,
            notes="Clerk never takes control; handoff times out on the live session.",
        )
    return HitlCase(
        case_id=case_id,
        index=index,
        mode=mode,
        member_id="MRN-10042",
        wrong_password=wrong,
        operator_password=wrong,
        expected_status=ReplayStatus.HARD_FAILURE,
        expected_failure_code="STEP_FAILED",
        expected_recovered=False,
        sample=sample,
        notes="Clerk resumes with another bad password; checkpoint still fails.",
    )
