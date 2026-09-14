"""Convert a successfully targeted pixel into ranked replay locators."""

from __future__ import annotations

from interface_ai.artifact.schema import (
    CoordinatePoint,
    LocatorKind,
    LocatorStrategy,
)
from interface_ai.surface.protocol import ElementFingerprint, Viewport

NATIVE_ROLES = {
    "a": "link",
    "button": "button",
    "input": "textbox",
    "select": "combobox",
    "textarea": "textbox",
}


class LocatorHarvester:
    def harvest(
        self,
        fingerprint: ElementFingerprint,
        *,
        viewport: Viewport,
        click_coordinate: tuple[float, float] | None = None,
        extraction_only: bool = False,
    ) -> list[LocatorStrategy]:
        candidates: list[LocatorStrategy] = []
        rank = 1
        role = fingerprint.role or NATIVE_ROLES.get(fingerprint.tag)
        if not extraction_only and role and fingerprint.accessible_name:
            candidates.append(
                LocatorStrategy(
                    kind=LocatorKind.ROLE_NAME,
                    rank=rank,
                    role=role,
                    name=fingerprint.accessible_name,
                    reasoning="Accessible role and name survived visual discovery",
                )
            )
            rank += 1
        if not extraction_only and fingerprint.label:
            candidates.append(
                LocatorStrategy(
                    kind=LocatorKind.LABEL,
                    rank=rank,
                    value=fingerprint.label,
                    reasoning="Associated visible label is stable across layout changes",
                )
            )
            rank += 1
        if not extraction_only and fingerprint.text and len(fingerprint.text) <= 120:
            candidates.append(
                LocatorStrategy(
                    kind=LocatorKind.TEXT,
                    rank=rank,
                    value=fingerprint.text,
                    reasoning="Visible text is a human-recognizable fallback",
                )
            )
            rank += 1
        if fingerprint.css_path:
            candidates.append(
                LocatorStrategy(
                    kind=LocatorKind.CSS,
                    rank=rank,
                    value=fingerprint.css_path,
                    reasoning=(
                        "Captured structural path; weaker than semantics and expected to drift"
                    ),
                )
            )
            rank += 1
        if fingerprint.xpath:
            candidates.append(
                LocatorStrategy(
                    kind=LocatorKind.XPATH,
                    rank=rank,
                    value=fingerprint.xpath,
                    reasoning="Absolute structural fallback for non-semantic legacy markup",
                )
            )
            rank += 1
        if not extraction_only and click_coordinate:
            x, y = click_coordinate
            candidates.append(
                LocatorStrategy(
                    kind=LocatorKind.COORDINATES,
                    rank=99,
                    coordinates=CoordinatePoint(
                        x_ratio=x / viewport.width,
                        y_ratio=y / viewport.height,
                        recorded_viewport_width=viewport.width,
                        recorded_viewport_height=viewport.height,
                    ),
                    reasoning="Last resort normalized visual coordinate from successful action",
                )
            )
        return candidates
