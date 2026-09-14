"""Progress-based stopping heuristics for bounded discovery."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StuckDecision:
    stuck: bool
    reason: str | None = None


class StuckDetector:
    def __init__(
        self,
        *,
        repeated_action_limit: int = 3,
        unchanged_state_limit: int = 3,
    ) -> None:
        self.repeated_action_limit = repeated_action_limit
        self.unchanged_state_limit = unchanged_state_limit
        self.actions: deque[str] = deque(maxlen=repeated_action_limit)
        self.states: deque[str] = deque(maxlen=unchanged_state_limit + 1)

    def observe(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        state_fingerprint: str,
    ) -> StuckDecision:
        signature = json.dumps(
            {"name": tool_name, "input": tool_input},
            sort_keys=True,
            separators=(",", ":"),
        )
        self.actions.append(signature)
        self.states.append(state_fingerprint)
        if len(self.actions) == self.repeated_action_limit and len(set(self.actions)) == 1:
            return StuckDecision(True, "same action repeated without a new strategy")
        if len(self.states) == self.unchanged_state_limit + 1 and len(set(self.states)) == 1:
            return StuckDecision(True, "UI state did not change across repeated actions")
        return StuckDecision(False)
