"""Run scored replay trials. This path never calls an LLM."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from interface_ai.artifact.schema import CapabilityArtifact
from interface_ai.eval.score import EvalReport, EvalScenario, TrialRecord, score_trials
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayStatus
from interface_ai.safety.policy import PolicyGate
from interface_ai.safety.redaction import Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface


def default_healthcare_scenarios() -> list[EvalScenario]:
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
    ]


def _locator_kinds_from_events(path: Path) -> tuple[list[str], bool]:
    kinds: list[str] = []
    policy_denied = False
    if not path.exists():
        return kinds, policy_denied
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        event_type = event.get("event_type")
        payload = event.get("payload") or {}
        if event_type == "locator_resolved":
            kinds.append(str(payload.get("kind")))
        if event_type == "policy_verdict" and payload.get("allowed") is False:
            policy_denied = True
    return kinds, policy_denied


class EvaluationRunner:
    def __init__(
        self,
        artifact: CapabilityArtifact,
        *,
        credentials: dict[str, str],
        policy_gate: PolicyGate,
        redactor: Redactor,
        offline_har: Path | None,
        work_dir: Path,
        headless: bool = True,
    ) -> None:
        self.artifact = artifact
        self.credentials = credentials
        self.policy_gate = policy_gate
        self.redactor = redactor
        self.offline_har = offline_har
        self.work_dir = work_dir
        self.headless = headless

    async def run(
        self,
        scenarios: list[EvalScenario],
        *,
        repeats: int,
    ) -> EvalReport:
        if repeats < 1:
            raise ValueError("repeats must be >= 1")
        trials: list[TrialRecord] = []
        self.work_dir.mkdir(parents=True, exist_ok=True)
        for scenario in scenarios:
            for index in range(repeats):
                run_id = f"eval-{scenario.name}-{index + 1}-{uuid4().hex[:6]}"
                run_dir = self.work_dir / run_id
                evidence = EvidenceRecorder(
                    run_dir,
                    run_id=run_id,
                    redactor=self.redactor,
                    secret_values=[*scenario.parameters.values(), *self.credentials.values()],
                )
                surface = PlaywrightWebSurface(
                    headless=self.headless,
                    replay_har_path=self.offline_har,
                )
                result = await ReplayEngine(
                    surface,
                    evidence_dir=run_dir,
                    evidence=evidence,
                    policy_gate=self.policy_gate,
                ).run(
                    self.artifact,
                    scenario.parameters,
                    credentials=self.credentials,
                    run_id=run_id,
                )
                evidence.write_json("result.json", result.model_dump(mode="json"))
                kinds, denied = _locator_kinds_from_events(run_dir / "events.jsonl")
                trials.append(
                    TrialRecord(
                        scenario=scenario.name,
                        status=ReplayStatus(result.status),
                        outcome_code=result.outcome_code,
                        outputs=result.outputs,
                        duration_ms=result.duration_ms,
                        locator_kinds=kinds,
                        policy_denied=denied,
                        failure_code=result.failure.code if result.failure else None,
                    )
                )
        return score_trials(self.artifact, trials, repeats=repeats)
