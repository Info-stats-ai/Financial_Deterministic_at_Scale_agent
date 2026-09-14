# Demonstration evidence

All values belong to CloudCruise's public synthetic automation demo. No real patient,
institution, account, or credential data is present.

## Curated files

- `artifacts/lookup_patient_recent_claims.v1.json` — reviewed, hashed artifact used by
  production-style replay and `capability invoke`.
- `discovery/discovery-live/` — genuine Anthropic computer-use run (not a fake-model test).
- `replay/replay-success/` — model-free successful replay with redacted typed outputs.
- `replay/replay-not-found/` — expected `PATIENT_NOT_FOUND` business outcome, not a crash.
- `replay/replay-hard-failure/` — bad public-demo password producing a hard failure with
  expected/observed details and a masked screenshot.
- `fixtures/cloudcruise-healthcare.har` — test-only network fixture for offline replay.
  It contains the public demo's client bundle and synthetic fixture records.

## Live discovery (`discovery/discovery-live/`)

This directory is the required genuine LLM run. `result.json` reports real model token
usage (`input_tokens` / `output_tokens` > 0) and `events.jsonl` contains Anthropic
computer-tool calls. Password keystrokes are `[REDACTED]` in JSON/JSONL. The live HAR has
the public demo password string stripped; use the fixture HAR for offline replay.

```text
evidence/discovery/discovery-live/
  events.jsonl
  final.png
  final-semantic-snapshot.json
  network.har
  artifact.json
  result.json
```

`artifact.json` is a **draft** (`approved_for_unattended_replay: false`). Replay it to see
what the compiler emitted. Unattended production replay uses the reviewed golden file
under `artifacts/`.
