# Deterministic Computer-Use Capabilities

**Discover once with Claude. Compile a typed capability. Replay with no LLM.**

- Public repo: https://github.com/Info-stats-ai/Financial_Deterministic_at_Scale_agent
- Design write-up (STAR, seven required headings): [REPORT.md](REPORT.md)
- Proof pack: [evidence/](evidence/README.md)
- Target: CloudCruise **public synthetic** healthcare portal (`provider` / `claims123`)
- Stand-in for a vendor core used by many banks and credit unions
- No real patient or bank data; this repo is not affiliated with CloudCruise

## Problem we solved

- Servicing still runs on **legacy UIs with no API**
- A clerk logs in, looks up a member, reads recent claims, copies a few fields
- Two bad options today:
  - humans click the same path thousands of times
  - an LLM re-drives the screen on **every** request (cost, latency, non-determinism)
- Production needs a **named, invocable skill**, not a chat that “tries the UI again”

## Task we are automating

- Capability name: `lookup_patient_recent_claims`
- Who: back-office operator, or an upstream agent calling a tool
- Where: a browser UI that will not grow a stable API
- Flow:
  - sign in
  - search `{member_id}`
  - select the matching patient row
  - expand Recent Claims
  - return typed fields
- Inputs: `member_id` (`MRN-#####`); credential *references* `DEMO_USERNAME` / `DEMO_PASSWORD` (values never stored in the skill)
- Outputs:
  - typed fields (`patient_status`, `latest_claim`, …), **or**
  - business outcome `PATIENT_NOT_FOUND` (`failure: null`), **or**
  - hard failure with expected vs observed + masked screenshot
- Chat is used only to **author** the skill, not to run it in production

## What we built

- End-to-end **record → compile → replay** system
- **Discovery agent** — Claude computer-use authors the skill once
- **Replay engine** — deterministic interpreter; **no LLM** on the lookup path
- **Human clerk** — same Playwright session (`:8787`), not a new browser
- **Catalog / invoke** — another agent calls the skill by name with typed args
- Policy allowlist, redaction, eval gates, HITL ledger
- Draft skills cannot run unattended until eval `--promote`

## First-go agent vs deterministic agent

### First go (authoring) — stochastic

- Runtime: `DiscoveryLoop` + Anthropic computer-use
- Sees screenshot + coordinates (no hidden “clean DOM” cheat)
- After each successful click, `LocatorHarvester` fingerprints the control
- `ArtifactCompiler` writes a **draft** JSON skill
- Committed live run: **15** computer actions, **68,305 / 1,054** tokens, status `success`
- Draft contract score **0.706** — **fails** promotion (no `PATIENT_NOT_FOUND` rule, brittle CSS)
- Use this path **once per skill version** (or after vendor drift)
- Do **not** put this on every member lookup

### Deterministic path (production) — no LLM

- Runtime: `ReplayEngine` (does **not** import Anthropic)
- Decision maker: the JSON artifact, not a model
- Same ordered steps: validate → allowlisted URL → unique locator (never 2-of-N) → policy → act → checkpoint → classify
- Happy path: **6** steps, ~**2.6s**
- Missing member: `business_outcome`, not a crash
- Bad password: `hard_failure` + masked screenshot
- Golden contract score **0.981**, locator quality **0.885**
- This is the path that **scales**

### Other actors

- Human: `automation → pending_human → human → automation` on the **same** `BrowserContext`
- Upstream agent: `capability catalog` / `capability invoke` — never opens the JSON file
- Drafts refused until eval promotion

## Business impact

- **Cost:** LLM tokens belong on authoring (one discovery), not on every lookup (~2.6s replay vs 68k-token computer-use run)
- **Latency / throughput:** a clerk or upstream bot can invoke a skill instead of waiting on a chat loop
- **Determinism:** same MRN → same outputs (eval output fingerprint = 1); auditors can replay the artifact
- **Exception hygiene:** “member not found” is a **business result**, not an incident; bad login / off-allowlist is a **hard failure** with evidence
- **Risk:** origin/route/action allowlist before every click; risky/irreversible needs a human; secrets never stored in the skill
- **HITL without session loss:** clerk takes the **live** browser (cookies, login form intact) — a new window is not a handoff
- **Multi-tenant path:** one vendor skill + overlays, not “re-record for every bank”
- **Unattended gate:** `approved_for_unattended_replay` only after measured gates (composite 99.77) — drafts cannot silently go to prod
- What this is **not**: a replacement for a real core API; it is how you automate the UI **until** that API exists, without betting production on a live LLM

## Evidence — what we did

- Genuine Claude discovery (not a fake-model test): `evidence/discovery/discovery-live/`
- Reviewed golden skill: `evidence/artifacts/lookup_patient_recent_claims.v1.json`
- Replay success: `evidence/replay/replay-success/`
- Exceptional state (not-found): `evidence/replay/replay-not-found/`
- Hard failure + masked PNG: `evidence/replay/replay-hard-failure/`
- 48-trial eval report: `evidence/eval/lookup_patient_recent_claims.eval.json`
- Draft fails promotion: `evidence/eval/discovery-live.contract.json`
- 100 same-session HITL cases: `evidence/eval/hitl-100/`
- Offline HAR (no live network): `evidence/fixtures/cloudcruise-healthcare.har`

## How we tested

- Unit / integration: `uv run pytest -q` (schema, replay, policy, handoff, eval, deliverable paths)
- Reliability gates: `uv run capability evaluate` (8 repeats × scenarios; `--promote` only if all gates pass)
- HITL pack: `uv run capability evaluate-hitl` (hermetic portal; does **not** hammer the live demo)
- Offline path: `--offline-har evidence/fixtures/cloudcruise-healthcare.har` (unrecorded requests abort)
- Secret scan: no committed Anthropic keys; `.env` gitignored
- Replay package grep: no `anthropic` import under `src/interface_ai/replay/`

