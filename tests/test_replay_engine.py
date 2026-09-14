from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from interface_ai.artifact.schema import (
    ActionType,
    ArtifactMetadata,
    CapabilityArtifact,
    CapabilityStep,
    Checkpoint,
    CheckpointKind,
    CredentialReference,
    ExtractionSpec,
    LocatorKind,
    LocatorStrategy,
    ObservationRule,
    OutcomeClass,
    OutputSpec,
    ParameterSpec,
    RecoveryAction,
    RetryPolicy,
    SurfaceKind,
    TargetSpec,
    ValueType,
)
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.locator_resolver import LocatorResolver
from interface_ai.replay.result import ReplayStatus
from interface_ai.surface.web_playwright import PlaywrightWebSurface


def role(role: str, name: str, rank: int = 1) -> LocatorStrategy:
    return LocatorStrategy(
        kind=LocatorKind.ROLE_NAME,
        rank=rank,
        role=role,
        name=name,
        reasoning="Accessible role and stable visible name",
    )


def text(value: str) -> LocatorStrategy:
    return LocatorStrategy(
        kind=LocatorKind.TEXT,
        rank=1,
        value=value,
        reasoning="Stable visible text used as deterministic state evidence",
    )


def css(value: str, rank: int = 1) -> LocatorStrategy:
    return LocatorStrategy(
        kind=LocatorKind.CSS,
        rank=rank,
        value=value,
        reasoning="Scoped structural selector for deterministic extraction",
    )


def demo_app_url() -> str:
    html = """
    <html><body>
      <main id="app">
        <label>Provider ID <input aria-label="Provider ID"></label>
        <label>Password <input aria-label="Password" type="password"></label>
        <button onclick="showPatients()">Sign in</button>
      </main>
      <script>
        function showPatients() {
          app.innerHTML = `
            <h1>Patients</h1>
            <label>Search patients <input aria-label="Search patients"></label>
            <button onclick="search()">Search</button>
            <section id="results"></section>`;
        }
        function search() {
          const value = document.querySelector('[aria-label="Search patients"]').value;
          results.innerHTML = value === 'MISSING'
            ? '<p>No patient found</p>'
            : '<button onclick="selectPatient()">Select John Smith</button>';
        }
        function selectPatient() {
          results.innerHTML = `
            <h2>Patient Summary</h2>
            <span data-output="patient-name">John Smith</span>
            <span data-output="patient-status">Active</span>
            <button onclick="recent()">Recent Claims</button>
            <section id="claims"></section>`;
        }
        function recent() { claims.innerHTML = '<p>CLM-2026-0142 — Pending</p>'; }
      </script>
    </body></html>
    """
    return f"data:text/html,{quote(html)}"


def replay_artifact() -> CapabilityArtifact:
    return CapabilityArtifact(
        capability_version="1.0.0",
        capability_id=UUID("f9027c35-6a3a-4d19-8de8-6e40c6946bdd"),
        name="lookup_patient_claims",
        description="Find a synthetic patient and return claim summary information",
        target=TargetSpec(
            app_id="test-healthcare",
            vendor_product="Test Healthcare",
            surface=SurfaceKind.WEB,
            entry_url_template=demo_app_url(),
            allowed_origin="null",
            product_version="1",
        ),
        input_parameters=[
            ParameterSpec(
                name="member_id",
                type=ValueType.STRING,
                description="Synthetic member record identifier",
                pattern=r"^[A-Z0-9-]+$",
            )
        ],
        credential_references=[
            CredentialReference(name="DEMO_USERNAME", purpose="Demo provider login"),
            CredentialReference(name="DEMO_PASSWORD", purpose="Demo provider password"),
        ],
        outputs=[
            OutputSpec(
                name="patient_name",
                type=ValueType.STRING,
                description="Synthetic patient display name",
                extraction=ExtractionSpec(
                    locators=[css("[data-output='patient-name']")]
                ),
            ),
            OutputSpec(
                name="patient_status",
                type=ValueType.STRING,
                description="Synthetic patient status",
                extraction=ExtractionSpec(
                    locators=[css("[data-output='patient-status']")]
                ),
            ),
        ],
        steps=[
            CapabilityStep(
                id="enter-provider",
                description="Enter provider ID",
                action=ActionType.TYPE,
                locators=[role("textbox", "Provider ID")],
                credential_ref="DEMO_USERNAME",
            ),
            CapabilityStep(
                id="enter-password",
                description="Enter password",
                action=ActionType.TYPE,
                locators=[role("textbox", "Password")],
                credential_ref="DEMO_PASSWORD",
            ),
            CapabilityStep(
                id="sign-in",
                description="Sign in to the claims portal",
                action=ActionType.CLICK,
                locators=[role("button", "Sign in")],
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.TEXT_VISIBLE,
                        description="Patient search page is visible",
                        expected="Patients",
                    )
                ],
            ),
            CapabilityStep(
                id="enter-member",
                description="Enter synthetic member ID",
                action=ActionType.TYPE,
                locators=[role("textbox", "Search patients")],
                value_template="{member_id}",
            ),
            CapabilityStep(
                id="search",
                description="Search for the patient",
                action=ActionType.CLICK,
                locators=[role("button", "Search")],
                observation_rules=[
                    ObservationRule(
                        code="PATIENT_NOT_FOUND",
                        classification=OutcomeClass.BUSINESS,
                        description="No patient matches the supplied member ID",
                        when=Checkpoint(
                            kind=CheckpointKind.TEXT_VISIBLE,
                            description="No-results message is visible",
                            expected="No patient found",
                            timeout_ms=500,
                        ),
                        recovery=RecoveryAction.STOP,
                    )
                ],
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.TEXT_VISIBLE,
                        description="Matching patient action is visible",
                        expected="Select John Smith",
                        timeout_ms=1_000,
                    )
                ],
            ),
            CapabilityStep(
                id="select-patient",
                description="Select the matching patient",
                action=ActionType.CLICK,
                locators=[role("button", "Select John Smith")],
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.TEXT_VISIBLE,
                        description="Patient summary is visible",
                        expected="Patient Summary",
                    )
                ],
            ),
            CapabilityStep(
                id="expand-claims",
                description="Expand recent claims",
                action=ActionType.CLICK,
                locators=[role("button", "Recent Claims")],
            ),
        ],
        success_checkpoint=Checkpoint(
            kind=CheckpointKind.TEXT_VISIBLE,
            description="Most recent claim appears",
            expected="CLM-2026-0142",
        ),
        metadata=ArtifactMetadata(source_run_id="hand-authored-golden"),
    )


