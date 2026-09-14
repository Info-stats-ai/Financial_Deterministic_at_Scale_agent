"""Run scored replay trials. This path never calls an LLM."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from interface_ai.artifact.schema import CapabilityArtifact
from interface_ai.core.session import SessionManager
from interface_ai.eval.operator import SimulatedClaimsOperator
from interface_ai.eval.scenarios import default_healthcare_scenarios
from interface_ai.eval.score import EvalReport, EvalScenario, TrialRecord, score_trials
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.handoff.controller import HandoffController
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayResult, ReplayStatus
from interface_ai.safety.policy import PolicyGate
from interface_ai.safety.redaction import Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface

__all__ = ["EvaluationRunner", "default_healthcare_scenarios"]


def _locator_kinds_from_events(path: Path) -> tuple[list[str], bool, int]:
    kinds: list[str] = []
    policy_denied = False
    human_actions = 0
    if not path.exists():
        return kinds, policy_denied, human_actions
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
        if event_type == "human_action":
            human_actions += 1
    return kinds, policy_denied, human_actions


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
        include_live: bool = True,
    ) -> None:
        self.artifact = artifact
        self.credentials = credentials
        self.policy_gate = policy_gate
        self.redactor = redactor
        self.offline_har = offline_har
        self.work_dir = work_dir
        self.headless = headless
        self.include_live = include_live

    def _artifact_for(self, scenario: EvalScenario) -> CapabilityArtifact:
        if not scenario.mutate_entry_url:
            return self.artifact
        return self.artifact.model_copy(
            update={
                "target": self.artifact.target.model_copy(
                    update={"entry_url_template": scenario.mutate_entry_url}
                ),
                "content_hash": None,
            }
        )

    async def _run_one(
        self,
        scenario: EvalScenario,
        index: int,
        surface: PlaywrightWebSurface,
    ) -> TrialRecord:
        run_id = f"eval-{scenario.name}-{index + 1}-{uuid4().hex[:6]}"
        run_dir = self.work_dir / run_id
        credentials = {**self.credentials, **(scenario.credentials_override or {})}
        evidence = EvidenceRecorder(
            run_dir,
            run_id=run_id,
            redactor=self.redactor,
            secret_values=[*scenario.parameters.values(), *credentials.values()],
        )
        artifact = self._artifact_for(scenario)
        handoff: HandoffController | None = None
        operator: SimulatedClaimsOperator | None = None
        operator_task: asyncio.Task[None] | None = None
        if scenario.use_handoff:
            session = SessionManager(
                surface,
                on_human_action=lambda action: evidence.record(
                    "human_action", action.model_dump(mode="json")
                ),
            )
            handoff = HandoffController(session, evidence, timeout_seconds=40)
            operator = SimulatedClaimsOperator(
                session,
                username=self.credentials.get("DEMO_USERNAME", "provider"),
                password=self.credentials.get("DEMO_PASSWORD", "claims123"),
            )
            operator_task = asyncio.create_task(operator.run())
        result = ReplayResult(
            run_id=run_id,
            capability_id=str(artifact.capability_id),
            capability_version=artifact.capability_version,
            status=ReplayStatus.HARD_FAILURE,
            duration_ms=0,
        )
        try:
            result = await ReplayEngine(
                surface,
                evidence_dir=run_dir,
                evidence=evidence,
                policy_gate=self.policy_gate,
                handoff=handoff,
            ).run(
                artifact,
                scenario.parameters,
                credentials=credentials,
                run_id=run_id,
                keep_session_open=True,
            )
        finally:
            if operator_task and not operator_task.done():
                operator_task.cancel()
                try:
                    await operator_task
                except asyncio.CancelledError:
                    pass
            if surface.page is not None:
                await surface.close(shutdown_browser=False)

        evidence.write_json("result.json", result.model_dump(mode="json"))
        kinds, denied, human_actions = _locator_kinds_from_events(run_dir / "events.jsonl")
        return TrialRecord(
            scenario=scenario.name,
            status=ReplayStatus(result.status),
            outcome_code=result.outcome_code,
            outputs=result.outputs,
            duration_ms=result.duration_ms,
            locator_kinds=kinds,
            policy_denied=denied,
            failure_code=result.failure.code if result.failure else None,
            handoff_used=bool(operator and operator.recovered),
            human_action_count=human_actions,
        )

    async def run(
        self,
        scenarios: list[EvalScenario],
        *,
        repeats: int,
        hitl_repeats: int = 3,
    ) -> EvalReport:
        if repeats < 1:
            raise ValueError("repeats must be >= 1")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        offline_surface = PlaywrightWebSurface(
            headless=self.headless,
            replay_har_path=self.offline_har,
        )
        live_surface = PlaywrightWebSurface(headless=self.headless)
        trials: list[TrialRecord] = []
        try:
            for scenario in scenarios:
                if scenario.live and not self.include_live:
                    continue
                count = hitl_repeats if scenario.use_handoff else repeats
                surface = live_surface if scenario.live else offline_surface
                for index in range(count):
                    trials.append(await self._run_one(scenario, index, surface))
        finally:
            await offline_surface.close()
            await live_surface.close()
        return score_trials(self.artifact, trials, repeats=repeats)
