"""Reviewed golden artifact for replay before/without a discovery API call."""

from __future__ import annotations

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
    RiskClass,
    SurfaceKind,
    TargetSpec,
    ValueType,
)


def role(role_name: str, accessible_name: str, rank: int = 1) -> LocatorStrategy:
    return LocatorStrategy(
        kind=LocatorKind.ROLE_NAME,
        rank=rank,
        role=role_name,
        name=accessible_name,
        reasoning="Accessible role and visible name are stable across shuffled table layouts",
    )


def xpath(value: str, rank: int = 1, reason: str | None = None) -> LocatorStrategy:
    return LocatorStrategy(
        kind=LocatorKind.XPATH,
        rank=rank,
        value=value,
        reasoning=reason
        or "Semantic table-column anchor avoids dependence on shuffled column order",
    )


def patient_row_target(column: str) -> LocatorStrategy:
    return xpath(
        "//tr[.//td[@data-column='mrn' and normalize-space()='{member_id}']]"
        f"//td[@data-column='{column}']"
    )


def select_patient_target() -> LocatorStrategy:
    return xpath(
        "//tr[.//td[@data-column='mrn' and normalize-space()='{member_id}']]"
        "//button[normalize-space()='Select']"
    )


def build_demo_artifact() -> CapabilityArtifact:
    select_target = select_patient_target()
    return CapabilityArtifact(
        capability_version="1.0.0",
        capability_id=UUID("5fc5bf56-60b1-502f-87ec-26c74f30e58d"),
        name="lookup_patient_recent_claims",
        description=(
            "Look up a synthetic patient by MRN, select the patient, expand recent claims, "
            "and return the declared summary fields"
        ),
        target=TargetSpec(
            app_id="cloudcruise-healthcare",
            vendor_product="CloudCruise XPath Cascade Healthcare",
            surface=SurfaceKind.WEB,
            entry_url_template=("https://demo.cloudcruise.com/xpath-cascade-healthcare?reset=true"),
            allowed_origin="https://demo.cloudcruise.com",
            product_version="1",
        ),
        input_parameters=[
            ParameterSpec(
                name="member_id",
                type=ValueType.STRING,
                description="Synthetic medical record number from the public demo",
                pattern=r"^(?:MRN|DEMO)-\d{5}$",
                examples=[],
                sensitive=True,
            )
        ],
        credential_references=[
            CredentialReference(name="DEMO_USERNAME", purpose="Public synthetic demo provider ID"),
            CredentialReference(name="DEMO_PASSWORD", purpose="Public synthetic demo password"),
        ],
        outputs=[
            OutputSpec(
                name="patient_name",
                type=ValueType.STRING,
                description="Selected synthetic patient's display name",
                sensitive=True,
                extraction=ExtractionSpec(locators=[patient_row_target("patient-name")]),
            ),
            OutputSpec(
                name="patient_status",
                type=ValueType.STRING,
                description="Selected synthetic patient's active status",
                extraction=ExtractionSpec(locators=[patient_row_target("status")]),
            ),
            OutputSpec(
                name="insurance",
                type=ValueType.STRING,
                description="Selected synthetic patient's insurer",
                sensitive=True,
                extraction=ExtractionSpec(locators=[patient_row_target("insurance")]),
            ),
            OutputSpec(
                name="latest_claim",
                type=ValueType.STRING,
                description="First claim shown in the expanded recent-claims panel",
                sensitive=True,
                extraction=ExtractionSpec(
                    locators=[
                        xpath(
                            "(//button[@aria-label='Recent Claims']"
                            "/following-sibling::div//div[not(*)])[1]",
                            reason=("Anchors extraction to the labelled Recent Claims panel"),
                        )
                    ]
                ),
            ),
        ],
        steps=[
            CapabilityStep(
                id="enter-provider-id",
                description="Enter the public demo provider ID",
                action=ActionType.TYPE,
                locators=[
                    role("textbox", "Provider ID"),
                    LocatorStrategy(
                        kind=LocatorKind.LABEL,
                        rank=2,
                        value="Provider ID",
                        reasoning="Visible form label survives CSS and layout changes",
                    ),
                ],
                credential_ref="DEMO_USERNAME",
            ),
            CapabilityStep(
                id="enter-password",
                description="Enter the public demo password",
                action=ActionType.TYPE,
                locators=[
                    role("textbox", "Password"),
                    LocatorStrategy(
                        kind=LocatorKind.LABEL,
                        rank=2,
                        value="Password",
                        reasoning="Visible form label survives CSS and layout changes",
                    ),
                ],
                credential_ref="DEMO_PASSWORD",
            ),
            CapabilityStep(
                id="sign-in",
                description="Sign in to the synthetic claims portal",
                action=ActionType.CLICK,
                locators=[role("button", "Sign in")],
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.TEXT_VISIBLE,
                        description="Patient workspace loaded",
                        expected="Patients",
                    )
                ],
            ),
            CapabilityStep(
                id="search-member",
                description="Filter patients by synthetic MRN",
                action=ActionType.TYPE,
                locators=[role("textbox", "Search patients")],
                value_template="{member_id}",
                observation_rules=[
                    ObservationRule(
                        code="PATIENT_NOT_FOUND",
                        classification=OutcomeClass.BUSINESS,
                        description="No patient matches the supplied synthetic MRN",
                        when=Checkpoint(
                            kind=CheckpointKind.ELEMENT_ABSENT,
                            description="No matching row has a Select action",
                            expected=True,
                            locator=select_target,
                            timeout_ms=750,
                        ),
                        recovery=RecoveryAction.STOP,
                    )
                ],
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.ELEMENT_VISIBLE,
                        description="Matching patient row has a Select action",
                        expected=True,
                        locator=select_target,
                        timeout_ms=2_000,
                    )
                ],
            ),
            CapabilityStep(
                id="select-patient",
                description="Select the patient row matching the supplied MRN",
                action=ActionType.CLICK,
                locators=[select_target],
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.TEXT_VISIBLE,
                        description="Patient summary panel is populated",
                        expected="Patient Summary",
                    )
                ],
            ),
            CapabilityStep(
                id="expand-recent-claims",
                description="Expand the selected patient's recent claims",
                action=ActionType.CLICK,
                locators=[role("button", "Recent Claims")],
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.ELEMENT_VISIBLE,
                        description="Recent Claims accordion is expanded",
                        expected=True,
                        locator=xpath(
                            "//button[@aria-label='Recent Claims' and @aria-expanded='true']",
                            reason="ARIA expanded state verifies the accordion action",
                        ),
                    )
                ],
                risk_class=RiskClass.SAFE,
            ),
        ],
        success_checkpoint=Checkpoint(
            kind=CheckpointKind.ELEMENT_VISIBLE,
            description="Recent Claims accordion remains expanded",
            expected=True,
            locator=xpath(
                "//button[@aria-label='Recent Claims' and @aria-expanded='true']",
                reason="Final semantic state confirms the requested panel is open",
            ),
        ),
        metadata=ArtifactMetadata(
            source_run_id="reviewed-golden-before-live-discovery",
            recorded_by="human_reviewed_fixture",
            approved_for_unattended_replay=False,
            tags=["public-demo", "synthetic-data", "golden-fixture"],
        ),
    ).with_content_hash()
