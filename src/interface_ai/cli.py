"""Command-line entry point for discovery and deterministic replay."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import typer
from dotenv import load_dotenv

from interface_ai.artifact.io import load_artifact, save_artifact
from interface_ai.artifact.schema import CapabilityArtifact
from interface_ai.catalog import CapabilityCatalog, CatalogError
from interface_ai.core.session import SessionManager
from interface_ai.discovery.anthropic_client import ClaudeComputerClient
from interface_ai.discovery.loop import DiscoveryLoop, DiscoveryResult
from interface_ai.eval.runner import EvaluationRunner, default_healthcare_scenarios
from interface_ai.eval.score import EvalReport
from interface_ai.evidence.recorder import EvidenceRecorder
from interface_ai.handoff.controller import HandoffController
from interface_ai.replay.engine import ReplayEngine
from interface_ai.replay.result import ReplayResult
from interface_ai.safety.policy import PolicyGate, load_policy
from interface_ai.safety.redaction import Redactor
from interface_ai.surface.web_playwright import PlaywrightWebSurface

app = typer.Typer(
    no_args_is_help=True,
    help="Discover and deterministically replay computer-use capabilities.",
)


def parse_assignments(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"expected NAME=VALUE, received {item!r}")
        name, value = item.split("=", 1)
        if not name or not value:
            raise typer.BadParameter(f"expected non-empty NAME=VALUE, received {item!r}")
        parsed[name] = value
    return parsed


def add_variant(url: str, variant: str | None) -> str:
    if not variant:
        return url
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["variant"] = variant
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


async def run_replay(
    artifact: CapabilityArtifact,
    parameters: dict[str, str],
    credentials: dict[str, str],
    *,
    evidence: EvidenceRecorder,
    policy_gate: PolicyGate,
    headless: bool,
    operator_port: int | None,
    offline_har: Path | None,
) -> ReplayResult:
    surface = PlaywrightWebSurface(
        headless=False if operator_port else headless,
        replay_har_path=offline_har,
    )
    if operator_port is None:
        return await ReplayEngine(
            surface,
            evidence_dir=evidence.run_dir,
            evidence=evidence,
            policy_gate=policy_gate,
        ).run(
            artifact,
            parameters,
            credentials=credentials,
            run_id=evidence.run_id,
        )

    session = SessionManager(
        surface,
        on_human_action=lambda action: evidence.record(
            "human_action", action.model_dump(mode="json")
        ),
    )
    handoff = HandoffController(session, evidence)
    await handoff.start_operator_console(port=operator_port)
    try:
        return await ReplayEngine(
            surface,
            evidence_dir=evidence.run_dir,
            evidence=evidence,
            policy_gate=policy_gate,
            handoff=handoff,
        ).run(
            artifact,
            parameters,
            credentials=credentials,
            run_id=evidence.run_id,
        )
    finally:
        await handoff.stop_operator_console()


async def run_discovery(
    *,
    surface: PlaywrightWebSurface,
    policy_gate: PolicyGate,
    evidence: EvidenceRecorder,
    client: ClaudeComputerClient,
    goal: str,
    target: str,
    name: str,
    parameters: dict[str, str],
    credentials: dict[str, str],
    max_steps: int,
    timeout_seconds: int,
    operator_port: int | None,
) -> DiscoveryResult:
    handoff: HandoffController | None = None
    if operator_port is not None:
        session = SessionManager(
            surface,
            on_human_action=lambda action: evidence.record(
                "human_action", action.model_dump(mode="json")
            ),
        )
        handoff = HandoffController(session, evidence)
        await handoff.start_operator_console(port=operator_port)
    try:
        return await DiscoveryLoop(
            surface=surface,
            policy_gate=policy_gate,
            evidence=evidence,
            client=client,
            handoff=handoff,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        ).run(
            goal=goal,
            target_url=target,
            capability_name=name,
            parameters=parameters,
            credentials=credentials,
        )
    finally:
        if handoff:
            await handoff.stop_operator_console()


@app.command()
def discover(
    goal: Annotated[str, typer.Option(help="Natural-language UI goal")],
    target: Annotated[
        str,
        typer.Option(
            help="Allowlisted entry URL",
        ),
    ] = "https://demo.cloudcruise.com/xpath-cascade-healthcare?reset=true",
    name: Annotated[str, typer.Option(help="Capability name")] = "lookup_patient_claims",
    param: Annotated[
        list[str] | None, typer.Option(help="Typed discovery input NAME=VALUE")
    ] = None,
    policy_path: Annotated[Path, typer.Option()] = Path("config/policy.yaml"),
    headless: Annotated[bool, typer.Option()] = False,
    max_steps: Annotated[int, typer.Option(min=1, max=50)] = 20,
    timeout_seconds: Annotated[int, typer.Option(min=30, max=900)] = 300,
    operator_port: Annotated[
        int | None,
        typer.Option(
            help="Run same-session operator console on this local port",
            min=1,
            max=65535,
        ),
    ] = 8787,
    evidence_label: Annotated[
        str | None,
        typer.Option(help="Stable label for a curated discovery run"),
    ] = None,
) -> None:
    """Run one genuine Claude-driven discovery and save its compiled artifact."""

    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise typer.BadParameter("ANTHROPIC_API_KEY is required for a genuine discovery run")
    parameters = parse_assignments(param or [])
    credentials = {
        "DEMO_USERNAME": os.getenv("DEMO_USERNAME", "provider"),
        "DEMO_PASSWORD": os.getenv("DEMO_PASSWORD", "claims123"),
    }
    if evidence_label and not evidence_label.replace("-", "").isalnum():
        raise typer.BadParameter("evidence-label must contain only letters, digits, or hyphens")
    run_id = (
        f"discovery-{evidence_label.lower()}"
        if evidence_label
        else f"discovery-{uuid4().hex[:12]}"
    )
    run_dir = Path("evidence/discovery") / run_id
    if evidence_label and run_dir.exists():
        raise typer.BadParameter(
            f"curated evidence directory already exists: {run_dir}"
        )
    policy = load_policy(policy_path)
    evidence = EvidenceRecorder(
        run_dir,
        run_id=run_id,
        redactor=Redactor(policy.redaction),
        secret_values=[*parameters.values(), *credentials.values()],
    )
    surface = PlaywrightWebSurface(
        headless=headless,
        har_path=run_dir / "network.har",
    )
    client = ClaudeComputerClient(model=os.getenv("COMPUTER_USE_MODEL", "claude-sonnet-5"))
    if operator_port:
        typer.echo(f"Operator console: http://127.0.0.1:{operator_port}")
    result = asyncio.run(
        run_discovery(
            surface=surface,
            policy_gate=PolicyGate(policy),
            evidence=evidence,
            client=client,
            goal=goal,
            target=target,
            name=name,
            parameters=parameters,
            credentials=credentials,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            operator_port=operator_port,
        )
    )
    if result.artifact:
        save_artifact(result.artifact, run_dir / "artifact.json")
    evidence.write_json("result.json", result.model_dump(mode="json"))
    typer.echo(result.model_dump_json(indent=2))
    if not result.artifact:
        raise typer.Exit(code=2)


@app.command()
def replay(
    artifact_path: Annotated[Path, typer.Option("--artifact", exists=True)],
    param: Annotated[list[str] | None, typer.Option(help="Invocation input NAME=VALUE")] = None,
    variant: Annotated[
        str | None,
        typer.Option(help="Demo-only deterministic runtime variant"),
    ] = None,
    policy_path: Annotated[Path, typer.Option()] = Path("config/policy.yaml"),
    headless: Annotated[bool, typer.Option()] = True,
    operator_port: Annotated[
        int | None,
        typer.Option(
            help="Run same-session operator console on this local port",
            min=1,
            max=65535,
        ),
    ] = None,
    offline_har: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            help="Serve recorded network responses and block live network fallback",
        ),
    ] = None,
    evidence_label: Annotated[
        str | None,
        typer.Option(help="Stable label for a curated evidence run"),
    ] = None,
) -> None:
    """Replay a saved artifact with no LLM in the decision path."""

    load_dotenv()
    artifact = load_artifact(artifact_path)
    if variant:
        artifact = artifact.model_copy(
            update={
                "target": artifact.target.model_copy(
                    update={
                        "entry_url_template": add_variant(
                            artifact.target.entry_url_template, variant
                        )
                    }
                ),
                "content_hash": None,
            }
        )
    parameters = parse_assignments(param or [])
    credentials = {
        reference.name: os.environ[reference.name]
        for reference in artifact.credential_references
        if reference.name in os.environ
    }
    if evidence_label and not evidence_label.replace("-", "").isalnum():
        raise typer.BadParameter("evidence-label must contain only letters, digits, or hyphens")
    run_id = f"replay-{evidence_label.lower()}" if evidence_label else f"replay-{uuid4().hex[:12]}"
    run_dir = Path("evidence/replay") / run_id
    policy = load_policy(policy_path)
    redactor = Redactor(policy.redaction)
    evidence = EvidenceRecorder(
        run_dir,
        run_id=run_id,
        redactor=redactor,
        secret_values=[*parameters.values(), *credentials.values()],
    )
    if operator_port:
        typer.echo(f"Operator console: http://127.0.0.1:{operator_port}")
    result = asyncio.run(
        run_replay(
            artifact,
            parameters,
            credentials,
            evidence=evidence,
            policy_gate=PolicyGate(policy),
            headless=headless,
            operator_port=operator_port,
            offline_har=offline_har,
        )
    )
    evidence.write_json("result.json", result.model_dump(mode="json"))
    typer.echo(json.dumps(redactor.redact(result.model_dump(mode="json")), indent=2))
    if result.status.value not in {"success", "business_outcome"}:
        raise typer.Exit(code=2)


@app.command()
def catalog(
    directory: Annotated[Path, typer.Option(exists=True)] = Path("evidence/artifacts"),
) -> None:
    """List reviewed artifacts as agent-callable tool specs."""

    tools = CapabilityCatalog(directory).list_tools()
    typer.echo(json.dumps(tools, indent=2))


@app.command()
def invoke(
    name: Annotated[str, typer.Option(help="Capability name from the catalog")],
    param: Annotated[list[str] | None, typer.Option(help="Invocation input NAME=VALUE")] = None,
    directory: Annotated[Path, typer.Option(exists=True)] = Path("evidence/artifacts"),
    policy_path: Annotated[Path, typer.Option()] = Path("config/policy.yaml"),
    headless: Annotated[bool, typer.Option()] = True,
    offline_har: Annotated[Path | None, typer.Option(exists=True)] = None,
    evidence_label: Annotated[str | None, typer.Option()] = None,
    allow_draft: Annotated[
        bool,
        typer.Option(help="Allow invoke of artifacts not approved by evaluate"),
    ] = False,
) -> None:
    """Invoke a cataloged capability by name. This is the agent-facing production path."""

    try:
        catalog = CapabilityCatalog(directory)
        artifact_path = catalog.path_for(name)
        artifact = catalog.get(name)
    except CatalogError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not artifact.metadata.approved_for_unattended_replay and not allow_draft:
        raise typer.BadParameter(
            f"{name} is a draft. Run `capability evaluate --promote` after it meets "
            "reliability gates, or pass --allow-draft."
        )
    replay(
        artifact_path=artifact_path,
        param=param,
        variant=None,
        policy_path=policy_path,
        headless=headless,
        operator_port=None,
        offline_har=offline_har,
        evidence_label=evidence_label or f"invoke-{name.replace('_', '-')}",
    )


def _promote_if_passed(artifact: CapabilityArtifact, path: Path, report: EvalReport) -> None:
    if not report.passed:
        raise typer.BadParameter(
            "evaluation gates failed; refusing to set approved_for_unattended_replay"
        )
    promoted = artifact.model_copy(
        update={
            "metadata": artifact.metadata.model_copy(
                update={
                    "approved_for_unattended_replay": True,
                    "tags": list(dict.fromkeys([*artifact.metadata.tags, "eval-promoted"])),
                }
            ),
            "content_hash": None,
        }
    )
    save_artifact(promoted, path)


@app.command()
def evaluate(
    artifact_path: Annotated[Path, typer.Option("--artifact", exists=True)],
    repeats: Annotated[int, typer.Option(min=1, max=20)] = 5,
    policy_path: Annotated[Path, typer.Option()] = Path("config/policy.yaml"),
    offline_har: Annotated[Path | None, typer.Option(exists=True)] = Path(
        "evidence/fixtures/cloudcruise-healthcare.har"
    ),
    headless: Annotated[bool, typer.Option()] = True,
    promote: Annotated[
        bool,
        typer.Option(help="If all gates pass, mark the artifact approved for unattended replay"),
    ] = False,
) -> None:
    """Score replay reliability. This is how a skill is promoted, not how a model is trained."""

    load_dotenv()
    artifact = load_artifact(artifact_path)
    credentials = {
        reference.name: os.environ[reference.name]
        for reference in artifact.credential_references
        if reference.name in os.environ
    }
    missing = [
        reference.name
        for reference in artifact.credential_references
        if reference.name not in credentials
    ]
    if missing:
        raise typer.BadParameter(f"missing runtime credentials: {missing}")
    policy = load_policy(policy_path)
    redactor = Redactor(policy.redaction)
    work_dir = Path("evidence/runtime") / f"eval-{artifact.name}"
    report = asyncio.run(
        EvaluationRunner(
            artifact,
            credentials=credentials,
            policy_gate=PolicyGate(policy),
            redactor=redactor,
            offline_har=offline_har,
            work_dir=work_dir,
            headless=headless,
        ).run(default_healthcare_scenarios(), repeats=repeats)
    )
    out_dir = Path("evidence/eval")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{artifact.name}.eval.json"
    EvidenceRecorder(
        out_dir,
        run_id=f"eval-{artifact.name}",
        redactor=redactor,
        secret_values=[*credentials.values()],
    ).write_json(report_path.name, report.model_dump(mode="json"))
    if promote:
        _promote_if_passed(artifact, artifact_path, report)
        report = report.model_copy(
            update={"notes": [*report.notes, f"promoted {artifact_path}"]}
        )
        EvidenceRecorder(
            out_dir,
            run_id=f"eval-{artifact.name}",
            redactor=redactor,
            secret_values=[*credentials.values()],
        ).write_json(report_path.name, report.model_dump(mode="json"))
    typer.echo(json.dumps(redactor.redact(report.model_dump(mode="json")), indent=2))
    if not report.passed:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
