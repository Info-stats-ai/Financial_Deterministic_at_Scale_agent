import asyncio
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import httpx

from interface_ai.artifact.schema import (
    ActionType,
    ArtifactMetadata,
    CapabilityArtifact,
    CapabilityStep,
    Checkpoint,
    CheckpointKind,
    LocatorKind,
    LocatorStrategy,
    RiskClass,
    SurfaceKind,
    TargetSpec,
)
from interface_ai.core.session import ControlOwner, SessionManager
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.handoff.controller import HandoffController
from interface_ai.handoff.models import InterventionReason, InterventionRequest
from interface_ai.handoff.operator_app import create_operator_app
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayStatus
from interface_ai.safety.policy import (
    ActionPolicy,
    NetworkPolicy,
    PolicyConfig,
    PolicyGate,
    RedactionPolicy,
)
from interface_ai.safety.redaction import Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface


def risky_artifact(url: str) -> CapabilityArtifact:
    button = LocatorStrategy(
        kind=LocatorKind.ROLE_NAME,
        rank=1,
        role="button",
        name="Submit Claim",
        reasoning="Stable accessible name for consequential action",
    )
    return CapabilityArtifact(
        capability_version="1.0.0",
        capability_id=UUID("eb9668b5-ea8a-443c-b95f-e714d2ec3492"),
        name="submit_claim",
        description="Submit a synthetic claim with human approval",
        target=TargetSpec(
            app_id="handoff-test",
            vendor_product="Handoff Test",
            surface=SurfaceKind.WEB,
            entry_url_template=url,
            allowed_origin="data://",
        ),
        steps=[
            CapabilityStep(
                id="submit-claim",
                description="Submit Claim",
                action=ActionType.CLICK,
                locators=[button],
                risk_class=RiskClass.IRREVERSIBLE,
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.TEXT_VISIBLE,
                        description="Claim submission confirmation",
                        expected="Claim submitted",
                    )
                ],
            )
        ],
        success_checkpoint=Checkpoint(
            kind=CheckpointKind.TEXT_VISIBLE,
            description="Claim submission confirmation",
            expected="Claim submitted",
        ),
        metadata=ArtifactMetadata(source_run_id="handoff-test"),
    )


def handoff_policy() -> PolicyConfig:
    return PolicyConfig(
        version="test",
        network=NetworkPolicy(
            allowed_origins=["data://"],
            allowed_path_patterns=[".*"],
        ),
        actions=ActionPolicy(
            allowed=[ActionType.CLICK],
            risky_text_patterns=["(?i)submit claim"],
        ),
        redaction=RedactionPolicy(sensitive_keys=["password"]),
    )


async def test_human_takes_over_same_session_and_replay_reverifies(
    tmp_path: Path,
) -> None:
    url = "data:text/html," + quote(
        "<button onclick=\"this.outerHTML='<p>Claim submitted</p>'\">Submit Claim</button>"
    )
    surface = PlaywrightWebSurface(headless=True)
    await surface.start(start_url=url)
    original_context = surface.context
    config = handoff_policy()
    evidence = EvidenceRecorder(
        tmp_path / "handoff",
        run_id="handoff-test",
        redactor=Redactor(config.redaction),
    )
    session = SessionManager(
        surface,
        on_human_action=lambda action: evidence.record(
            "human_action", action.model_dump(mode="json")
        ),
    )
    controller = HandoffController(session, evidence, timeout_seconds=5)
    engine = ReplayEngine(
        surface,
        policy_gate=PolicyGate(config),
        handoff=controller,
        evidence_dir=tmp_path / "handoff",
    )

    replay_task = asyncio.create_task(engine.run(risky_artifact(url), {}))
    for _ in range(100):
        if session.owner == ControlOwner.PENDING_HUMAN:
            break
        await asyncio.sleep(0.01)

    assert session.owner == ControlOwner.PENDING_HUMAN
    await session.take_control()
    assert session.owner == ControlOwner.HUMAN
    await surface._require_page().get_by_role("button", name="Submit Claim", exact=True).click()
    await asyncio.sleep(0.05)
    await session.resume_automation()
    result = await replay_task

    assert result.status == ReplayStatus.SUCCESS
    assert result.completed_steps == 1
    assert surface.context is original_context
    assert session.owner == ControlOwner.AUTOMATION
    assert any(action.event_type == "click" for action in session.human_actions)
    assert "human_action" in evidence.events_path.read_text()
    await surface.close()


async def test_operator_api_enforces_control_transitions() -> None:
    session = SessionManager(PlaywrightWebSurface(headless=True))
    await session.request_intervention(
        InterventionRequest(
            intervention_id="int-test",
            run_id="run-test",
            reason=InterventionReason.DISCOVERY_STUCK,
            summary="Automation is stuck",
            goal_or_capability="lookup_patient",
            current_step="search",
            current_url="https://example.test",
            screenshot_path="evidence/intervention.png",
        )
    )
    transport = httpx.ASGITransport(app=create_operator_app(session))
    async with httpx.AsyncClient(transport=transport, base_url="http://operator.test") as client:
        state = (await client.get("/api/state")).json()
        assert state["owner"] == ControlOwner.PENDING_HUMAN

        taken = await client.post("/api/take-control")
        assert taken.status_code == 200
        assert session.owner == ControlOwner.HUMAN

        resumed = await client.post("/api/resume")
        assert resumed.status_code == 200
        assert session.owner == ControlOwner.AUTOMATION

        invalid = await client.post("/api/resume")
        assert invalid.status_code == 409