async def test_deterministic_replay_returns_declared_outputs(tmp_path: Path) -> None:
    surface = PlaywrightWebSurface(headless=True, viewport=(900, 700))
    engine = ReplayEngine(surface, evidence_dir=tmp_path)

    result = await engine.run(
        replay_artifact(),
        {"member_id": "MRN-10042"},
        credentials={"DEMO_USERNAME": "provider", "DEMO_PASSWORD": "claims123"},
    )

    assert result.status == ReplayStatus.SUCCESS
    assert result.completed_steps == 7
    assert result.outputs == {"patient_name": "John Smith", "patient_status": "Active"}


async def test_not_found_is_business_outcome_not_crash(tmp_path: Path) -> None:
    surface = PlaywrightWebSurface(headless=True)
    engine = ReplayEngine(surface, evidence_dir=tmp_path)

    result = await engine.run(
        replay_artifact(),
        {"member_id": "MISSING"},
        credentials={"DEMO_USERNAME": "provider", "DEMO_PASSWORD": "claims123"},
    )

    assert result.status == ReplayStatus.BUSINESS_OUTCOME
    assert result.outcome_code == "PATIENT_NOT_FOUND"
    assert result.failure is None


async def test_locator_resolver_skips_ambiguous_candidate() -> None:
    surface = PlaywrightWebSurface(headless=True)
    await surface.start(
        start_url="data:text/html,"
        + quote("<button>Open</button><button id='target'>Open</button>")
    )
    try:
        resolver = LocatorResolver(surface._require_page())
        target = await resolver.resolve(
            [
                role("button", "Open", rank=1),
                css("#target", rank=2),
            ]
        )

        assert target.strategy.kind == LocatorKind.CSS
        assert target.strategy.rank == 2
    finally:
        await surface.close()


async def test_recoverable_condition_exhaustion_is_not_hard_failure(
    tmp_path: Path,
) -> None:
    artifact = replay_artifact().model_copy(
        update={
            "target": replay_artifact().target.model_copy(
                update={
                    "entry_url_template": "data:text/html,"
                    + quote(
                        "<button>Search</button>"
                        "<p>Service temporarily unavailable</p>"
                    )
                }
            ),
            "steps": [
                CapabilityStep(
                    id="search",
                    description="Retry a transient search",
                    action=ActionType.CLICK,
                    locators=[role("button", "Search")],
                    observation_rules=[
                        ObservationRule(
                            code="TRANSIENT_SERVICE_ERROR",
                            classification=OutcomeClass.RECOVERABLE,
                            description="The service is temporarily unavailable",
                            when=Checkpoint(
                                kind=CheckpointKind.TEXT_VISIBLE,
                                description="Transient error message is visible",
                                expected="Service temporarily unavailable",
                                timeout_ms=500,
                            ),
                            recovery=RecoveryAction.WAIT,
                            retry_policy=RetryPolicy(
                                max_attempts=2,
                                initial_delay_ms=1,
                                jitter_ratio=0,
                            ),
                            wait_ms=1,
                        )
                    ],
                    retry_policy=RetryPolicy(
                        max_attempts=2, initial_delay_ms=1, jitter_ratio=0
                    ),
                )
            ],
            "outputs": [],
            "success_checkpoint": Checkpoint(
                kind=CheckpointKind.TEXT_VISIBLE,
                description="Impossible success state",
                expected="Complete",
                timeout_ms=500,
            ),
        }
    )
    surface = PlaywrightWebSurface(headless=True)

    result = await ReplayEngine(surface, evidence_dir=tmp_path).run(
        artifact, {"member_id": "MRN-10042"}
    )

    assert result.status == ReplayStatus.RECOVERABLE_EXHAUSTED
    assert result.failure
    assert result.failure.code == "TRANSIENT_SERVICE_ERROR"
    assert len(result.failure.evidence_paths) == 1
    assert Path(result.failure.evidence_paths[0]).exists()
