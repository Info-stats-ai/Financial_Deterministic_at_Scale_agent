# Deterministic Computer-Use Capabilities

A small end-to-end record→replay system for legacy applications without APIs:

1. Claude operates a real UI from screenshots and coordinates.
2. Successful actions are compiled into a typed, versioned capability artifact.
3. Replay interprets that artifact deterministically with no LLM calls.
4. Policy, runtime outcomes, evidence, and same-session human takeover are first-class.

The primary target is CloudCruise United's **third-party public synthetic automation demo**.
This repository is not affiliated with CloudCruise and contains no real patient or banking
data.

## Architecture at a glance

```text
CLI
 └─ Orchestrator
     ├─ DiscoveryLoop ── Claude computer toolset ──┐
     ├─ ReplayEngine (no LLM)                     ├─ PlaywrightWebSurface
     ├─ PolicyGate + Redactor                     │
     ├─ HandoffController + Operator Console ─────┘
     └─ EvidenceRecorder ── JSONL / JSON / masked PNG / HAR
```

`SurfaceDriver` is the web/desktop seam. The artifact, policy, and replay contracts do not
depend on model transcripts. See [REPORT.md](REPORT.md) for decisions and
[LEARNING.md](LEARNING.md) for the phase-by-phase system-design journal.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- An Anthropic API key with Claude computer-use access for **live discovery only**

```bash
git clone https://github.com/Info-stats-ai/Financial_Deterministic_at_Scale_agent.git
cd Financial_Deterministic_at_Scale_agent
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env
```

For live discovery, set `ANTHROPIC_API_KEY` in `.env`. The committed demo username/password
are public synthetic credentials published by the demo site, not private secrets.

## Demo 1: genuine LLM discovery

This is the non-negotiable live run. Claude receives the screenshot and accessibility-
oriented observation, chooses computer actions, and drives the public UI. The action path
is policy-checked and bounded by step and wall-clock limits.

```bash
uv run capability discover \
  --goal "Log in to the synthetic claims portal. Search for member MRN-10042, select the matching patient, expand Recent Claims, and return outputs named patient_status and latest_claim. Do not open or submit a new claim." \
  --param member_id=MRN-10042 \
  --evidence-label live
```

The operator console is available at <http://127.0.0.1:8787> during the run. Output:

```text
evidence/discovery/discovery-live/
  events.jsonl
  final.png
  final-semantic-snapshot.json
  network.har
  artifact.json
  result.json
```

The repository must not claim completion of this requirement unless that directory contains
real Anthropic token usage and computer-tool calls. A fake-model integration test exists
only for repeatable CI.

## Demo 2: deterministic replay

Replay a reviewed artifact against the live demo. There is no Anthropic import or model
call in the replay decision path.

```bash
uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-10042 \
  --evidence-label live-success
```

Expected status: `success`, six completed steps, and typed outputs. Sensitive output values
are returned internally but redacted from persisted logs and terminal evidence.

## Demo 3: business outcome, not a crash

```bash
uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-99999 \
  --evidence-label live-not-found
```

Expected result:

```json
{
  "status": "business_outcome",
  "outcome_code": "PATIENT_NOT_FOUND",
  "failure": null
}
```

## Demo 4: run without live services or an API key

The committed HAR serves recorded frontend responses and aborts every unrecorded network
request. It does not silently fall back to the internet.

```bash
uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-10042 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --evidence-label offline-success
```

No `ANTHROPIC_API_KEY` is needed. The public demo credentials remain in `.env`.

## Demo 5: agent-facing capability catalog

An upstream agent should not open a JSON file. It should discover a named tool with a
typed input schema, then invoke it.

```bash
uv run capability catalog
uv run capability invoke \
  --name lookup_patient_recent_claims \
  --param member_id=MRN-10042 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --evidence-label catalog-invoke
```

`catalog` prints the tool/function-calling contract. `invoke` is a thin wrapper over
deterministic replay, so production callers never enter the discovery loop.

## Demo 6: same-session human handoff

Start with a deliberately wrong synthetic password:

```bash
DEMO_PASSWORD=wrong-demo-value uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-10042 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --operator-port 8787 \
  --evidence-label handoff
```

After bounded replay failure:

1. Open <http://127.0.0.1:8787>.
2. Click **Take control**.
3. In the already-open Playwright browser, replace the password with `claims123` and sign in.
4. Click **Resume automation** in the console.
5. Replay verifies the `Patients` checkpoint in the same `BrowserContext`, then continues.

Human clicks/changes are logged without entered values. The integration test asserts that
the browser-context object is identical before and after handoff.

## Artifact contract

The JSON artifact includes:

- schema and capability versions plus a canonical SHA-256 hash;
- target application/surface metadata;
- typed input parameters and JSON Schema export;
- credential references without credential values;
- typed outputs and deterministic extraction rules;
- ordered actions with ranked locators and robustness reasoning;
- preconditions, postconditions, and an overall success checkpoint;
- declared business/recoverable/hard outcome rules;
- retry policy and safe/reversible/risky/irreversible classification.

Replay requires a locator candidate to match exactly one element. The reviewed demo artifact
anchors its parameterized XPath to semantic `data-column` names, so randomly shuffled table
columns do not affect row selection.

## Safety and evidence

`config/policy.yaml` is enforced in discovery and replay immediately before actions:

- exact origin and full route allowlist;
- action-type allowlist;
- risky/irreversible steps require human control;
- runtime credentials are references, never artifact values;
- JSON/JSONL persistence always passes through redaction;
- failure screenshots mask inputs and known sensitive regions.

Curated outputs are documented in [evidence/README.md](evidence/README.md).

## Development checks

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

Tests cover schema integrity, parameterized locator fallback, replay success and outcomes,
policy/redaction, real Chromium actions, bounded discovery with a fake model, same-session
handoff, operator state transitions, and network-isolated HAR replay.

## Repository layout

```text
src/interface_ai/
  artifact/     typed capability schema and integrity-checked persistence
  surface/      browser-neutral protocol and Playwright adapter
  discovery/    Claude loop, stuck detection, locator harvesting, compiler
  replay/       locator resolver, checkpoints, outcome classifier, engine
  safety/       policy gate and recursive redaction
  handoff/      intervention contracts, controller, operator console
  evidence/     append-only structured recorder
config/         versioned execution policy
evidence/       reviewed artifact, replay runs, masked failure, offline HAR
tests/          unit and browser integration coverage
```
