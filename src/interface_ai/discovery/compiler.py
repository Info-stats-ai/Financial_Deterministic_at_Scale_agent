"""Compile a successful model-driven run into a reviewable capability artifact."""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from interface_ai.artifact.schema import (
    ActionType,
    ArtifactMetadata,
    CapabilityArtifact,
    CapabilityStep,
    Checkpoint,
    CheckpointKind,
    CredentialReference,
    ExtractionSpec,
    OutputSpec,
    ParameterSpec,
    RiskClass,
    SurfaceKind,
    TargetSpec,
    ValueType,
)
from interface_ai.discovery.harvester import LocatorHarvester
from interface_ai.discovery.models import CompletionPayload, RecordedAction
from interface_ai.surface.protocol import Viewport
from interface_ai.surface.web_playwright import PlaywrightWebSurface

RISKY_TEXT = re.compile(r"(?i)\b(submit|finalize|confirm|pay|transfer|delete)\b")


class CompilationError(ValueError):
    pass


class ArtifactCompiler:
    def __init__(self, surface: PlaywrightWebSurface) -> None:
        self.surface = surface
        self.harvester = LocatorHarvester()

    def _binding_for_text(
        self,
        text: str,
        parameters: dict[str, str],
        credentials: dict[str, str],
    ) -> tuple[str | None, str | None]:
        for name, value in parameters.items():
            if text == value:
                return f"{{{name}}}", None
        for name, value in credentials.items():
            if text == value:
                return None, name
        raise CompilationError(
            "typed text was neither a declared parameter nor credential reference"
        )

    async def _output_extraction(
        self, name: str, visible_value: str, viewport: Viewport
    ) -> OutputSpec:
        page = self.surface._require_page()
        locator = page.get_by_text(visible_value, exact=True)
        count = await locator.count()
        if count != 1:
            raise CompilationError(
                f"output {name!r} value matched {count} elements; extraction is ambiguous"
            )
        box = await locator.bounding_box()
        if not box:
            raise CompilationError(f"output {name!r} has no visible bounding box")
        fingerprint = await self.surface._fingerprint_at(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
        )
        if fingerprint is None:
            raise CompilationError(f"could not fingerprint output {name!r}")
        locators = self.harvester.harvest(fingerprint, viewport=viewport, extraction_only=True)
        if not locators:
            raise CompilationError(f"could not create a safe output locator for {name!r}")
        return OutputSpec(
            name=name,
            type=ValueType.STRING,
            description=f"Value of {name.replace('_', ' ')} visible after success",
            extraction=ExtractionSpec(locators=locators),
        )

    async def compile(
        self,
        *,
        run_id: str,
        goal: str,
        target_url: str,
        capability_name: str,
        parameters: dict[str, str],
        credentials: dict[str, str],
        actions: list[RecordedAction],
        completion: CompletionPayload,
    ) -> CapabilityArtifact:
        observation = await self.surface.observe()
        actionable = [
            item
            for item in actions
            if item.success
            and item.tool_name in {"left_click", "double_click", "triple_click", "type"}
        ]
        steps: list[CapabilityStep] = []
        index = 0
        while index < len(actionable):
            current = actionable[index]
            if current.tool_name in {"left_click", "double_click", "triple_click"}:
                if current.target is None:
                    raise CompilationError("successful click had no target fingerprint")
                coordinate = current.tool_input.get("coordinate")
                click_coordinate = (
                    (float(coordinate[0]), float(coordinate[1]))
                    if isinstance(coordinate, list) and len(coordinate) == 2
                    else None
                )
                locators = self.harvester.harvest(
                    current.target,
                    viewport=observation.viewport,
                    click_coordinate=click_coordinate,
                )
                next_action = actionable[index + 1] if index + 1 < len(actionable) else None
                if next_action and next_action.tool_name == "type":
                    text = str(next_action.tool_input.get("text", ""))
                    value_template, credential_ref = self._binding_for_text(
                        text, parameters, credentials
                    )
                    steps.append(
                        CapabilityStep(
                            id=f"step-{len(steps) + 1:02d}-type",
                            description=(
                                f"Type into {current.target.accessible_name or current.target.tag}"
                            ),
                            action=ActionType.TYPE,
                            locators=locators,
                            value_template=value_template,
                            credential_ref=credential_ref,
                            risk_class=RiskClass.SAFE,
                        )
                    )
                    index += 2
                    continue

                target_name = (
                    current.target.accessible_name or current.target.text or current.target.tag
                )
                description = f"Click {target_name}"
                risk = RiskClass.IRREVERSIBLE if RISKY_TEXT.search(description) else RiskClass.SAFE
                steps.append(
                    CapabilityStep(
                        id=f"step-{len(steps) + 1:02d}-click",
                        description=description,
                        action=ActionType.CLICK,
                        locators=locators,
                        risk_class=risk,
                    )
                )
            elif current.tool_name == "type":
                raise CompilationError("type action had no preceding target click")
            index += 1

        if not steps:
            raise CompilationError("discovery produced no replayable actions")

        outputs = [
            await self._output_extraction(name, value, observation.viewport)
            for name, value in completion.outputs.items()
        ]
        parsed = urlsplit(target_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return CapabilityArtifact(
            capability_version="1.0.0",
            capability_id=uuid5(NAMESPACE_URL, f"{origin}:{capability_name}"),
            name=capability_name,
            description=goal,
            target=TargetSpec(
                app_id="cloudcruise-healthcare",
                vendor_product="CloudCruise XPath Cascade Healthcare",
                surface=SurfaceKind.WEB,
                entry_url_template=target_url,
                allowed_origin=origin,
                product_version="1",
            ),
            input_parameters=[
                ParameterSpec(
                    name=name,
                    type=ValueType.STRING,
                    description=f"Caller-supplied {name.replace('_', ' ')}",
                    examples=[],
                    sensitive="member" in name or "patient" in name,
                )
                for name in parameters
            ],
            credential_references=[
                CredentialReference(
                    name=name,
                    purpose=f"Runtime credential for {name.lower().replace('_', ' ')}",
                )
                for name in credentials
            ],
            outputs=outputs,
            steps=steps,
            success_checkpoint=Checkpoint(
                kind=CheckpointKind.TEXT_VISIBLE,
                description="Model-observed final UI state remains visible",
                expected=completion.final_checkpoint_text,
            ),
            metadata=ArtifactMetadata(
                source_run_id=run_id,
                tags=["live-discovery", "public-demo", "read-only"],
            ),
        ).with_content_hash()
