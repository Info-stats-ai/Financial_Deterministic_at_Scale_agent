# Deterministic Computer-Use Capabilities

A servicing clerk’s job on a **legacy UI with no API**: log in, look up a member, read
recent claims, return typed fields. Today that is either a human clicking or an LLM
re-driving the screen on every request. This system does neither in production.

**Discover once with Claude. Compile a typed capability. Replay with no LLM.**

Public repo: https://github.com/Info-stats-ai/Financial_Deterministic_at_Scale_agent

The live target is CloudCruise’s **public synthetic** healthcare portal (fake credentials
`provider` / `claims123`). It stands in for a vendor core used by many banks and credit
unions. This repo is not affiliated with CloudCruise and contains **no real patient or
bank data**.

| File | Role |
|---|---|
| [REPORT.md](REPORT.md) | Design write-up — STAR under the brief’s seven headings |
| [evidence/](evidence/README.md) | Live discovery, golden artifact, three replay outcomes, eval, HITL |

## What is actually being automated

Not “an agent that chats about claims.” A **named, invocable skill**:
`lookup_patient_recent_claims`.

- **Who:** a back-office operator (or an upstream AI agent calling a tool).
- **Where:** a browser UI that will not grow a stable API.
- **Flow:** sign in → search by `{member_id}` → select the matching row → expand Recent
  Claims → extract `patient_status`, `latest_claim`, and related fields.
- **Inputs:** typed `member_id` (pattern `MRN-#####`), runtime credential *references*
  (`DEMO_USERNAME`, `DEMO_PASSWORD`) — never passwords stored in the skill.
- **Outputs:** declared JSON fields, or a **business outcome** (`PATIENT_NOT_FOUND`), or a
  **hard failure** with expected vs observed and a masked screenshot.

That is the production object. Chat is only used to *author* it.

## Two agents — how they are built, and how they differ

There is not one “AI agent.” There are two runtimes with opposite jobs.

| | **Discovery agent** (authoring) | **Replay engine** (production) |
|---|---|---|
| **What it is** | Claude computer-use loop | Deterministic interpreter |
| **How it is built** | `DiscoveryLoop` + Anthropic computer toolset. Sees screenshot + coordinates. No hidden “clean DOM” cheat. `LocatorHarvester` fingerprints the clicked control. `ArtifactCompiler` writes JSON. | `ReplayEngine`. Reads the artifact. Resolves ranked locators (exactly one match). Runs policy. Clicks/types. Checks checkpoints. Classifies outcomes. **Does not import Anthropic.** |
| **When it runs** | Once per capability version (or after vendor drift). | Every lookup. |
| **Decision maker** | Stochastic LLM. | The JSON artifact. No model call. |
| **Failure mode** | Stuck detector → same-session human. Compile is a **draft**. | `business_outcome` vs `hard_failure` vs handoff. Never “ask Claude if this looks like an error.” |
| **Cost** | 15 computer actions, 68,305 in / 1,054 out tokens on the committed live run. | ~2.5s happy path on the committed replay; mean 4.5s across 48 eval trials. |

A **third** actor is a human clerk, not an LLM: `SessionManager` + operator console at
`:8787`. Control is `automation → pending_human → human → automation` on the **same**
Playwright `BrowserContext`. Cookies and the login form stay put.

An **upstream** agent (another LLM, a workflow, a ticket bot) does not open the JSON. It
calls `capability catalog` / `capability invoke` with typed args. Drafts are refused until
eval promotion.

## Architecture

```text
                    authoring (slow, LLM)              production (cheap, no LLM)
                 ┌─────────────────────────┐        ┌──────────────────────────────┐
  natural-language goal                     │        │  catalog / invoke / CLI      │
                 ▼                          │        ▼                              │
  DiscoveryLoop ── Claude computer tools ───┼──► CapabilityArtifact (JSON + hash)  │
                 │                          │        │                              │
                 │ harvest locators         │        ▼                              │
                 │ compile draft            │     ReplayEngine                      │
                 └──────────┬───────────────┘        │ unique locator → policy      │
                            │                        │ → act → checkpoint           │
                            ▼                        │ → business / hard / handoff  │
                 human review + evaluate ────────────┘                              │
                            │                                                       │
                            ▼                                                       │
                 approved_for_unattended_replay                                     │
                                                                                    │
  shared: PlaywrightWebSurface  PolicyGate  SessionManager  EvidenceRecorder  :8787 │
```

- **CLI (`capability`)** — Typer entry: `discover`, `replay`, `catalog`, `invoke`,
  `evaluate`, `evaluate-hitl`.
- **SurfaceDriver** — perception/action seam. Only Playwright web is implemented; desktop
  would swap the driver, not the artifact schema.
- **PolicyGate** — fail-closed origin, route, action allowlist; risky/irreversible needs a
  human. Checked *before* the click.
- **Artifact** — the skill. Ranked locators, `{member_id}` templates, checkpoints,
  observation rules, risk class, SHA-256 integrity.
- **Evidence** — append-only JSONL through a redactor. Masked PNGs on failure.

Design write-up with trade-offs: [REPORT.md](REPORT.md).

## What we achieved (measured)

