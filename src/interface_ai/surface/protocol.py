"""Surface-neutral observation and action boundary."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class SurfaceActionKind(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    WAIT = "wait"
    EXTRACT = "extract"
    DISMISS_DIALOG = "dismiss_dialog"


class Viewport(BaseModel):
    width: int
    height: int


class FrameInfo(BaseModel):
    name: str | None
    url: str
    depth: int


class Observation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    title: str
    screenshot: bytes
    semantic_tree: list[dict[str, Any]]
    frames: list[FrameInfo]
    viewport: Viewport
    observed_at_monotonic: float
    state_fingerprint: str


class SurfaceAction(BaseModel):
    kind: SurfaceActionKind
    x: float | None = None
    y: float | None = None
    text: str | None = None
    url: str | None = None
    option: str | None = None
    wait_ms: int | None = Field(default=None, ge=0, le=30_000)


class ElementFingerprint(BaseModel):
    tag: str
    role: str | None
    accessible_name: str | None
    text: str | None
    label: str | None
    element_id: str | None
    classes: list[str]
    css_path: str | None
    xpath: str | None
    frame_url: str
    bounding_box: dict[str, float] | None


class ActionResult(BaseModel):
    success: bool
    message: str
    url_before: str
    url_after: str
    duration_ms: int
    extracted_value: str | None = None
    target_fingerprint: ElementFingerprint | None = None


@runtime_checkable
class SurfaceDriver(Protocol):
    async def start(self, *, start_url: str | None = None) -> None: ...

    async def observe(self) -> Observation: ...

    async def act(self, action: SurfaceAction) -> ActionResult: ...

    async def snapshot(self, path: Path) -> Path: ...

    async def close(self) -> None: ...
