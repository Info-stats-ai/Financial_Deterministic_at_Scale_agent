"""Pause, route, and resume automation on one browser context."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import uvicorn

from interface_ai.core.session import SessionManager
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.handoff.models import (
    HandoffResolution,
    InterventionReason,
    InterventionRequest,
)
from interface_ai.handoff.operator_app import create_operator_app


class HandoffController:
    def __init__(
        self,
        session: SessionManager,
        evidence: EvidenceRecorder,
        *,
        timeout_seconds: float = 600,
        capture_screenshot: bool = True,
    ) -> None:
        self.session = session
        self.evidence = evidence
        self.timeout_seconds = timeout_seconds
        self.capture_screenshot = capture_screenshot
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None

    async def start_operator_console(self, *, host: str = "127.0.0.1", port: int = 8787) -> None:
        if self._server_task:
            return
        app = create_operator_app(self.session)
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._server_task.done():
                await self._server_task
            await asyncio.sleep(0.01)

    async def stop_operator_console(self) -> None:
        if self._server and self._server_task:
            self._server.should_exit = True
            await self._server_task
        self._server = None
        self._server_task = None

    async def intervene(
        self,
        *,
        run_id: str,
        reason: InterventionReason,
        summary: str,
        goal_or_capability: str,
        current_step: str | None,
        expected_state: str | None = None,
        observed_state: str | None = None,
    ) -> HandoffResolution:
        await self.session.install_human_action_capture()
        screenshot = Path(self.evidence.run_dir) / (f"intervention-{uuid4().hex[:8]}.png")
        screenshot_path = ""
        if self.capture_screenshot:
            await self.session.surface.snapshot(screenshot)
            screenshot_path = str(screenshot)
        request = InterventionRequest(
            intervention_id=f"int-{uuid4().hex[:12]}",
            run_id=run_id,
            reason=reason,
            summary=summary,
            goal_or_capability=goal_or_capability,
            current_step=current_step,
            current_url=self.session.surface._require_page().url,
            screenshot_path=screenshot_path,
            expected_state=expected_state,
            observed_state=observed_state,
        )
        await self.session.request_intervention(request)
        self.evidence.record("intervention_requested", request.model_dump(mode="json"))
        try:
            actions = await self.session.wait_for_resume(self.timeout_seconds)
        except TimeoutError:
            self.evidence.record(
                "intervention_timeout",
                {"intervention_id": request.intervention_id},
            )
            return HandoffResolution(
                intervention_id=request.intervention_id,
                resumed=False,
                human_actions=list(self.session.human_actions),
                reason="human intervention timed out",
            )
        self.evidence.record(
            "intervention_resumed",
            {
                "intervention_id": request.intervention_id,
                "human_actions": [action.model_dump(mode="json") for action in actions],
            },
        )
        return HandoffResolution(
            intervention_id=request.intervention_id,
            resumed=True,
            human_actions=actions,
        )
