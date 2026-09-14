"""Simulated operator for eval: same live session, never a new browser."""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum

from interface_ai.core.session import ControlOwner, SessionManager


class OperatorMode(StrEnum):
    RECOVER = "recover"
    ABANDON = "abandon"
    FAIL_AGAIN = "fail_again"


class SimulatedClaimsOperator:
    """Stand-in for a back-office clerk recovering a stuck login.

    Takes the existing Playwright session, types a password, signs in (or does
    not), then either resumes automation or lets the handoff time out.
    """

    def __init__(
        self,
        session: SessionManager,
        *,
        username: str,
        password: str,
        poll_seconds: float = 0.05,
        timeout_seconds: float = 45,
        mode: OperatorMode = OperatorMode.RECOVER,
        patients_timeout_ms: float = 15_000,
    ) -> None:
        self.session = session
        self.username = username
        self.password = password
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.mode = OperatorMode(mode)
        self.patients_timeout_ms = patients_timeout_ms
        self.recovered = False
        self.took_control = False
        self.resumed = False
        self.owner_trace: list[str] = []
        self.context_ids: list[int] = []

    def _note(self) -> None:
        self.owner_trace.append(self.session.owner.value)
        context = self.session.surface.context
        if context is not None:
            self.context_ids.append(id(context))

    async def recover_login(self) -> None:
        page = self.session.surface._require_page()
        password_box = page.get_by_role("textbox", name="Password")
        await password_box.fill(self.password)
        await page.get_by_role("button", name="Sign in").click()
        if self.mode == OperatorMode.RECOVER:
            await page.get_by_text("Patients").first.wait_for(
                state="visible", timeout=self.patients_timeout_ms
            )

    async def run(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            self._note()
            if self.session.owner != ControlOwner.PENDING_HUMAN:
                await asyncio.sleep(self.poll_seconds)
                continue
            if self.mode == OperatorMode.ABANDON:
                await asyncio.sleep(self.poll_seconds)
                continue
            await self.session.take_control()
            self.took_control = True
            self._note()
            await self.recover_login()
            await self.session.resume_automation()
            self.resumed = True
            self.recovered = self.mode == OperatorMode.RECOVER
            self._note()
            return
