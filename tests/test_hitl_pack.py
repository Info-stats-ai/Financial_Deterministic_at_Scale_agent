import json
from pathlib import Path

from interface_ai.eval.hitl_cases import (
    ABANDON_COUNT,
    FAIL_AGAIN_COUNT,
    HITL_CASE_COUNT,
    RECOVER_COUNT,
    build_hitl_cases,
    representative_hitl_cases,
)
from interface_ai.eval.hitl_pack import run_hitl_pack
from interface_ai.eval.operator import OperatorMode
from interface_ai.replay.result import ReplayStatus


def test_hitl_catalog_has_one_hundred_tracked_cases() -> None:
    cases = build_hitl_cases()
    assert len(cases) == HITL_CASE_COUNT
    assert len({item.case_id for item in cases}) == HITL_CASE_COUNT
    counts = {mode: 0 for mode in OperatorMode}
    for item in cases:
        counts[item.mode] += 1
    assert counts[OperatorMode.RECOVER] == RECOVER_COUNT
    assert counts[OperatorMode.ABANDON] == ABANDON_COUNT
    assert counts[OperatorMode.FAIL_AGAIN] == FAIL_AGAIN_COUNT
    samples = [item for item in cases if item.sample]
    assert {item.mode for item in samples} == set(OperatorMode)


async def test_hitl_operator_modes_on_same_session(tmp_path: Path) -> None:
    summary = await run_hitl_pack(
        representative_hitl_cases(),
        out_dir=tmp_path / "hitl",
        headless=True,
    )
    assert summary.case_count == 3
    assert summary.passed
    assert summary.same_session == 3
    ledger = (tmp_path / "hitl" / "ledger.jsonl").read_text().splitlines()
    assert len(ledger) == 3
    by_mode = {json.loads(line)["mode"]: json.loads(line) for line in ledger}
    assert by_mode["recover"]["status"] == ReplayStatus.SUCCESS
    assert by_mode["abandon"]["status"] == ReplayStatus.INTERVENTION_REQUIRED
    assert by_mode["fail_again"]["status"] == ReplayStatus.HARD_FAILURE
    assert (tmp_path / "hitl" / "samples" / "recover" / "events.jsonl").exists()
    assert (tmp_path / "hitl" / "samples" / "abandon" / "result.json").exists()
    assert (tmp_path / "hitl" / "samples" / "fail_again" / "result.json").exists()
