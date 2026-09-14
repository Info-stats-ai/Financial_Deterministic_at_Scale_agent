"""Integrity-checked artifact persistence."""

from __future__ import annotations

import json
from pathlib import Path

from interface_ai.artifact.schema import CapabilityArtifact


class ArtifactIntegrityError(ValueError):
    pass


def save_artifact(artifact: CapabilityArtifact, path: Path) -> CapabilityArtifact:
    hashed = artifact.with_content_hash()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(hashed.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return hashed


def load_artifact(path: Path, *, verify_hash: bool = True) -> CapabilityArtifact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    artifact = CapabilityArtifact.model_validate(payload)
    if verify_hash and not artifact.verify_content_hash():
        raise ArtifactIntegrityError(f"artifact integrity check failed: {path}")
    return artifact


def export_agent_schema(artifact: CapabilityArtifact, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact.agent_input_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
