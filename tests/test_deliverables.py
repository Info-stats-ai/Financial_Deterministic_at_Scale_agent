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
    assert "uv run capability evaluate" in readme
    assert "evidence/discovery/discovery-live/artifact.json" in readme
    assert "evidence/artifacts/lookup_patient_recent_claims.v1.json" in readme
    assert "--offline-har evidence/fixtures/cloudcruise-healthcare.har" in readme
    assert "--operator-port 8787" in readme


def test_live_discovery_evidence_is_genuine() -> None:
    run_dir = Path("evidence/discovery/discovery-live")
    result = json.loads((run_dir / "result.json").read_text())
    events = (run_dir / "events.jsonl").read_text()

    assert result["status"] == "success"
    assert result["input_tokens"] > 0
    assert result["output_tokens"] > 0
    assert result["computer_actions"] > 0
    assert "toolset_name" in events
    assert (run_dir / "final.png").stat().st_size > 0
    assert (run_dir / "artifact.json").stat().st_size > 0
    assert (run_dir / "network.har").stat().st_size > 0
    assert "sk-ant-" not in events
    assert "claims123" not in events
    assert "claims123" not in (run_dir / "network.har").read_text()

    artifact = load_artifact(run_dir / "artifact.json")
    assert artifact.verify_content_hash()
    assert artifact.metadata.approved_for_unattended_replay is False


def test_curated_artifact_and_replay_evidence_are_valid() -> None:
    artifact = load_artifact(
        Path("evidence/artifacts/lookup_patient_recent_claims.v1.json")
    )
    assert artifact.verify_content_hash()
    assert artifact.metadata.approved_for_unattended_replay is True
    eval_report = json.loads(
        Path("evidence/eval/lookup_patient_recent_claims.eval.json").read_text()
    )
    assert eval_report["passed"] is True
    assert eval_report["composite"] >= 90
    assert eval_report["metrics"]["happy_path_success_rate"] == 1.0
    assert eval_report["metrics"]["business_outcome_fidelity"] == 1.0

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
    skipped_names = {".env", ".env.local"}
    skipped_parts = {
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
    for path in Path(".").rglob("*"):
        if (
            not path.is_file()
            or path.name in skipped_names
            or any(cache in path.parts for cache in skipped_parts)
            or path.suffix in {".png", ".har", ".pyc"}
        ):
            continue
        assert not private_key.search(path.read_text(errors="ignore")), path
