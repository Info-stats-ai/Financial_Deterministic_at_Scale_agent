from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from interface_ai.artifact.io import ArtifactIntegrityError, load_artifact, save_artifact
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
    OutputSpec,
    ParameterSpec,
    RiskClass,
    SurfaceKind,
    TargetSpec,
    ValueType,
)


def role_locator(name: str, rank: int = 1) -> LocatorStrategy:
    return LocatorStrategy(
        kind=LocatorKind.ROLE_NAME,
        rank=rank,
        role="textbox",
        name=name,
        reasoning="Accessible role and stable visible label",
    )


def example_artifact() -> CapabilityArtifact:
    return CapabilityArtifact(
        capability_version="1.0.0",
        capability_id=UUID("177a42c8-129a-44e9-9750-8c6ba08d01d8"),
        name="lookup_claim",
        description="Look up a fake demo claim by member identifier",
        target=TargetSpec(
            app_id="cloudcruise-healthcare",
            vendor_product="CloudCruise XPath Healthcare",
            surface=SurfaceKind.WEB,
            entry_url_template="https://demo.cloudcruise.com/xpath-cascade-healthcare",
            allowed_origin="https://demo.cloudcruise.com",
            product_version="1",
        ),
        input_parameters=[
            ParameterSpec(
                name="member_id",
                type=ValueType.STRING,
                description="Synthetic member identifier",
                pattern=r"^[A-Z0-9-]+$",
                examples=["MEM-1001"],
            )
        ],
        credential_references=[
            CredentialReference(name="DEMO_USERNAME", purpose="Demo portal login")
        ],
        outputs=[
            OutputSpec(
                name="claim_status",
                type=ValueType.STRING,
                description="Current status shown by the demo",
                extraction=ExtractionSpec(
                    locators=[
                        LocatorStrategy(
                            kind=LocatorKind.TEXT,
                            rank=1,
                            value="Claim Status",
                            reasoning="Stable result label near extracted value",
                        )
                    ]
                ),
            )
        ],
        steps=[
            CapabilityStep(
                id="enter-member-id",
                description="Enter the synthetic member identifier",
                action=ActionType.TYPE,
                locators=[role_locator("Member ID")],
                value_template="{member_id}",
                postconditions=[
                    Checkpoint(
                        kind=CheckpointKind.VALUE_MATCHES,
                        description="Member identifier field contains the input",
                        expected="{member_id}",
                        locator=role_locator("Member ID"),
                    )
                ],
                risk_class=RiskClass.SAFE,
            )
        ],
        success_checkpoint=Checkpoint(
            kind=CheckpointKind.TEXT_VISIBLE,
            description="Claim detail is visible",
            expected="Claim Details",
        ),
        metadata=ArtifactMetadata(source_run_id="discovery-test-001"),
    )


def test_round_trip_and_integrity_hash(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    saved = save_artifact(example_artifact(), path)

    loaded = load_artifact(path)

    assert loaded == saved
    assert loaded.verify_content_hash()
    assert loaded.content_hash is not None


def test_tampering_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    save_artifact(example_artifact(), path)
    path.write_text(path.read_text().replace("lookup_claim", "changed"), encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError):
        load_artifact(path)


def test_agent_input_schema_is_strict_and_typed() -> None:
    schema = example_artifact().agent_input_schema()

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["member_id"]
    assert schema["properties"]["member_id"]["type"] == "string"
    assert schema["properties"]["member_id"]["pattern"] == r"^[A-Z0-9-]+$"


def test_unknown_template_parameter_is_rejected() -> None:
    artifact = example_artifact().model_dump()
    artifact["steps"][0]["value_template"] = "{missing}"

    with pytest.raises(ValidationError, match="unknown parameter placeholders"):
        CapabilityArtifact.model_validate(artifact)


def test_duplicate_locator_ranks_are_rejected() -> None:
    with pytest.raises(ValidationError, match="locator ranks must be unique"):
        CapabilityStep(
            id="duplicate",
            description="Ambiguous locator order",
            action=ActionType.CLICK,
            locators=[
                LocatorStrategy(
                    kind=LocatorKind.TEXT,
                    rank=1,
                    value="Search",
                    reasoning="First visible text candidate",
                ),
                LocatorStrategy(
                    kind=LocatorKind.CSS,
                    rank=1,
                    value="button.search",
                    reasoning="Fallback structural selector candidate",
                ),
            ],
        )
