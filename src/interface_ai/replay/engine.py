"""Deterministic artifact executor. This module intentionally has no LLM dependency."""

from __future__ import annotations

import asyncio
import random
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from interface_ai.artifact.schema import (
    ActionType,
    CapabilityArtifact,
    CapabilityStep,
    OutcomeClass,
    RecoveryAction,
    ValueType,
)
from interface_ai.replay.checkpoints import CheckpointResult, CheckpointVerifier
from interface_ai.replay.locator_resolver import (
    LocatorResolutionError,
    LocatorResolver,
    ResolvedTarget,
)
from interface_ai.replay.outcomes import OutcomeClassifier
from interface_ai.replay.result import FailureDetail, ReplayResult, ReplayStatus
from interface_ai.safety.policy import PolicyGate
from interface_ai.surface.web_playwright import PlaywrightWebSurface


class InputValidationError(ValueError):
    pass


class ReplayEngine:
    def __init__(
        self,
        surface: PlaywrightWebSurface,
        *,
        evidence_dir: Path | None = None,
        policy_gate: PolicyGate | None = None,
    ) -> None:
        self.surface = surface
        self.evidence_dir = evidence_dir
        self.policy_gate = policy_gate

    def _validate_inputs(
        self, artifact: CapabilityArtifact, supplied: dict[str, Any]
    ) -> dict[str, Any]:
        specs = {item.name: item for item in artifact.input_parameters}
        unknown = set(supplied) - set(specs)
        if unknown:
            raise InputValidationError(f"unknown inputs: {sorted(unknown)}")

        values: dict[str, Any] = {}
        for name, spec in specs.items():
            if name not in supplied:
                if spec.required:
                    raise InputValidationError(f"missing required input: {name}")
                values[name] = spec.default
                continue
            value = supplied[name]
            expected_type = ValueType(spec.type)
            valid = {
                ValueType.STRING: isinstance(value, str),
                ValueType.DATE: isinstance(value, str),
                ValueType.INTEGER: isinstance(value, int) and not isinstance(value, bool),
                ValueType.NUMBER: isinstance(value, (int, float)) and not isinstance(value, bool),
                ValueType.MONEY: isinstance(value, (int, float, Decimal))
                and not isinstance(value, bool),
                ValueType.BOOLEAN: isinstance(value, bool),
            }[expected_type]
            if not valid:
                raise InputValidationError(
                    f"{name} must be {expected_type.value}, observed {type(value).__name__}"
                )
            if spec.pattern and not re.fullmatch(spec.pattern, str(value)):
                raise InputValidationError(f"{name} does not match required pattern")
            values[name] = value
        return values

    async def _resolve(self, step: CapabilityStep, resolver: LocatorResolver) -> ResolvedTarget:
        return await resolver.resolve(step.locators)

    async def _perform_action(
        self,
        step: CapabilityStep,
        target: ResolvedTarget | None,
        values: dict[str, Any],
        credentials: dict[str, str],
    ) -> str | None:
        page = self.surface._require_page()
        action = ActionType(step.action)
        value: str | None = None
        if step.credential_ref:
            if step.credential_ref not in credentials:
                raise InputValidationError(
                    f"missing runtime credential reference: {step.credential_ref}"
                )
            value = credentials[step.credential_ref]
        elif step.value_template:
            value = step.value_template.format_map({key: str(item) for key, item in values.items()})

        if action == ActionType.NAVIGATE:
            if not value:
                raise ValueError("navigate step requires value_template")
            await page.goto(value, wait_until="domcontentloaded")
            return None
        if action == ActionType.WAIT:
            await page.wait_for_timeout(step.retry_policy.initial_delay_ms)
            return None
        if action == ActionType.DISMISS_DIALOG:
            raise RuntimeError("dialog dismissal requires an explicit observation handler")
        if target is None:
            raise ValueError(f"{action} requires a resolved target")

        if target.locator is not None:
            if action == ActionType.CLICK:
                await target.locator.click()
            elif action == ActionType.TYPE:
                assert value is not None
                await target.locator.fill(value)
            elif action == ActionType.SELECT:
                assert value is not None
                await target.locator.select_option(value)
            elif action == ActionType.EXTRACT:
                return (await target.locator.text_content() or "").strip()
            else:
                raise ValueError(f"unsupported locator action: {action}")
            return None

        assert target.coordinates is not None
        x, y = target.coordinates
        if action == ActionType.CLICK:
            await page.mouse.click(x, y)
        elif action == ActionType.TYPE:
            assert value is not None
            await page.mouse.click(x, y)
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.type(value)
        elif action == ActionType.EXTRACT:
            extracted: str = await page.evaluate(
                "([x, y]) => document.elementFromPoint(x, y)?.textContent?.trim() || ''",
                [x, y],
            )
            return extracted
        else:
            raise ValueError(f"coordinate fallback does not support {action}")
        return None

    async def _capture_failure(self, run_id: str, step_index: int | None, suffix: str) -> list[str]:
        if self.evidence_dir is None:
            return []
        if self.surface.page is None:
            return []
        filename = f"{run_id}-step-{step_index if step_index is not None else 'final'}-{suffix}.png"
        path = self.evidence_dir / filename
        await self.surface.snapshot(path)
        return [str(path)]

    async def _failure_result(
        self,
        *,
        run_id: str,
        artifact: CapabilityArtifact,
        started: float,
        status: ReplayStatus,
        completed_steps: int,
        step: CapabilityStep | None,
        step_index: int | None,
        code: str,
        expected: str,
        observed: str,
    ) -> ReplayResult:
        paths = await self._capture_failure(run_id, step_index, code.lower())
        return ReplayResult(
            run_id=run_id,
            capability_id=str(artifact.capability_id),
            capability_version=artifact.capability_version,
            status=status,
            completed_steps=completed_steps,
            duration_ms=int((time.monotonic() - started) * 1000),
            failure=FailureDetail(
                step_id=step.id if step else None,
                step_index=step_index,
                code=code,
                expected=expected,
                observed=observed,
                evidence_paths=paths,
            ),
        )

    async def _check_all(
        self,
        verifier: CheckpointVerifier,
        checkpoints: list[Any],
        values: dict[str, Any],
    ) -> CheckpointResult | None:
        for checkpoint in checkpoints:
            result = await verifier.verify(checkpoint, values)
            if not result.passed:
                return result
        return None

    async def _extract_outputs(
        self, artifact: CapabilityArtifact, resolver: LocatorResolver
    ) -> dict[str, Any]:
        outputs: dict[str, Any] = {}
        for spec in artifact.outputs:
            target = await resolver.resolve(spec.extraction.locators)
            if target.locator is None:
                raise LocatorResolutionError(
                    [f"output {spec.name} cannot use coordinate-only extraction"]
                )
            if spec.extraction.attribute == "text_content":
                raw = (await target.locator.text_content() or "").strip()
            else:
                raw = await target.locator.get_attribute(spec.extraction.attribute) or ""
            if spec.extraction.transform == "strip_currency":
                raw = re.sub(r"[^0-9.-]", "", raw)
            output_type = ValueType(spec.type)
            if output_type in {ValueType.STRING, ValueType.DATE}:
                outputs[spec.name] = raw
            elif output_type == ValueType.INTEGER:
                outputs[spec.name] = int(raw)
            elif output_type == ValueType.NUMBER:
                outputs[spec.name] = float(raw)
            elif output_type == ValueType.MONEY:
                outputs[spec.name] = str(Decimal(raw).quantize(Decimal("0.01")))
            elif output_type == ValueType.BOOLEAN:
                outputs[spec.name] = raw.lower() in {"true", "yes", "1"}
        return outputs

    async def run(
        self,
        artifact: CapabilityArtifact,
        parameters: dict[str, Any],
        *,
        credentials: dict[str, str] | None = None,
        keep_session_open: bool = False,
    ) -> ReplayResult:
        run_id = f"replay-{uuid4().hex[:12]}"
        started = time.monotonic()
        completed_steps = 0
        credentials = credentials or {}

        try:
            values = self._validate_inputs(artifact, parameters)
        except InputValidationError as exc:
            return await self._failure_result(
                run_id=run_id,
                artifact=artifact,
                started=started,
                status=ReplayStatus.HARD_FAILURE,
                completed_steps=0,
                step=None,
                step_index=None,
                code="INVALID_INPUT",
                expected="parameters matching the artifact input contract",
                observed=str(exc),
            )

        entry_url = artifact.target.entry_url_template.format_map(
            {key: str(value) for key, value in values.items()}
        )
        if self.policy_gate:
            entry_verdict = self.policy_gate.check_url(entry_url)
            if not entry_verdict.allowed:
                return await self._failure_result(
                    run_id=run_id,
                    artifact=artifact,
                    started=started,
                    status=ReplayStatus.HARD_FAILURE,
                    completed_steps=0,
                    step=None,
                    step_index=None,
                    code=entry_verdict.code,
                    expected="allowlisted entry URL",
                    observed=entry_verdict.reason,
                )
        owns_session = self.surface.page is None
        if owns_session:
            await self.surface.start(start_url=entry_url)
        page = self.surface._require_page()
        resolver = LocatorResolver(page)
        verifier = CheckpointVerifier(page, resolver)
        classifier = OutcomeClassifier(verifier)

        try:
            for index, step in enumerate(artifact.steps):
                failed_precondition = await self._check_all(verifier, step.preconditions, values)
                if failed_precondition:
                    return await self._failure_result(
                        run_id=run_id,
                        artifact=artifact,
                        started=started,
                        status=ReplayStatus.HARD_FAILURE,
                        completed_steps=completed_steps,
                        step=step,
                        step_index=index,
                        code="PRECONDITION_FAILED",
                        expected=failed_precondition.expected,
                        observed=failed_precondition.observed,
                    )

                policy = step.retry_policy
                max_attempts = max(
                    [policy.max_attempts]
                    + [
                        rule.retry_policy.max_attempts
                        for rule in step.observation_rules
                        if rule.retry_policy is not None
                    ]
                )
                rng = random.Random(f"{run_id}:{step.id}")  # noqa: S311 - retry jitter only
                last_error = "action did not run"
                for attempt in range(1, max_attempts + 1):
                    try:
                        if self.policy_gate:
                            navigation_url = None
                            if (
                                ActionType(step.action) == ActionType.NAVIGATE
                                and step.value_template
                            ):
                                navigation_url = step.value_template.format_map(
                                    {key: str(item) for key, item in values.items()}
                                )
                            verdict = self.policy_gate.check_step(
                                step,
                                current_url=page.url,
                                navigation_url=navigation_url,
                            )
                            if not verdict.allowed:
                                return await self._failure_result(
                                    run_id=run_id,
                                    artifact=artifact,
                                    started=started,
                                    status=ReplayStatus.HARD_FAILURE,
                                    completed_steps=completed_steps,
                                    step=step,
                                    step_index=index,
                                    code=verdict.code,
                                    expected="policy-allowed action",
                                    observed=verdict.reason,
                                )
                            if verdict.requires_human_approval:
                                return await self._failure_result(
                                    run_id=run_id,
                                    artifact=artifact,
                                    started=started,
                                    status=ReplayStatus.INTERVENTION_REQUIRED,
                                    completed_steps=completed_steps,
                                    step=step,
                                    step_index=index,
                                    code=verdict.code,
                                    expected="human approval before execution",
                                    observed=verdict.reason,
                                )
                        target = await self._resolve(step, resolver) if step.locators else None
                        await self._perform_action(step, target, values, credentials)
                        classified = await classifier.classify(step.observation_rules, values)
                        if classified:
                            if classified.classification == OutcomeClass.BUSINESS:
                                return ReplayResult(
                                    run_id=run_id,
                                    capability_id=str(artifact.capability_id),
                                    capability_version=artifact.capability_version,
                                    status=ReplayStatus.BUSINESS_OUTCOME,
                                    outcome_code=classified.code,
                                    outcome_message=classified.description,
                                    completed_steps=completed_steps,
                                    duration_ms=int((time.monotonic() - started) * 1000),
                                )
                            if classified.classification == OutcomeClass.HARD_FAILURE:
                                return await self._failure_result(
                                    run_id=run_id,
                                    artifact=artifact,
                                    started=started,
                                    status=ReplayStatus.HARD_FAILURE,
                                    completed_steps=completed_steps,
                                    step=step,
                                    step_index=index,
                                    code=classified.code,
                                    expected="declared successful step state",
                                    observed=classified.description,
                                )
                            last_error = f"{classified.code}: {classified.description}"
                            if classified.recovery in {
                                RecoveryAction.ESCALATE,
                                RecoveryAction.REAUTHENTICATE,
                            }:
                                return await self._failure_result(
                                    run_id=run_id,
                                    artifact=artifact,
                                    started=started,
                                    status=ReplayStatus.INTERVENTION_REQUIRED,
                                    completed_steps=completed_steps,
                                    step=step,
                                    step_index=index,
                                    code=classified.code,
                                    expected="operator recovery",
                                    observed=classified.description,
                                )
                            if classified.recovery == RecoveryAction.DISMISS:
                                assert classified.rule.recovery_locator is not None
                                recovery_target = await resolver.resolve(
                                    [classified.rule.recovery_locator]
                                )
                                if recovery_target.locator is None:
                                    raise RuntimeError("dismiss recovery cannot use coordinates")
                                await recovery_target.locator.click()
                            elif classified.recovery in {
                                RecoveryAction.WAIT,
                                RecoveryAction.RETRY,
                            }:
                                await page.wait_for_timeout(classified.rule.wait_ms)
                            if attempt < max_attempts:
                                continue
                            return await self._failure_result(
                                run_id=run_id,
                                artifact=artifact,
                                started=started,
                                status=ReplayStatus.RECOVERABLE_EXHAUSTED,
                                completed_steps=completed_steps,
                                step=step,
                                step_index=index,
                                code=classified.code,
                                expected="recoverable condition to clear",
                                observed=classified.description,
                            )

                        failed_postcondition = await self._check_all(
                            verifier, step.postconditions, values
                        )
                        if failed_postcondition:
                            last_error = (
                                f"expected {failed_postcondition.expected}; "
                                f"observed {failed_postcondition.observed}"
                            )
                            raise RuntimeError(last_error)
                        completed_steps += 1
                        break
                    except Exception as exc:
                        last_error = f"{type(exc).__name__}: {exc}"
                        if attempt >= max_attempts:
                            return await self._failure_result(
                                run_id=run_id,
                                artifact=artifact,
                                started=started,
                                status=ReplayStatus.HARD_FAILURE,
                                completed_steps=completed_steps,
                                step=step,
                                step_index=index,
                                code="STEP_FAILED",
                                expected=step.description,
                                observed=last_error,
                            )
                        delay = policy.initial_delay_ms * (
                            policy.backoff_multiplier ** (attempt - 1)
                        )
                        jitter = 1 + rng.uniform(-policy.jitter_ratio, policy.jitter_ratio)
                        await asyncio.sleep(delay * jitter / 1000)

            final = await verifier.verify(artifact.success_checkpoint, values)
            if not final.passed:
                return await self._failure_result(
                    run_id=run_id,
                    artifact=artifact,
                    started=started,
                    status=ReplayStatus.HARD_FAILURE,
                    completed_steps=completed_steps,
                    step=None,
                    step_index=None,
                    code="SUCCESS_CHECKPOINT_FAILED",
                    expected=final.expected,
                    observed=final.observed,
                )
            try:
                outputs = await self._extract_outputs(artifact, resolver)
            except Exception as exc:
                return await self._failure_result(
                    run_id=run_id,
                    artifact=artifact,
                    started=started,
                    status=ReplayStatus.HARD_FAILURE,
                    completed_steps=completed_steps,
                    step=None,
                    step_index=None,
                    code="OUTPUT_EXTRACTION_FAILED",
                    expected="all declared outputs",
                    observed=f"{type(exc).__name__}: {exc}",
                )
            return ReplayResult(
                run_id=run_id,
                capability_id=str(artifact.capability_id),
                capability_version=artifact.capability_version,
                status=ReplayStatus.SUCCESS,
                outputs=outputs,
                completed_steps=completed_steps,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            if owns_session and not keep_session_open:
                await self.surface.close()
