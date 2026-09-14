"""Ranked, unique-match locator resolution for web replay."""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Frame, Locator, Page

from interface_ai.artifact.schema import LocatorKind, LocatorStrategy


class LocatorResolutionError(LookupError):
    def __init__(self, attempts: list[str]) -> None:
        self.attempts = attempts
        super().__init__("; ".join(attempts))


@dataclass(frozen=True)
class ResolvedTarget:
    strategy: LocatorStrategy
    locator: Locator | None = None
    coordinates: tuple[float, float] | None = None


class LocatorResolver:
    def __init__(self, page: Page) -> None:
        self.page = page

    def _root_for(self, strategy: LocatorStrategy) -> Page | Frame:
        if not strategy.frame_path:
            return self.page
        current: Page | Frame = self.page
        for frame_hint in strategy.frame_path:
            candidates = [
                frame
                for frame in self.page.frames
                if frame.name == frame_hint or frame.url == frame_hint
            ]
            if len(candidates) != 1:
                raise LocatorResolutionError(
                    [f"frame '{frame_hint}' matched {len(candidates)} frames"]
                )
            current = candidates[0]
        return current

    def _build_locator(self, root: Page | Frame, strategy: LocatorStrategy) -> Locator:
        kind = LocatorKind(strategy.kind)
        if kind == LocatorKind.ROLE_NAME:
            assert strategy.role and strategy.name
            # The artifact supports surface-neutral role strings; Playwright narrows its
            # annotation to browser ARIA literals while runtime validation remains its job.
            return root.get_by_role(
                strategy.role,  # type: ignore[arg-type]
                name=strategy.name,
                exact=True,
            )
        if kind == LocatorKind.LABEL:
            assert strategy.value
            return root.get_by_label(strategy.value, exact=True)
        if kind == LocatorKind.TEXT:
            assert strategy.value
            locator = root.get_by_text(strategy.value, exact=True)
            if strategy.anchor_text:
                locator = root.get_by_text(strategy.anchor_text, exact=False).locator(
                    f".. >> text={strategy.value}"
                )
            return locator
        if kind == LocatorKind.CSS:
            assert strategy.value
            return root.locator(strategy.value)
        if kind == LocatorKind.XPATH:
            assert strategy.value
            value = strategy.value
            return root.locator(value if value.startswith("xpath=") else f"xpath={value}")
        raise ValueError(f"{kind} does not produce a Playwright locator")

    async def resolve(self, strategies: list[LocatorStrategy]) -> ResolvedTarget:
        attempts: list[str] = []
        for strategy in sorted(strategies, key=lambda item: item.rank):
            kind = LocatorKind(strategy.kind)
            if kind == LocatorKind.COORDINATES:
                assert strategy.coordinates
                viewport = self.page.viewport_size
                if not viewport:
                    attempts.append(f"rank {strategy.rank} coordinates: viewport unavailable")
                    continue
                return ResolvedTarget(
                    strategy=strategy,
                    coordinates=(
                        strategy.coordinates.x_ratio * viewport["width"],
                        strategy.coordinates.y_ratio * viewport["height"],
                    ),
                )
            try:
                root = self._root_for(strategy)
                locator = self._build_locator(root, strategy)
                count = await locator.count()
                if count != 1:
                    attempts.append(
                        f"rank {strategy.rank} {kind.value}: expected 1 match, observed {count}"
                    )
                    continue
                return ResolvedTarget(strategy=strategy, locator=locator)
            except LocatorResolutionError as exc:
                attempts.extend(exc.attempts)
            except Exception as exc:
                attempts.append(f"rank {strategy.rank} {kind.value}: {type(exc).__name__}: {exc}")
        raise LocatorResolutionError(attempts or ["no locator strategies supplied"])
