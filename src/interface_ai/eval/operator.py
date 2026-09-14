"""Simulated operator for eval: same live session, never a new browser."""

from __future__ import annotations

import asyncio
import time

from interface_ai.core.session import ControlOwner, SessionManager


class SimulatedClaimsOperator:
    """Stand-in for a back-office clerk recovering a stuck login.

    Takes the existing Playwright session, types the runtime password, signs in,
    then resumes automation so replay can re-verify checkpoints.
    """

    def __init__(
        self,
        session: SessionManager,
        *,
        username: str,
        password: str,
        poll_seconds: float = 0.05,
        timeout_seconds: float = 45,
    ) -> None:
        self.session = session
        self.username = username
        self.password = password
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.recovered = False

    async def recover_login(self) -> None:
        page = self.session.surface._require_page()
        password_box = page.get_by_role("textbox", name="Password")
        await password_box.fill(self.password)
        await page.get_by_role("button", name="Sign in").click()
        await page.get_by_text("Patients").first.wait_for(state="visible", timeout=15_000)

    async def run(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if self.session.owner == ControlOwner.PENDING_HUMAN:
                await self.session.take_control()
                await self.recover_login()
                await self.session.resume_automation()
                self.recovered = True
                return
            await asyncio.sleep(self.poll_seconds)
