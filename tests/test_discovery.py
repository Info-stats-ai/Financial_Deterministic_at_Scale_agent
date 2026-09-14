from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import quote

from interface_ai.artifact.schema import ActionType
from interface_ai.discovery.loop import DiscoveryLoop
from interface_ai.discovery.models import DiscoveryStatus, ModelTurn, ToolCall
from interface_ai.discovery.stuck import StuckDetector
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.safety.policy import (
    ActionPolicy,
    NetworkPolicy,
    PolicyConfig,
    PolicyGate,
    RedactionPolicy,
)
from interface_ai.safety.redaction import Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface


class FakeComputerClient:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = deque(turns)

    async def next_turn(self, *, system: str, messages: list[dict[str, Any]]) -> ModelTurn:
        assert "complete_capability" in system
        assert messages
        return self.turns.popleft()


def call(identifier: str, name: str, payload: dict[str, Any], *, computer: bool = True) -> ToolCall:
    return ToolCall(
        id=identifier,
        name=name,
        input=payload,
        toolset_name="computer" if computer else None,
    )


def turn(calls: list[ToolCall]) -> ModelTurn:
    raw = [
        {
            "type": "tool_use",
            "id": item.id,
            "name": item.name,
            "input": item.input,
            **({"toolset_name": "computer"} if item.toolset_name else {}),
        }
        for item in calls
    ]
    return ModelTurn(raw_content=raw, tool_calls=calls, stop_reason="tool_use")


def fixed_demo_url() -> str:
    html = """
    <html><body><main id="app">
      <input aria-label="Provider ID" style="position:fixed;left:100px;top:100px;width:200px;height:30px">
      <input aria-label="Password" type="password" style="position:fixed;left:100px;top:150px;width:200px;height:30px">
      <button onclick="login()" style="position:fixed;left:100px;top:200px;width:100px;height:40px">Sign in</button>
    </main><script>
      function login() {
        app.innerHTML = `<h1>Patients</h1>
          <input aria-label="Search patients" style="position:fixed;left:100px;top:100px;width:200px;height:30px">
          <button onclick="search()" style="position:fixed;left:100px;top:150px;width:100px;height:30px">Search</button>
          <section id="results"></section>`;
      }
      function search() {
        results.innerHTML = `<button onclick="selectPatient()"
          style="position:fixed;left:100px;top:200px;width:150px;height:30px">Select John Smith</button>`;
      }
      function selectPatient() {
        results.innerHTML = `<h2>Patient Summary</h2>
          <button onclick="recent()" style="position:fixed;left:100px;top:250px;width:150px;height:30px">Recent Claims</button>
          <span style="position:fixed;left:100px;top:300px">John Smith</span>
          <span style="position:fixed;left:100px;top:325px">Active</span>
          <section id="claims"></section>`;
      }
      function recent() {
        claims.innerHTML = '<p style="position:fixed;left:100px;top:350px">CLM-2026-0142 — Pending</p>';
      }
    </script></body></html>
    """
    return f"data:text/html,{quote(html)}"


def data_policy() -> PolicyConfig:
    return PolicyConfig(
        version="test",
        network=NetworkPolicy(
            allowed_origins=["data://"],
            allowed_path_patterns=[".*"],
        ),
        actions=ActionPolicy(
            allowed=[
                ActionType.CLICK,
                ActionType.TYPE,
                ActionType.WAIT,
                ActionType.EXTRACT,
            ],
        ),
        redaction=RedactionPolicy(
            sensitive_keys=["password", "member_id"],
        ),
    )


async def test_model_loop_compiles_actions_into_artifact(tmp_path: Path) -> None:
    first = turn(
        [
            call("c1", "left_click", {"coordinate": [150, 115]}),
            call("c2", "type", {"text": "provider"}),
            call("c3", "left_click", {"coordinate": [150, 165]}),
            call("c4", "type", {"text": "claims123"}),
            call("c5", "left_click", {"coordinate": [150, 220]}),
            call("c6", "screenshot", {}),
        ]
    )
    second = turn(
        [
            call("c7", "left_click", {"coordinate": [150, 115]}),
            call("c8", "type", {"text": "MRN-10042"}),
            call("c9", "left_click", {"coordinate": [150, 165]}),
            call("c10", "left_click", {"coordinate": [150, 215]}),
            call("c11", "left_click", {"coordinate": [150, 265]}),
            call("c12", "screenshot", {}),
        ]
    )
    completion = turn(
        [
            call(
                "done",
                "complete_capability",
                {
                    "summary": "Patient selected and recent claims expanded",
                    "final_checkpoint_text": "CLM-2026-0142",
                    "outputs": {
                        "patient_name": "John Smith",
                        "patient_status": "Active",
                    },
                },
                computer=False,
            )
        ]
    )
    config = data_policy()
    evidence = EvidenceRecorder(
        tmp_path / "discovery",
        run_id="discovery-test",
        redactor=Redactor(config.redaction),
        secret_values=["provider", "claims123"],
    )
    loop = DiscoveryLoop(
        surface=PlaywrightWebSurface(headless=True, viewport=(800, 600)),
        policy_gate=PolicyGate(config),
        evidence=evidence,
        client=FakeComputerClient([first, second, completion]),
        max_steps=20,
    )

    result = await loop.run(
        goal="Find member MRN-10042 and return patient name and status",
        target_url=fixed_demo_url(),
        capability_name="lookup_patient",
        parameters={"member_id": "MRN-10042"},
        credentials={"DEMO_USERNAME": "provider", "DEMO_PASSWORD": "claims123"},
    )

    assert result.status == DiscoveryStatus.SUCCESS, result.reason
    assert result.artifact
    assert result.artifact.verify_content_hash()
    assert result.artifact.agent_input_schema()["required"] == ["member_id"]
    assert len(result.artifact.steps) == 7
    assert result.artifact.steps[0].credential_ref == "DEMO_USERNAME"
    assert result.artifact.steps[3].value_template == "{member_id}"
    persisted_log = evidence.events_path.read_text()
    assert "claims123" not in persisted_log
    assert "MRN-10042" not in persisted_log


def test_stuck_detector_requires_repeated_action_or_state() -> None:
    detector = StuckDetector(repeated_action_limit=3, unchanged_state_limit=3)

    assert not detector.observe(tool_name="click", tool_input={"x": 1}, state_fingerprint="a").stuck
    assert not detector.observe(tool_name="click", tool_input={"x": 1}, state_fingerprint="a").stuck
    decision = detector.observe(tool_name="click", tool_input={"x": 1}, state_fingerprint="a")

    assert decision.stuck
    assert "same action" in str(decision.reason)
