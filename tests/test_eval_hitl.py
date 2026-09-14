import asyncio
from pathlib import Path
from urllib.parse import quote

from interface_ai.artifact.schema import ActionType
from interface_ai.core.session import SessionManager
from interface_ai.demo_artifact import build_demo_artifact
from interface_ai.eval.operator import SimulatedClaimsOperator
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.handoff.controller import HandoffController
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayStatus
from interface_ai.safety.policy import (
    ActionPolicy,
    NetworkPolicy,
    PolicyConfig,
    PolicyGate,
    RedactionPolicy,
)
from interface_ai.safety.redaction import Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface

CLAIMS_HTML = """
<html><body>
<form id="login">
  <input aria-label="Provider ID">
  <input aria-label="Password" type="password">
  <button type="button" aria-label="Sign in">Sign in</button>
</form>
<main id="app" hidden>
  <h1>Patients</h1>
  <input aria-label="Search patients">
  <table><tbody>
    <tr id="row">
      <td data-column="mrn">MRN-10042</td>
      <td data-column="patient-name">Jane Doe</td>
      <td data-column="status">Active</td>
      <td data-column="insurance">Acme</td>
      <td><button>Select</button></td>
    </tr>
  </tbody></table>
  <div id="summary" hidden>Patient Summary</div>
  <button type="button" aria-label="Recent Claims" aria-expanded="false">Recent Claims</button>
  <div id="claims" hidden><div>CLM-1 Pending</div></div>
</main>
<script>
document.querySelector('[aria-label="Sign in"]').onclick = () => {
  if (document.querySelector('[aria-label="Password"]').value === 'claims123') {
    document.getElementById('login').hidden = true;
    document.getElementById('app').hidden = false;
  }
};
document.querySelector('[aria-label="Search patients"]').addEventListener('input', (event) => {
  document.getElementById('row').hidden = !document.querySelector('[data-column="mrn"]')
    .textContent.includes(event.target.value);
});
document.querySelector('#row button').onclick = () => {
  document.getElementById('summary').hidden = false;
};
document.querySelector('[aria-label="Recent Claims"]').onclick = (event) => {
  event.target.setAttribute('aria-expanded', 'true');
  document.getElementById('claims').hidden = false;
};
</script>
</body></html>
"""


def _policy() -> PolicyConfig:
    return PolicyConfig(
        version="hitl-eval",
        network=NetworkPolicy(allowed_origins=["data://"], allowed_path_patterns=[".*"]),
        actions=ActionPolicy(
            allowed=[ActionType.CLICK, ActionType.TYPE, ActionType.WAIT, ActionType.EXTRACT]
        ),
        redaction=RedactionPolicy(sensitive_keys=["password"]),
    )


async def test_operator_recovers_login_on_same_session(tmp_path: Path) -> None:
    url = "data:text/html," + quote(CLAIMS_HTML)
    base = build_demo_artifact()
    artifact = base.model_copy(
        update={
            "target": base.target.model_copy(update={"entry_url_template": url}),
            "content_hash": None,
        }
    )
    config = _policy()
    surface = PlaywrightWebSurface(headless=True)
    evidence = EvidenceRecorder(
        tmp_path / "hitl",
        run_id="hitl-eval",
        redactor=Redactor(config.redaction),
        secret_values=["claims123", "wrong-demo-value"],
    )
    session = SessionManager(surface)
    handoff = HandoffController(session, evidence, timeout_seconds=45)
    operator = SimulatedClaimsOperator(
        session, username="provider", password="claims123", timeout_seconds=60
    )
    operator_task = asyncio.create_task(operator.run())
    try:
        result = await ReplayEngine(
            surface,
            evidence=evidence,
            policy_gate=PolicyGate(config),
            handoff=handoff,
        ).run(
            artifact,
            {"member_id": "MRN-10042"},
            credentials={"DEMO_USERNAME": "provider", "DEMO_PASSWORD": "wrong-demo-value"},
            keep_session_open=True,
        )
        context_after = surface.context
    finally:
        if not operator_task.done():
            operator_task.cancel()
            try:
                await operator_task
            except asyncio.CancelledError:
                pass
        else:
            await operator_task
        await surface.close()

    assert result.status == ReplayStatus.SUCCESS
    assert operator.recovered
    assert context_after is not None
    assert result.completed_steps == 6
