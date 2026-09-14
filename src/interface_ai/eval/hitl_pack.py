"""Run tracked HITL login failures on a hermetic portal, not live CloudCruise."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections import Counter
from pathlib import Path

from interface_ai.artifact.schema import ActionType, CapabilityArtifact, RetryPolicy
from interface_ai.core.session import SessionManager
from interface_ai.demo_artifact import build_demo_artifact
from interface_ai.eval.hitl_cases import HitlCase, HitlCaseRecord, HitlPackSummary
from interface_ai.eval.operator import OperatorMode, SimulatedClaimsOperator
from interface_ai.eval.portal import claims_portal_url
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.handoff.controller import HandoffController
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayResult, ReplayStatus
from interface_ai.safety.policy import (
    ActionPolicy,
    NetworkPolicy,
    PolicyConfig,
    PolicyGate,
    RedactionPolicy,
)
from interface_ai.safety.redaction import Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface

FAST_RETRY = RetryPolicy(max_attempts=1, initial_delay_ms=0, jitter_ratio=0)
FAST_TIMEOUT_MS = 400


def hitl_policy() -> PolicyConfig:
    return PolicyConfig(
        version="hitl-eval",
        network=NetworkPolicy(allowed_origins=["data://"], allowed_path_patterns=[".*"]),
        actions=ActionPolicy(
            allowed=[ActionType.CLICK, ActionType.TYPE, ActionType.WAIT, ActionType.EXTRACT]
        ),
        redaction=RedactionPolicy(sensitive_keys=["password", "member_id", "mrn"]),
    )


def fast_hitl_artifact(entry_url: str) -> CapabilityArtifact:
    base = build_demo_artifact()
    steps = []
    for step in base.steps:
        posts = [
            item.model_copy(update={"timeout_ms": FAST_TIMEOUT_MS})
            for item in step.postconditions
        ]
        rules = [
            rule.model_copy(
                update={
                    "when": rule.when.model_copy(
                        update={"timeout_ms": min(rule.when.timeout_ms, FAST_TIMEOUT_MS)}
                    ),
                    "wait_ms": 0,
                }
            )
            for rule in step.observation_rules
        ]
        steps.append(
            step.model_copy(
                update={
                    "postconditions": posts,
                    "observation_rules": rules,
                    "retry_policy": FAST_RETRY,
                }
            )
        )
    success = (
        base.success_checkpoint.model_copy(update={"timeout_ms": FAST_TIMEOUT_MS})
        if base.success_checkpoint
        else None
    )
    return base.model_copy(
        update={
            "target": base.target.model_copy(update={"entry_url_template": entry_url}),
            "steps": steps,
            "success_checkpoint": success,
            "content_hash": None,
        }
    )


def _matched(case: HitlCase, result: ReplayResult, operator: SimulatedClaimsOperator) -> bool:
    failure_code = result.failure.code if result.failure else None
    if result.status != case.expected_status:
        return False
    if case.expected_failure_code and failure_code != case.expected_failure_code:
        return False
    if operator.recovered != case.expected_recovered:
        return False
    return True


def _same_session(operator: SimulatedClaimsOperator, surface: PlaywrightWebSurface) -> bool:
    ids = list(operator.context_ids)
    if surface.context is not None:
        ids.append(id(surface.context))
    return bool(ids) and len(set(ids)) == 1


async def _run_one(
    case: HitlCase,
    *,
    artifact: CapabilityArtifact,
    policy: PolicyConfig,
    surface: PlaywrightWebSurface,
    work_dir: Path,
    persist_evidence: bool,
) -> HitlCaseRecord:
    run_dir = work_dir / case.case_id
    redactor = Redactor(policy.redaction)
    evidence = EvidenceRecorder(
        run_dir,
        run_id=case.case_id,
        redactor=redactor,
        secret_values=[
            case.wrong_password,
            case.operator_password,
            "claims123",
            case.member_id,
        ],
    )
    session = SessionManager(
        surface,
        on_human_action=lambda action: evidence.record(
            "human_action", action.model_dump(mode="json")
        ),
    )
    handoff_timeout = 0.4 if case.mode == OperatorMode.ABANDON else 20
    operator_timeout = 2 if case.mode == OperatorMode.ABANDON else 20
    handoff = HandoffController(
        session,
        evidence,
        timeout_seconds=handoff_timeout,
        capture_screenshot=persist_evidence,
    )
    operator = SimulatedClaimsOperator(
        session,
        username="provider",
        password=case.operator_password,
        timeout_seconds=operator_timeout,
        mode=case.mode,
        patients_timeout_ms=2_000,
    )
    operator_task = asyncio.create_task(operator.run())
    result = ReplayResult(
        run_id=case.case_id,
        capability_id=str(artifact.capability_id),
        capability_version=artifact.capability_version,
        status=ReplayStatus.HARD_FAILURE,
        duration_ms=0,
    )
    same_session = False
    try:
        result = await ReplayEngine(
            surface,
            evidence_dir=run_dir,
            evidence=evidence,
            policy_gate=PolicyGate(policy),
            handoff=handoff,
        ).run(
            artifact,
            {"member_id": case.member_id},
            credentials={"DEMO_USERNAME": "provider", "DEMO_PASSWORD": case.wrong_password},
            run_id=case.case_id,
            keep_session_open=True,
        )
        same_session = _same_session(operator, surface)
    finally:
        if not operator_task.done():
            operator_task.cancel()
            try:
                await operator_task
            except asyncio.CancelledError:
                pass
        if surface.page is not None:
            await surface.close(shutdown_browser=False)

    evidence.write_json("result.json", result.model_dump(mode="json"))
    record = HitlCaseRecord(
        case_id=case.case_id,
        mode=case.mode,
        expected_status=case.expected_status,
        status=result.status,
        failure_code=result.failure.code if result.failure else None,
        recovered=operator.recovered,
        took_control=operator.took_control,
        resumed=operator.resumed,
        same_session=same_session,
        context_id=operator.context_ids[0] if operator.context_ids else None,
        completed_steps=result.completed_steps,
        duration_ms=result.duration_ms,
        owner_trace=_dedupe_trace(operator.owner_trace),
        matched_expected=_matched(case, result, operator) and same_session,
        evidence_dir=str(run_dir) if persist_evidence else None,
    )
    evidence.record("hitl_case", record.model_dump(mode="json"))
    if persist_evidence:
        evidence.write_json("case.json", case.model_dump(mode="json"))
    return record


def _dedupe_trace(trace: list[str]) -> list[str]:
    compact: list[str] = []
    for owner in trace:
        if not compact or compact[-1] != owner:
            compact.append(owner)
    return compact


async def run_hitl_pack(
    cases: list[HitlCase],
    *,
    out_dir: Path,
    headless: bool = True,
) -> HitlPackSummary:
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "runs"
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    policy = hitl_policy()
    artifact = fast_hitl_artifact(claims_portal_url())
    surface = PlaywrightWebSurface(headless=headless, viewport=(900, 700))
    records: list[HitlCaseRecord] = []
    ledger_path = out_dir / "ledger.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    try:
        for case in cases:
            persist = case.sample
            record = await _run_one(
                case,
                artifact=artifact,
                policy=policy,
                surface=surface,
                work_dir=samples_dir if persist else work_dir,
                persist_evidence=persist,
            )
            if persist:
                sample_name = {
                    OperatorMode.RECOVER: "recover",
                    OperatorMode.ABANDON: "abandon",
                    OperatorMode.FAIL_AGAIN: "fail_again",
                }[case.mode]
                sample_path = samples_dir / sample_name
                source = samples_dir / case.case_id
                if source.exists() and source != sample_path:
                    if sample_path.exists():
                        shutil.rmtree(sample_path)
                    source.rename(sample_path)
                    record = record.model_copy(update={"evidence_dir": str(sample_path)})
            records.append(record)
            with ledger_path.open("a", encoding="utf-8") as stream:
                stream.write(record.model_dump_json() + "\n")
    finally:
        await surface.close()
        shutil.rmtree(work_dir, ignore_errors=True)

    counts = Counter(record.mode for record in records)
    matched = sum(item.matched_expected for item in records)
    same_session = sum(item.same_session for item in records)
    summary = HitlPackSummary(
        case_count=len(records),
        recovered=counts[OperatorMode.RECOVER],
        abandoned=counts[OperatorMode.ABANDON],
        failed_recovery=counts[OperatorMode.FAIL_AGAIN],
        matched_expected=matched,
        same_session=same_session,
        same_session_rate=round(same_session / len(records), 4) if records else 0.0,
        passed=matched == len(records) and same_session == len(records),
        notes=[
            "Hermetic HTML portal; short checkpoints. Does not hammer the live demo.",
            "Failed login always escalates on the live BrowserContext.",
            "recover: clerk types claims123 and replay finishes.",
            "abandon: clerk never takes control; handoff times out.",
            "fail_again: clerk resumes with another bad password; checkpoint fails.",
        ],
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "cases.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in cases], indent=2) + "\n",
        encoding="utf-8",
    )
    return summary
