# Demonstration evidence

All values belong to CloudCruise's public synthetic automation demo. No real patient,
institution, account, or credential data is present.

## Curated files

- `artifacts/lookup_patient_recent_claims.v1.json` — reviewed, hashed artifact used by replay.
- `replay/replay-success/` — model-free successful replay with redacted typed outputs.
- `replay/replay-not-found/` — expected `PATIENT_NOT_FOUND` business outcome, not a crash.
- `replay/replay-hard-failure/` — bad public-demo password producing a hard failure with
  expected/observed details and a masked screenshot.
- `fixtures/cloudcruise-healthcare.har` — test-only network fixture for offline replay.
  It contains the public demo's client bundle and synthetic fixture records.

## Live discovery evidence status

The discovery implementation and fake-model Chromium integration test are complete, but a
genuine Anthropic run must not be fabricated. Run the README's discovery command after
placing `ANTHROPIC_API_KEY` in `.env`; it creates:

```text
evidence/discovery/discovery-<id>/
  events.jsonl
  final.png
  final-semantic-snapshot.json
  network.har
  artifact.json
  result.json
```

That directory is valid live evidence only when `result.json` reports real model token
usage and `events.jsonl` contains Anthropic computer-tool calls.
