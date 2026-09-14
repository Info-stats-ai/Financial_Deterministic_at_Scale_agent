"""Explicit ownership state for one live browser session."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from interface_ai.handoff.models import HumanAction, InterventionRequest
from interface_ai.surface.web_playwright import PlaywrightWebSurface

HUMAN_CAPTURE_SCRIPT = """
(() => {
  if (window.__humanCaptureInstalled) return;
  window.__humanCaptureInstalled = true;
  const describe = (el) => ({
    tag: el?.tagName?.toLowerCase() || null,
    role: el?.getAttribute?.('role') || null,
    accessible_name: el?.getAttribute?.('aria-label')
      || el?.innerText?.trim()?.slice(0, 120) || null,
    input_type: el?.getAttribute?.('type') || null
  });
  document.addEventListener('click', (event) => {
    window.__recordHumanAction({
      event_type: 'click',
      url: location.href,
      target: describe(event.target),
      value_was_entered: false
    });
  }, true);
  document.addEventListener('change', (event) => {
    window.__recordHumanAction({
      event_type: 'change',
      url: location.href,
      target: describe(event.target),
      value_was_entered: true
    });
  }, true);
})();
"""


class ControlOwner(StrEnum):
    AUTOMATION = "automation"
    PENDING_HUMAN = "pending_human"
    HUMAN = "human"


class InvalidControlTransition(RuntimeError):
    pass


class SessionManager:
    def __init__(
        self,
        surface: PlaywrightWebSurface,
        *,
        on_human_action: Callable[[HumanAction], None] | None = None,
    ) -> None:
        self.surface = surface
        self.owner = ControlOwner.AUTOMATION
        self.intervention: InterventionRequest | None = None
        self.human_actions: list[HumanAction] = []
        self._resume_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._on_human_action = on_human_action
        self._capture_installed = False

    async def install_human_action_capture(self) -> None:
        context = self.surface.context
        page = self.surface._require_page()
        if context is None:
            raise RuntimeError("browser context is not available")
        if self._capture_installed:
            return

        async def record_binding(_source: dict[str, Any], payload: dict[str, Any]) -> None:
            if self.owner != ControlOwner.HUMAN:
                return
            action = HumanAction.model_validate(payload)
            self.human_actions.append(action)
            if self._on_human_action:
                self._on_human_action(action)

        await context.expose_binding("__recordHumanAction", record_binding)
        await context.add_init_script(HUMAN_CAPTURE_SCRIPT)
        await page.evaluate(HUMAN_CAPTURE_SCRIPT)
        self._capture_installed = True

    async def request_intervention(self, request: InterventionRequest) -> None:
        async with self._lock:
            if self.owner != ControlOwner.AUTOMATION:
                raise InvalidControlTransition(
                    f"cannot request intervention while owner={self.owner}"
                )
            self.intervention = request
            self.human_actions = []
            self.owner = ControlOwner.PENDING_HUMAN
            self._resume_event.clear()

    async def take_control(self) -> None:
        async with self._lock:
            if self.owner != ControlOwner.PENDING_HUMAN:
                raise InvalidControlTransition(
                    f"take-control requires pending_human, observed {self.owner}"
                )
            self.owner = ControlOwner.HUMAN

    async def resume_automation(self) -> None:
        async with self._lock:
            if self.owner != ControlOwner.HUMAN:
                raise InvalidControlTransition(
                    f"resume requires human ownership, observed {self.owner}"
                )
            self.owner = ControlOwner.AUTOMATION
            self._resume_event.set()

    async def wait_for_resume(self, timeout_seconds: float) -> list[HumanAction]:
        await asyncio.wait_for(self._resume_event.wait(), timeout=timeout_seconds)
        return list(self.human_actions)

    def assert_automation_control(self) -> None:
        if self.owner != ControlOwner.AUTOMATION:
            raise InvalidControlTransition(f"automation action denied while owner={self.owner}")
