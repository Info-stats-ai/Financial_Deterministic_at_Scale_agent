"""Agent-facing capability catalog: discover artifacts and invoke them by name."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from interface_ai.artifact.io import load_artifact
from interface_ai.artifact.schema import CapabilityArtifact, RiskClass

_RISK_RANK = {
    RiskClass.SAFE: 0,
    RiskClass.REVERSIBLE: 1,
    RiskClass.RISKY: 2,
    RiskClass.IRREVERSIBLE: 3,
    "safe": 0,
    "reversible": 1,
    "risky": 2,
    "irreversible": 3,
}


class CatalogError(LookupError):
    pass


class CapabilityCatalog:
    """Filesystem-backed registry of reviewed, hashed artifacts."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def artifacts(self) -> list[CapabilityArtifact]:
        if not self.directory.exists():
            return []
        return [load_artifact(path) for path in sorted(self.directory.glob("*.json"))]

    def path_for(self, name: str) -> Path:
        matches = [
            path
            for path in sorted(self.directory.glob("*.json"))
            if load_artifact(path).name == name
        ]
        if not matches:
            raise CatalogError(f"unknown capability: {name}")
        if len(matches) > 1:
            raise CatalogError(f"ambiguous capability name: {name}")
        return matches[0]

    def get(self, name: str) -> CapabilityArtifact:
        return load_artifact(self.path_for(name))

    def list_tools(self) -> list[dict[str, Any]]:
        """Return OpenAI/Anthropic-style tool specs an upstream agent can call."""

        tools: list[dict[str, Any]] = []
        for artifact in self.artifacts():
            tools.append(
                {
                    "name": artifact.name,
                    "description": artifact.description,
                    "capability_id": str(artifact.capability_id),
                    "capability_version": artifact.capability_version,
                    "risk_profile": max(
                        (step.risk_class for step in artifact.steps),
                        key=lambda item: _RISK_RANK[item],
                        default=RiskClass.SAFE.value,
                    ),
                    "approved": artifact.metadata.approved_for_unattended_replay,
                    "input_schema": artifact.agent_input_schema(),
                    "outputs": [
                        {
                            "name": output.name,
                            "type": output.type,
                            "description": output.description,
                        }
                        for output in artifact.outputs
                    ],
                }
            )
        return tools
