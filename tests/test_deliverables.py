import json
import re
from pathlib import Path

from interface_ai.artifact.io import load_artifact


def test_report_has_exact_required_headings_in_order() -> None:
    report = Path("REPORT.md").read_text()
    headings = re.findall(r"^# (.+)$", report, flags=re.MULTILINE)

    assert headings == [
        "Architecture",
        "Artifact schema",
        "Determinism & error handling",
        "Heterogeneity & multi-tenant",
        "Escalation & handoff",
        "Safety",
        "Cuts",
    ]


def test_readme_has_exact_discovery_replay_and_offline_commands() -> None:
    readme = Path("README.md").read_text()

    assert "uv run capability discover" in readme
    assert "uv run capability replay" in readme
    assert "uv run capability catalog" in readme
    assert "uv run capability invoke" in readme
    assert "--offline-har evidence/fixtures/cloudcruise-healthcare.har" in readme
    assert "--operator-port 8787" in readme


def test_curated_artifact_and_replay_evidence_are_valid() -> None:
    artifact = load_artifact(
        Path("evidence/artifacts/lookup_patient_recent_claims.v1.json")
    )
    assert artifact.verify_content_hash()

    expected = {
        "replay-success": "success",
        "replay-not-found": "business_outcome",
        "replay-hard-failure": "hard_failure",
    }
    for directory, status in expected.items():
        run_dir = Path("evidence/replay") / directory
        result = json.loads((run_dir / "result.json").read_text())
        assert result["status"] == status
        assert (run_dir / "events.jsonl").stat().st_size > 0

    failure = json.loads(
        Path("evidence/replay/replay-hard-failure/result.json").read_text()
    )
    assert failure["failure"]["evidence_paths"]
    assert Path(failure["failure"]["evidence_paths"][0]).exists()


def test_replay_package_has_no_anthropic_dependency() -> None:
    for path in Path("src/interface_ai/replay").glob("*.py"):
        assert "anthropic" not in path.read_text().lower()


def test_no_private_anthropic_key_is_committed() -> None:
    private_key = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")
    for path in Path(".").rglob("*"):
        if (
            not path.is_file()
            or any(
                cache in path.parts
                for cache in {
                    ".git",
                    ".venv",
                    ".mypy_cache",
                    ".pytest_cache",
                    ".ruff_cache",
                }
            )
            or path.suffix in {".png", ".har", ".pyc"}
        ):
            continue
        assert not private_key.search(path.read_text(errors="ignore")), path
