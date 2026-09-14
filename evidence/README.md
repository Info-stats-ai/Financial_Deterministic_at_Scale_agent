# Demonstration evidence

All values belong to CloudCruise’s public synthetic automation demo. No real patient,
institution, account, or credential data is present.

This directory is the brief’s required pack: one discovery run, one reviewed artifact,
and replay logs for success plus exceptional states — plus scored eval and HITL.

## What the pack proves

- A real LLM **did** complete the UI goal (not a fake-model test).
- Replay **without** an LLM completes the same skill and returns typed fields.
- A missing member is a **business outcome**, not a crash.
- A bad password is a **hard failure** with expected/observed and a masked screenshot.
- The golden skill **beats** the live draft on contract gates (draft is not promoted).
- Failed login escalates on the **same** browser session (100 tracked cases).

## Pack

| Path | What it proves | Metric |
|---|---|---|
| `discovery/discovery-live/` | Genuine Anthropic computer-use | 15 actions, 68305 / 1054 tokens, `success` |
| `artifacts/lookup_patient_recent_claims.v1.json` | Reviewed golden skill | `approved_for_unattended_replay: true`, hash `sha256:6fc6…17a7` |
| `replay/replay-success/` | Model-free happy path | 6 steps, ~2.6s, `patient_status: Active` |
| `replay/replay-not-found/` | Exceptional business state | `PATIENT_NOT_FOUND`, `failure: null` |
| `replay/replay-hard-failure/` | Hard failure + evidence | `STEP_FAILED` at `sign-in`, masked PNG |
| `eval/lookup_patient_recent_claims.eval.json` | Reliability gates | 48 trials, composite **99.77**, all gates passed |
| `eval/discovery-live.contract.json` | Draft is not production | contract score 0.706, promotion **failed** |
| `eval/hitl-100/` | Same-session human recovery | 100/100 matched; 70 / 15 / 15; same context 100% |
| `fixtures/cloudcruise-healthcare.har` | Offline path | no live network fallback |

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

Computer-tool calls are in `events.jsonl`. Password keystrokes are `[REDACTED]`. The live
HAR has the public demo password stripped. `artifact.json` is a **draft**. Unattended
`capability invoke` uses the golden file after `evaluate --promote`.

## HITL pack

Failed login always goes `automation → pending_human` on the same Playwright context.
A simulated clerk then recovers, abandons, or resumes with another bad password.
See [eval/hitl-100/README.md](eval/hitl-100/README.md).
