"""Computer surface adapters."""

from interface_ai.surface.protocol import SurfaceDriver
from interface_ai.surface.web_playwright import PlaywrightWebSurface

__all__ = ["PlaywrightWebSurface", "SurfaceDriver"]
