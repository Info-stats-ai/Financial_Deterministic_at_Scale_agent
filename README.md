# Deterministic Computer-Use Capabilities

Record a UI goal once with Claude. Compile a typed capability artifact. Replay it with
**no LLM in the decision path**.

This is a small end-to-end system: discovery → artifact → deterministic replay →
policy → same-session human handoff → evidence. The target is CloudCruise's **public
synthetic** healthcare demo (fake credentials `provider` / `claims123`). This repository
is not affiliated with CloudCruise and contains no real patient or banking data.

**Public repository:** https://github.com/Info-stats-ai/Financial_Deterministic_at_Scale_agent

| Read first | What it is |
|---|---|
| [REPORT.md](REPORT.md) | Design write-up (exact seven headings from the brief) |
| [evidence/](evidence/README.md) | Live discovery, golden artifact, success / not-found / hard-failure replay, eval, HITL pack |

## Setup

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- An Anthropic API key with Claude computer-use access — **live discovery only**

```bash
git clone https://github.com/Info-stats-ai/Financial_Deterministic_at_Scale_agent.git
cd Financial_Deterministic_at_Scale_agent
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env
```

`.env` is gitignored. Set `ANTHROPIC_API_KEY` only if you re-run live discovery. The
committed demo username/password are the public synthetic credentials from the demo site.

## Demo path: discover, then replay the resulting artifact

This is the required end-to-end path: run the agent on a goal, then replay **the file it
wrote**.

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

A committed copy of that run is already in the repo (real Anthropic token usage, computer
actions, redacted HAR). Then replay **that** compiled artifact — no LLM:

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

Replay is scored, not trained. `--promote` sets `approved_for_unattended_replay` only if
every gate passes.

```bash
uv run capability evaluate \
  --artifact evidence/artifacts/lookup_patient_recent_claims.v1.json \
  --repeats 8 \
  --offline-har evidence/fixtures/cloudcruise-healthcare.har \
  --offline-only
```

Committed report: `evidence/eval/lookup_patient_recent_claims.eval.json` (composite 99.77,
48 offline trials). `--live-hitl` adds same-session login recovery against the live demo.

One hundred tracked HITL login failures (hermetic HTML, not the live site):

```bash
uv run capability evaluate-hitl
```

Ledger and three inspectable samples: `evidence/eval/hitl-100/`.

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

## Artifact contract

The JSON artifact includes schema/capability versions and a SHA-256 hash; target metadata;
typed inputs (JSON Schema) and credential *names*; extraction rules; ranked locators with
robustness reasoning; checkpoints; business / recoverable / hard outcome rules; retry
policy; and `safe|reversible|risky|irreversible`. Replay requires a locator to match
exactly one element. The golden file anchors parameterized XPath to `data-column` names so
shuffled columns do not break row selection.

## Safety

`config/policy.yaml` is checked before navigation and before every act: origin + route
allowlist, action allowlist, risky/irreversible requires human control, credentials are
references, JSON/JSONL is redacted, failure screenshots are masked.

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
