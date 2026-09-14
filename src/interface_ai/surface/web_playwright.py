"""Playwright implementation of the surface-neutral computer interface."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Dialog,
    Page,
    Playwright,
    async_playwright,
)

from interface_ai.surface.protocol import (
    ActionResult,
    ElementFingerprint,
    FrameInfo,
    Observation,
    SurfaceAction,
    SurfaceActionKind,
    Viewport,
)

SEMANTIC_SNAPSHOT_JS = """
() => {
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none'
      && rect.width > 0 && rect.height > 0;
  };
  const selectors = [
    'button', 'a', 'input', 'select', 'textarea', '[role]',
    'h1', 'h2', 'h3', 'label', 'table', '[aria-label]'
  ].join(',');
  return [...document.querySelectorAll(selectors)]
    .filter(visible)
    .slice(0, 500)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const label = el.labels?.[0]?.innerText
        || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText)
        || null;
      return {
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || null,
        name: el.getAttribute('aria-label') || label
          || el.getAttribute('placeholder') || el.innerText?.trim().slice(0, 160) || null,
        text: el.innerText?.trim().slice(0, 240) || null,
        type: el.getAttribute('type') || null,
        value_state: 'value' in el ? (el.value ? 'set' : 'empty') : null,
        disabled: Boolean(el.disabled),
        box: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
      };
    });
}
"""

FINGERPRINT_AT_POINT_JS = """
([x, y]) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  const label = el.labels?.[0]?.innerText
    || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText)
    || null;
  const cssPath = (node) => {
    const parts = [];
    while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
      let part = node.tagName.toLowerCase();
      if (node.id) {
        part += `#${CSS.escape(node.id)}`;
        parts.unshift(part);
        break;
      }
      const siblings = [...node.parentElement?.children || []]
        .filter(sibling => sibling.tagName === node.tagName);
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const xpath = (node) => {
    const parts = [];
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      let index = 1;
      let sibling = node.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === node.tagName) index += 1;
        sibling = sibling.previousElementSibling;
      }
      parts.unshift(`${node.tagName.toLowerCase()}[${index}]`);
      node = node.parentElement;
    }
    return '/' + parts.join('/');
  };
  return {
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role'),
    accessible_name: el.getAttribute('aria-label') || label
      || el.innerText?.trim().slice(0, 160) || null,
    text: el.innerText?.trim().slice(0, 240) || null,
    label,
    element_id: el.id || null,
    classes: [...el.classList],
    css_path: cssPath(el),
    xpath: xpath(el),
    frame_url: location.href,
    bounding_box: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
  };
}
"""


class PlaywrightWebSurface:
    def __init__(
        self,
        *,
        headless: bool = False,
        viewport: tuple[int, int] = (1440, 900),
        har_path: Path | None = None,
    ) -> None:
        self.headless = headless
        self.viewport = viewport
        self.har_path = har_path
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._dialogs: asyncio.Queue[Dialog] = asyncio.Queue()

    async def start(self, *, start_url: str | None = None) -> None:
        if self.page is not None:
            raise RuntimeError("surface already started")
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=self.headless)
        context_options: dict[str, Any] = {
            "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
        }
        if self.har_path:
            self.har_path.parent.mkdir(parents=True, exist_ok=True)
            context_options.update(
                record_har_path=str(self.har_path),
                record_har_mode="minimal",
                record_har_content="embed",
            )
        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()
        self.page.on("dialog", self._dialogs.put_nowait)
        if start_url:
            await self.page.goto(start_url, wait_until="domcontentloaded")

    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("surface has not been started")
        return self.page

    async def observe(self) -> Observation:
        page = self._require_page()
        screenshot = await page.screenshot(type="png")
        semantic_tree: list[dict[str, Any]] = []
        frames: list[FrameInfo] = []
        for frame in page.frames:
            depth = 0
            parent = frame.parent_frame
            while parent is not None:
                depth += 1
                parent = parent.parent_frame
            frames.append(FrameInfo(name=frame.name or None, url=frame.url, depth=depth))
            try:
                nodes = await frame.evaluate(SEMANTIC_SNAPSHOT_JS)
                for node in nodes:
                    node["frame_url"] = frame.url
                    node["frame_depth"] = depth
                semantic_tree.extend(nodes)
            except Exception:
                # Cross-origin, detached, and navigating frames remain visible in frame metadata.
                continue

        viewport = page.viewport_size or {"width": self.viewport[0], "height": self.viewport[1]}
        title = await page.title()
        state_data = json.dumps(
            {"url": page.url, "title": title, "tree": semantic_tree},
            sort_keys=True,
            default=str,
        ).encode()
        return Observation(
            url=page.url,
            title=title,
            screenshot=screenshot,
            semantic_tree=semantic_tree,
            frames=frames,
            viewport=Viewport(**viewport),
            observed_at_monotonic=time.monotonic(),
            state_fingerprint=hashlib.sha256(state_data).hexdigest(),
        )

    async def _fingerprint_at(self, x: float, y: float) -> ElementFingerprint | None:
        payload = await self._require_page().evaluate(FINGERPRINT_AT_POINT_JS, [x, y])
        return ElementFingerprint.model_validate(payload) if payload else None

    async def act(self, action: SurfaceAction) -> ActionResult:
        page = self._require_page()
        started = time.monotonic()
        url_before = page.url
        fingerprint: ElementFingerprint | None = None
        extracted: str | None = None

        try:
            if action.kind == SurfaceActionKind.NAVIGATE:
                if not action.url:
                    raise ValueError("navigate requires url")
                await page.goto(action.url, wait_until="domcontentloaded")
            elif action.kind == SurfaceActionKind.WAIT:
                await page.wait_for_timeout(action.wait_ms or 250)
            elif action.kind == SurfaceActionKind.DISMISS_DIALOG:
                dialog = self._dialogs.get_nowait()
                await dialog.dismiss()
            else:
                if action.x is None or action.y is None:
                    raise ValueError(f"{action.kind} requires x and y coordinates")
                fingerprint = await self._fingerprint_at(action.x, action.y)
                if action.kind == SurfaceActionKind.CLICK:
                    await page.mouse.click(action.x, action.y)
                elif action.kind == SurfaceActionKind.TYPE:
                    if action.text is None:
                        raise ValueError("type requires text")
                    await page.mouse.click(action.x, action.y)
                    await page.keyboard.press("ControlOrMeta+A")
                    await page.keyboard.type(action.text)
                elif action.kind == SurfaceActionKind.SELECT:
                    if action.option is None:
                        raise ValueError("select requires option")
                    handle = await page.evaluate_handle(
                        "([x, y]) => document.elementFromPoint(x, y)", [action.x, action.y]
                    )
                    element = handle.as_element()
                    if element is None:
                        raise ValueError("no selectable element found at coordinates")
                    await element.select_option(action.option)
                elif action.kind == SurfaceActionKind.EXTRACT:
                    extracted = await page.evaluate(
                        "([x, y]) => document.elementFromPoint(x, y)?.textContent?.trim() || null",
                        [action.x, action.y],
                    )
                else:
                    raise ValueError(f"unsupported action: {action.kind}")
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"{type(exc).__name__}: {exc}",
                url_before=url_before,
                url_after=page.url,
                duration_ms=int((time.monotonic() - started) * 1000),
                target_fingerprint=fingerprint,
            )

        return ActionResult(
            success=True,
            message="action completed",
            url_before=url_before,
            url_after=page.url,
            duration_ms=int((time.monotonic() - started) * 1000),
            extracted_value=extracted,
            target_fingerprint=fingerprint,
        )

    async def snapshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._require_page().screenshot(path=str(path), full_page=True)
        return path

    async def close(self) -> None:
        if self.context:
            await self.context.close()  # Closing the context flushes HAR to disk.
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        self.page = None
        self.context = None
        self.browser = None
        self._playwright = None
