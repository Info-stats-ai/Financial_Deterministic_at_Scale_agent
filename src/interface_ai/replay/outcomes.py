"""Deterministic classification of runtime UI states."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from interface_ai.artifact.schema import ObservationRule, OutcomeClass, RecoveryAction
from interface_ai.replay.checkpoints import CheckpointVerifier


@dataclass(frozen=True)
class ClassifiedOutcome:
    code: str
    classification: OutcomeClass
    description: str
    recovery: RecoveryAction
    rule: ObservationRule


class OutcomeClassifier:
    def __init__(self, verifier: CheckpointVerifier) -> None:
        self.verifier = verifier

    async def classify(
        self, rules: list[ObservationRule], values: dict[str, Any]
    ) -> ClassifiedOutcome | None:
        """Return the first explicitly declared matching state, never infer semantics."""

        for rule in rules:
            result = await self.verifier.verify(rule.when, values)
            if result.passed:
                return ClassifiedOutcome(
                    code=rule.code,
                    classification=OutcomeClass(rule.classification),
                    description=rule.description,
                    recovery=RecoveryAction(rule.recovery),
                    rule=rule,
                )
        return None
