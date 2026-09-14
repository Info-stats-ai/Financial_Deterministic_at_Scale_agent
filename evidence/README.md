# Demonstration evidence

All values belong to CloudCruise's public synthetic automation demo. No real patient,
institution, account, or credential data is present.

Read this directory as the brief's required pack: one discovery run, one reviewed
artifact, and replay logs for success plus an exceptional state.

## Pack

| Path | What it proves |
|---|---|
| `artifacts/lookup_patient_recent_claims.v1.json` | Reviewed golden artifact (`approved_for_unattended_replay: true`) |
| `discovery/discovery-live/` | Genuine Anthropic computer-use run (not a fake-model test) |
| `replay/replay-success/` | Model-free successful replay |
| `replay/replay-not-found/` | `PATIENT_NOT_FOUND` business outcome, not a crash |
| `replay/replay-hard-failure/` | Bad demo password → hard failure + masked screenshot |
| `eval/lookup_patient_recent_claims.eval.json` | 48 offline trials, composite 99.77, all gates passed |
| `eval/discovery-live.contract.json` | Static score of the live draft (fails promotion) |
| `eval/hitl-100/` | 100 tracked same-session login escalations |
| `fixtures/cloudcruise-healthcare.har` | Offline replay fixture (no live network) |

## Live discovery

```text
evidence/discovery/discovery-live/
  events.jsonl
  final.png
  final-semantic-snapshot.json
  network.har
  artifact.json
  result.json
```

`result.json` reports real model token usage. Computer-tool calls are in `events.jsonl`.
Password keystrokes are `[REDACTED]`. The live HAR has the public demo password stripped.

`artifact.json` is a **draft** (`approved_for_unattended_replay: false`). Unattended
`capability invoke` uses the golden file after `evaluate --promote`.

## HITL pack

Failed login always goes `automation → pending_human` on the **same** Playwright context.
A simulated clerk then recovers, abandons, or resumes with another bad password.
See [eval/hitl-100/README.md](eval/hitl-100/README.md).