## Results

- Live discovery: **success**, **15** computer actions, **68,305** input / **1,054** output tokens
- Golden replay: **success**, **6** steps, ~**2.6s**, typed outputs (redacted in logs)
- Not-found: `business_outcome` **`PATIENT_NOT_FOUND`**, `failure: null`
- Bad password: `hard_failure` at `sign-in` + masked screenshot
- Offline eval: **48** trials, composite **99.77**, **all gates passed**, recommend `approve_unattended_replay`
- Happy path: **8/8** success, **1** output fingerprint, **0** coordinate fallbacks
- Not-found: **16/16** `PATIENT_NOT_FOUND`
- Attacks: invalid MRN **8/8**, bad password **8/8**, off-allowlist URL **8/8**
- Locator quality **0.885**; golden contract **0.981**; live draft **0.706** (not promoted)
- HITL: **100/100** matched expected; **70** recover / **15** abandon / **15** fail-again; same `BrowserContext` **100%**
- Tests: **36** passed
- Mean eval duration: **4.5s** per trial

## Architecture

```text
  authoring (slow, LLM)                         production (cheap, no LLM)
  natural-language goal                         catalog / invoke / CLI
          │                                              │
          ▼                                              ▼
  DiscoveryLoop ── Claude computer tools ──► CapabilityArtifact (JSON + hash)
          │                                              │
          │ harvest + compile draft                      ▼
          ▼                                       ReplayEngine
  human review + evaluate                         unique locator → policy
          │                                       → act → checkpoint
          ▼                                       → business / hard / handoff
  approved_for_unattended_replay

  shared: PlaywrightWebSurface  PolicyGate  SessionManager  EvidenceRecorder  :8787
```

- **CLI** — `discover`, `replay`, `catalog`, `invoke`, `evaluate`, `evaluate-hitl`
- **SurfaceDriver** — observe / act / snapshot; only Playwright web in this slice
- **Artifact** — ranked locators, `{member_id}`, checkpoints, outcome rules, SHA-256
- **PolicyGate** — origin + route + action allowlist **before** the click
- **Evidence** — append-only JSONL through a redactor; masked PNGs on failure

Trade-offs and STAR write-up: [REPORT.md](REPORT.md)

## Tech stack — building the system

- Python 3.11+, async, `uv`
- Pydantic v2 contracts (forbid extra fields), canonical JSON, SHA-256
- Playwright Chromium (`SurfaceDriver`)
- Typer CLI (`capability`)
- FastAPI + Uvicorn + Jinja operator console (in-process with the browser)
- YAML policy (`config/policy.yaml`)
- HAR restage for offline replay (`not_found=abort`)
- pytest, ruff, mypy strict

## Tech stack — the agents

- **Discovery agent:** Anthropic Claude computer-use (`claude-sonnet-5` by default); screenshot + coordinate tools; stuck detector; locator harvest; compiler
- **Replay engine:** no model; ranked locators; checkpoint verifier; 3-way outcomes (`success` / `business_outcome` / `hard_failure`); bounded retries
- **Human operator:** FastAPI session state machine on the live `BrowserContext`
- **Upstream agent:** JSON tool spec from `catalog`; `invoke` is replay with an approval gate
- **Eval agent (simulated clerk):** hermetic HTML portal + `SimulatedClaimsOperator` for 100 HITL cases

## Future improvements

- Vendor-version overlay on the demo’s layout-drift mode (one base skill, per-version patches) — **next**
- Desktop `SurfaceDriver` (same artifact schema, different adapter)
- Worker lease / queue so many live sessions do not share one process
- Redacted remote view + fencing tokens for true distributed HITL
- Bounded, policy-checked single-step LLM repair on replay (never open-ended) — stretch, after the core stays clean
- Postgres-backed artifact registry (draft → canary → approved)
- Do **not** build next: k8s, multi-tenant plumbing, or “LLM on every click”

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

- `.env` is gitignored
- Set `ANTHROPIC_API_KEY` only to re-run live discovery
- Demo username/password are the public synthetic credentials from the demo site

## Demo path: discover, then replay the resulting artifact

- Required path: run the agent on a goal, then replay **the file it wrote**

```bash
uv run capability discover \
  --goal "Log in to the synthetic claims portal. Search for member MRN-10042, select the matching patient, expand Recent Claims, and return outputs named patient_status and latest_claim. Do not open or submit a new claim." \
  --param member_id=MRN-10042 \
  --evidence-label live
```

- Operator console: <http://127.0.0.1:8787>
- Output: `evidence/discovery/discovery-live/` (`events.jsonl`, `final.png`, `artifact.json`, `result.json`, `network.har`)
- Committed copy already in the repo (real tokens, computer actions, redacted HAR)

```bash
uv run capability replay \
  --artifact evidence/discovery/discovery-live/artifact.json \
  --param member_id=MRN-10042 \
  --evidence-label draft-replay
```

- That compile is a **draft** — weaker locators than the golden file; a flake here is a review signal, not the production contract

## Run without live services

- No API key
- No silent network fallback

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

- Expected: `success`, six completed steps, typed outputs (secrets redacted in logs)

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

- `invoke` refuses drafts unless `--allow-draft`

## Same-session human handoff

```bash
DEMO_PASSWORD=wrong-demo-value uv run capability replay \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --param member_id=MRN-10042 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --operator-port 8787 \
  --evidence-label handoff
```

- Open <http://127.0.0.1:8787>
- **Take control**
- In the already-open Playwright window, replace the password with `claims123` and sign in
- **Resume automation**
- Replay re-verifies `Patients` on the same `BrowserContext`

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
