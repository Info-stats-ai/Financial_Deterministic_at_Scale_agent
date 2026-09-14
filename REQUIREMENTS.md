# Requirements Traceability Matrix

This file prevents silent scope loss. A requirement is complete only when its implementation,
automated verification, and demonstration evidence are all present.

| Requirement | Implementation | Verification | Evidence | Status |
|---|---|---|---|---|
| Natural-language goal + target intake | `src/interface_ai/cli.py`, `discovery/loop.py` | discovery tests | discovery JSONL | Implemented; live evidence pending |
| Real LLM observe-decide-act loop | `discovery/`, `surface/` | bounded-loop tests + live run | screenshots and discovery JSONL | Implemented; API key/live evidence pending |
| No-clean-DOM bias | screenshot coordinates + semantic snapshot in `surface/` | surface tests | live run | Implemented; live evidence pending |
| Typed, versioned artifact contract | `artifact/schema.py`, `artifact/io.py` | `test_artifact_schema.py` | saved artifact JSON | Implemented; evidence pending |
| Ordered actions + locator reasoning | `CapabilityStep`, `LocatorStrategy` | schema and resolver tests | saved artifact JSON | Implemented; replay pending |
| Typed inputs and outputs | `ParameterSpec`, `OutputSpec` | schema tests | artifact + result | Implemented; evidence pending |
| Per-step and final checkpoints | `Checkpoint` + replay verifier | replay tests | replay result | Schema done; replay pending |
| Deterministic replay without LLM | `replay/engine.py` | golden replay test | success replay JSONL | Implemented; evidence pending |
| Stable targeting and fallbacks | `replay/locator_resolver.py` | uniqueness/cascade tests | selected-tier events | Implemented; evidence pending |
| Validation/runtime error handling | `replay/outcomes.py` | scenario tests | error replay | Implemented; evidence pending |
| Business outcome vs recoverable vs hard failure | result and outcome contracts | taxonomy tests | three replay results | Implemented; evidence pending |
| Structured success/failure result | `ReplayResult` | contract tests | `result.json` | Implemented; evidence pending |
| Domain/route/action allowlist | `safety/policy.py` + `config/policy.yaml` | policy tests | policy events | Implemented; evidence pending |
| Safe/reversible/risky/irreversible classes | artifact + policy gate | policy tests | risky-step handoff | Implemented; handoff pending |
| No persisted secrets or raw PII | credential references + redaction writer | redaction tests + repository scan | redacted logs/shots | Implemented; final scan pending |
| Structured action-and-reason logs | `evidence/recorder.py` | discovery/redaction tests | JSONL | Implemented; curated evidence pending |
| Rich failure signal | masked surface snapshot | failure test | masked screenshot | Implemented |
| Discovery stuck detection | `discovery/stuck.py` | state-progression tests | intervention event | Implemented; handoff pending |
| Unrecoverable replay escalation | replay + handoff | integration test | intervention event | Implemented; curated evidence pending |
| Risky-step escalation | safety + handoff | integration test | handoff log | Implemented; curated evidence pending |
| Same-session human takeover and return | session state machine + operator UI | handoff integration test | human action events | Implemented; curated evidence pending |
| Clear control ownership | `ControlOwner` state machine | transition tests | ownership events | Implemented |
| Legacy web/desktop extension seam | `SurfaceDriver` protocol | protocol conformance test | `REPORT.md` design | In progress |
| Multi-tenant reuse and drift design | artifact metadata + report | document check | `REPORT.md` | Planned |
| Real discovery evidence | live Claude run | evidence validator | `/evidence/discovery/` | Planned |
| Successful replay evidence | deterministic live/offline run | evidence validator | `/evidence/replay/replay-success/` | Complete |
| Exceptional replay evidence | deterministic no-result and bad-login runs | evidence validator | `/evidence/replay/replay-not-found/`, `replay-hard-failure/` | Complete |
| Offline/no-live-services path | HAR-backed demo mode | offline integration test | README command | Implemented; README pending |
| README exact setup/demo commands | `/README.md` | command smoke test | repository root | Planned |
| REPORT exact seven headings | `/REPORT.md` | heading validation test | repository root | Planned |
| Public GitHub repository | configured `origin` | remote and clean-tree checks | public URL | Pending authentication |

## Explicit acceptance gates

- Discovery evidence must contain at least one genuine Anthropic API response and real UI action.
- Replay code must not import or call the Anthropic client.
- Human takeover must retain the exact `BrowserContext`; opening a replacement session fails.
- Every persisted event passes through redaction.
- Runtime retries are bounded; no infinite loop or unbounded LLM agent loop is allowed.
- `REPORT.md` must have exactly the seven headings and order required by the brief.
- The final repository scan must find no API key, token, credential value, or raw synthetic PII.