| Signal | Result | Where |
|---|---|---|
| Live Claude discovery | **success**, **15** computer actions, **68,305 / 1,054** tokens | `evidence/discovery/discovery-live/` |
| Golden replay | **success**, 6 steps, ~2.6s, typed outputs (redacted in logs) | `evidence/replay/replay-success/` |
| Missing member | `business_outcome` **`PATIENT_NOT_FOUND`**, `failure: null` | `evidence/replay/replay-not-found/` |
| Bad password | `hard_failure` + masked screenshot | `evidence/replay/replay-hard-failure/` |
| Offline eval | **48** trials, composite **99.77**, **all gates passed** | `evidence/eval/lookup_patient_recent_claims.eval.json` |
| Happy path | **8/8** success, identical output fingerprint, **0** coordinate fallbacks | same |
| Not-found | **16/16** `PATIENT_NOT_FOUND` | same |
| Attacks | invalid MRN, bad password, off-allowlist URL: **8/8** each | same |
| Locator quality | **0.885**; contract score **0.981**; draft compile **fails** promotion (0.706, no business rule) | golden vs `discovery-live.contract.json` |
| HITL pack | **100/100** tracked login escalations, **100%** same `BrowserContext` (70 recover, 15 abandon, 15 bad resume) | `evidence/eval/hitl-100/` |
| Tests | **36** passed (schema, replay, policy, handoff, eval, deliverable paths) | `uv run pytest -q` |

Replay is **scored, not trained**. There is no fine-tune. The JSON *is* the skill.
`--promote` sets `approved_for_unattended_replay` only if every gate passes.

## Tech stack

- **Language / runtime:** Python 3.11+, async, `uv`
- **Contracts:** Pydantic v2 (forbid extra fields), canonical JSON, SHA-256
- **Browser:** Playwright Chromium (`SurfaceDriver`)
- **Discovery LLM:** Anthropic Claude computer-use (`claude-sonnet-5` by default)
- **CLI:** Typer (`capability`)
- **Operator console:** FastAPI + Uvicorn + Jinja, in-process with the browser
- **Policy:** YAML allowlist (`config/policy.yaml`)
- **Eval / HITL:** replayed trials + simulated clerk on a hermetic HTML portal
- **Offline:** HAR restage (`not_found=abort`) — no silent live fallback
- **Quality:** pytest, ruff, mypy strict

Cuts (queues, k8s, desktop driver, co-browsing video): [REPORT.md](REPORT.md) § Cuts.

## Setup

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Anthropic API key with computer-use — **live discovery only**

```bash
git clone https://github.com/Info-stats-ai/Financial_Deterministic_at_Scale_agent.git
cd Financial_Deterministic_at_Scale_agent
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env
```

`.env` is gitignored. Set `ANTHROPIC_API_KEY` only to re-run live discovery. Demo
username/password are the public synthetic credentials from the demo site.

## Demo path: discover, then replay the resulting artifact

Required path: run the agent on a goal, then replay **the file it wrote**.

```bash
uv run capability discover \
  --goal "Log in to the synthetic claims portal. Search for member MRN-10042, select the matching patient, expand Recent Claims, and return outputs named patient_status and latest_claim. Do not open or submit a new claim." \
  --param member_id=MRN-10042 \
  --evidence-label live
```

Operator console: <http://127.0.0.1:8787>. Output:

```text
evidence/discovery/discovery-live/
  events.jsonl
  final.png
  artifact.json
  result.json
  network.har
```

A committed copy of that run is already in the repo (real token usage, computer actions,
redacted HAR). Then replay **that** compiled artifact — no LLM:

```bash
uv run capability replay \
  --artifact evidence/discovery/discovery-live/artifact.json \
  --param member_id=MRN-10042 \
  --evidence-label draft-replay
```

That compile is a **draft**. Locators are weaker than the reviewed golden file. Treat a
flake here as a review signal, not the production contract.

## Run without live services

No API key and no network fallback. The committed HAR serves recorded frontend responses
and aborts every unrecorded request.

```bash
uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-10042 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --evidence-label offline-success
```

## Production-style replay (reviewed artifact)

```bash
uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-10042 \
  --evidence-label live-success
```

Expected: `success`, six completed steps, typed outputs. Secrets are redacted in logs.

Not-found is a business outcome, not a crash:

```bash
uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-99999 \
  --evidence-label live-not-found
```

```json
{
  "status": "business_outcome",
  "outcome_code": "PATIENT_NOT_FOUND",
  "failure": null
}
```

## Reliability eval and unattended approval

```bash
uv run capability evaluate \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --repeats 8 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --offline-only
```

`--live-hitl` adds live-demo login recovery. One hundred tracked HITL failures on a
hermetic portal (does not hammer CloudCruise):

```bash
uv run capability evaluate-hitl
```

## Catalog and invoke

```bash
uv run capability catalog
uv run capability invoke \
  --name lookup_patient_recent_claims \
  --param member_id=MRN-10042 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --evidence-label catalog-invoke
```

`invoke` refuses drafts unless `--allow-draft`.

## Same-session human handoff

```bash
DEMO_PASSWORD=wrong-demo-value uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-10042 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --operator-port 8787 \
  --evidence-label handoff
```

Open <http://127.0.0.1:8787> → **Take control** → in the already-open Playwright window,
replace the password with `claims123` and sign in → **Resume automation**. Replay
re-verifies `Patients` on the same `BrowserContext`.

## Development

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

```text
src/interface_ai/
  artifact/     typed capability schema
  surface/      Playwright adapter behind SurfaceDriver
  discovery/    Claude loop → compiler
  replay/       no-LLM interpreter
  safety/       policy + redaction
  handoff/      same-session takeover
  eval/         reliability gates + HITL pack
  evidence/     JSONL recorder
config/         execution policy
evidence/       curated demonstration pack
tests/
docs/           learning journal (not the interview write-up)
```
