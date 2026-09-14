from pathlib import Path

from test_replay_engine import replay_artifact

from interface_ai.artifact.schema import (
    ActionType,
    CapabilityStep,
    LocatorKind,
    LocatorStrategy,
    RiskClass,
)
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayStatus
from interface_ai.safety.policy import PolicyGate, load_policy
from interface_ai.safety.redaction import REDACTED, Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface


def click_step(
    description: str = "Open patient summary",
    risk: RiskClass = RiskClass.SAFE,
) -> CapabilityStep:
    return CapabilityStep(
        id="test-action",
        description=description,
        action=ActionType.CLICK,
        locators=[
            LocatorStrategy(
                kind=LocatorKind.ROLE_NAME,
                rank=1,
                role="button",
                name=description,
                reasoning="Stable accessible button name",
            )
        ],
        risk_class=risk,
    )


def policy() -> PolicyGate:
    return PolicyGate(load_policy(Path("config/policy.yaml")))


def test_policy_allows_only_configured_origin_route_and_action() -> None:
    gate = policy()

    allowed = gate.check_step(
        click_step(),
        current_url="https://demo.cloudcruise.com/xpath-cascade-healthcare",
    )
    blocked_origin = gate.check_step(
        click_step(), current_url="https://attacker.example/steal"
    )
    blocked_route = gate.check_step(
        click_step(), current_url="https://demo.cloudcruise.com/admin"
    )

    assert allowed.allowed
    assert not blocked_origin.allowed
    assert blocked_origin.code == "ORIGIN_NOT_ALLOWED"
    assert not blocked_route.allowed
    assert blocked_route.code == "ROUTE_NOT_ALLOWED"


def test_risk_class_and_text_both_require_human_approval() -> None:
    gate = policy()
    url = "https://demo.cloudcruise.com/xpath-cascade-healthcare"

    declared = gate.check_step(
        click_step(risk=RiskClass.IRREVERSIBLE), current_url=url
    )
    inferred = gate.check_step(click_step("Submit Claim"), current_url=url)

    assert declared.allowed and declared.requires_human_approval
    assert inferred.allowed and inferred.requires_human_approval
    assert inferred.code == "HUMAN_APPROVAL_REQUIRED"


def test_redactor_scrubs_keys_patterns_and_url_query() -> None:
    redactor = Redactor(load_policy(Path("config/policy.yaml")).redaction)
    event = {
        "password": "claims123",
        "message": "member SSN is 123-45-6789",
        "url": "https://example.test/path?token=secret&safe=value",
        "nested": [{"account_number": "12345678"}],
    }

    redacted = redactor.redact(event)

    assert redacted["password"] == REDACTED
    assert redacted["message"] == "member SSN is [REDACTED:us_ssn]"
    assert "secret" not in redacted["url"]
    assert "safe=value" in redacted["url"]
    assert redacted["nested"][0]["account_number"] == REDACTED


async def test_replay_fails_closed_before_opening_unlisted_target() -> None:
    gate = policy()
    surface = PlaywrightWebSurface(headless=True)
    artifact = replay_artifact().model_copy(
        update={
            "target": replay_artifact().target.model_copy(
                update={"entry_url_template": "https://not-allowed.example/"}
            )
        }
    )

    result = await ReplayEngine(surface, policy_gate=gate).run(
        artifact, {"member_id": "MRN-10042"}
    )

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.failure
    assert result.failure.code == "ORIGIN_NOT_ALLOWED"
    assert surface.page is None
