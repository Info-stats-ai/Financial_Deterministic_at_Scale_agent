"""Condition-based checkpoint verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Page

from interface_ai.artifact.schema import Checkpoint, CheckpointKind
from interface_ai.replay.locator_resolver import LocatorResolutionError, LocatorResolver


def render_template(value: str | bool, values: dict[str, Any]) -> str | bool:
    if not isinstance(value, str):
        return value
    return value.format_map({key: str(item) for key, item in values.items()})


@dataclass(frozen=True)
class CheckpointResult:
    passed: bool
    expected: str
    observed: str


class CheckpointVerifier:
    def __init__(self, page: Page, resolver: LocatorResolver) -> None:
        self.page = page
        self.resolver = resolver

    async def verify(
        self, checkpoint: Checkpoint, values: dict[str, Any]
    ) -> CheckpointResult:
        expected = render_template(checkpoint.expected, values)
        kind = CheckpointKind(checkpoint.kind)
        try:
            if kind == CheckpointKind.URL_MATCHES:
                passed = bool(re.search(str(expected), self.page.url))
                return CheckpointResult(passed, str(expected), self.page.url)

            if kind == CheckpointKind.TEXT_VISIBLE:
                locator = self.page.get_by_text(str(expected), exact=False)
                await locator.first.wait_for(state="visible", timeout=checkpoint.timeout_ms)
                count = await locator.count()
                return CheckpointResult(
                    True, f"visible text containing {expected!r}", f"{count} text matches"
                )

            assert checkpoint.locator is not None
            try:
                target = await self.resolver.resolve([checkpoint.locator])
            except LocatorResolutionError as exc:
                if kind == CheckpointKind.ELEMENT_ABSENT:
                    return CheckpointResult(True, "element absent", str(exc))
                return CheckpointResult(False, str(expected), str(exc))

            if target.locator is None:
                return CheckpointResult(
                    False,
                    str(expected),
                    "coordinate locators cannot verify semantic checkpoints",
                )

            if kind == CheckpointKind.ELEMENT_VISIBLE:
                visible = await target.locator.is_visible(timeout=checkpoint.timeout_ms)
                return CheckpointResult(visible, "element visible", f"visible={visible}")
            if kind == CheckpointKind.ELEMENT_ABSENT:
                visible = await target.locator.is_visible(timeout=checkpoint.timeout_ms)
                return CheckpointResult(not visible, "element absent", f"visible={visible}")
            if kind == CheckpointKind.VALUE_MATCHES:
                value = await target.locator.input_value(timeout=checkpoint.timeout_ms)
                return CheckpointResult(value == str(expected), str(expected), value)
        except Exception as exc:
            return CheckpointResult(False, str(expected), f"{type(exc).__name__}: {exc}")

        return CheckpointResult(False, str(expected), f"unsupported checkpoint kind: {kind}")
