# HITL 100 — tracked login escalations

Failed automation login always requests human control of the **same** Playwright
`BrowserContext`. A simulated clerk then does one of three things.

| Mode | Count | Expected result |
|---|---|---|
| `recover` | 70 | Clerk types the real demo password; replay finishes `success` |
| `abandon` | 15 | Clerk never takes control; `intervention_required` / `HANDOFF_NOT_RESUMED` |
| `fail_again` | 15 | Clerk resumes with another bad password; `hard_failure` / `STEP_FAILED` |

This pack uses a hermetic HTML portal and short checkpoints. It does **not** hammer the
live CloudCruise demo (sign-in waits there are 10s × retries).

## Files

- `cases.json` — the 100 case definitions
- `ledger.jsonl` — one execution record per case (owners, same-session, status)
- `summary.json` — counts and pass/fail
- `samples/recover|abandon|fail_again/` — full `events.jsonl` + `result.json` for one of each mode

Re-run:

```bash
uv run capability evaluate-hitl
```
