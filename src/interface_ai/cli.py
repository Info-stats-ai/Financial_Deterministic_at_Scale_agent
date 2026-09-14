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
from interface_ai.core.session import SessionManager
from interface_ai.discovery.anthropic_client import ClaudeComputerClient
from interface_ai.discovery.loop import DiscoveryLoop, DiscoveryResult
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
) -> ReplayResult:
    surface = PlaywrightWebSurface(headless=False if operator_port else headless)
    if operator_port is None:
        return await ReplayEngine(
            surface,
            evidence_dir=evidence.run_dir,
            policy_gate=policy_gate,
        ).run(artifact, parameters, credentials=credentials)

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
            policy_gate=policy_gate,
            handoff=handoff,
        ).run(artifact, parameters, credentials=credentials)
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
    run_id = f"discovery-{uuid4().hex[:12]}"
    run_dir = Path("evidence/discovery") / run_id
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
    run_id = f"replay-{uuid4().hex[:12]}"
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
        )
    )
    evidence.write_json("result.json", result.model_dump(mode="json"))
    typer.echo(json.dumps(redactor.redact(result.model_dump(mode="json")), indent=2))
    if result.status.value not in {"success", "business_outcome"}:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
