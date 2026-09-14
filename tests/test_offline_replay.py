from pathlib import Path

from interface_ai.demo_artifact import build_demo_artifact
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayStatus
from interface_ai.surface.web_playwright import PlaywrightWebSurface


async def test_golden_artifact_replays_with_network_blocked() -> None:
    har = Path("evidence/fixtures/cloudcruise-healthcare.har")
    assert har.exists(), "committed offline fixture is required"
    surface = PlaywrightWebSurface(headless=True, replay_har_path=har)

    result = await ReplayEngine(surface).run(
        build_demo_artifact(),
        {"member_id": "MRN-10042"},
        credentials={
            "DEMO_USERNAME": "provider",
            "DEMO_PASSWORD": "claims123",
        },
    )

    assert result.status == ReplayStatus.SUCCESS
    assert result.completed_steps == 6
    assert result.outputs
    assert result.outputs["patient_status"] == "Active"
