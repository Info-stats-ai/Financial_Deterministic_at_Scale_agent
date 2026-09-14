# Architecture

The system is an async Python modular monolith with explicit boundaries: `DiscoveryLoop`
owns stochastic authoring, `CapabilityArtifact` is the durable contract, `ReplayEngine`
owns deterministic execution, `PolicyGate` authorizes actions, `SessionManager` owns one
browser context, and `EvidenceRecorder` owns redacted persistence. A single process is the
right operational cut for this take-home: the browser and operator console share one event
loop and there is no distributed-session coordination. The modules are nevertheless ports
that can become services if load requires it.

Discovery uses Anthropic's GA `computer_toolset_20260801` with Claude Sonnet 5. Claude sees
screenshots plus a capped accessibility-oriented summary, then issues pixel-space mouse and
keyboard calls. Playwright executes them against CloudCruise United's third-party public
synthetic healthcare automation demo. This target was selected because it has a multi-step
login→search→select→claims flow, shuffled table columns, version/error variants, and no real
users or credentials. The system does not call the demo's API or inspect hidden DOM during
model decision-making.

The computer-use adapter captures the actual element under a successful coordinate action.
`LocatorHarvester` turns that fingerprint into ranked semantic, structural, and normalized-
coordinate candidates. `ArtifactCompiler` binds typed text to declared parameters or
runtime credential references; an unknown literal fails compilation. Raw model messages
remain evidence and never become the replay contract.

The architecture is intentionally asymmetric: discovery is a slow, model-backed control-
plane workflow; replay is a cheap data-plane interpreter with no LLM dependency. At scale,
requests would enter a durable queue, one browser worker would lease each run, artifacts
and rich evidence would live in object storage, and metadata would live in a relational
registry. Per-tenant concurrency limits, idempotency keys, worker fencing, and vendor-app
circuit breakers would be added without changing the artifact contract.

# Artifact schema

The Pydantic v2 artifact is an intermediate representation, not a transcript or generated
test script. It contains `schema_version` for structural compatibility,
`capability_version` for behavior changes, a stable capability ID, target application and
surface metadata, typed inputs, credential references, typed output extraction, ordered
steps, and a final checkpoint. Canonical JSON receives a SHA-256 content hash; loading
rejects edited or corrupted artifacts. Unknown fields are forbidden.

Each step declares an action, unique ID, description, ranked `LocatorStrategy` values and
their robustness reasoning, parameter/credential binding, preconditions, postconditions,
bounded retry policy, observation rules, and one of `safe`, `reversible`, `risky`, or
`irreversible`. Locators support accessible role/name, label, visible text, CSS, XPath,
frame path, and normalized coordinates. Parameter placeholders are validated everywhere,
including XPath, checkpoints, outputs, and URL templates. The reviewed artifact finds a row
by `data-column='mrn'` and `{member_id}`, so random column ordering is irrelevant.

Inputs export as strict JSON Schema, making the artifact directly usable as an agent tool
contract. Outputs declare type, sensitivity, and deterministic extraction rather than an
observed value. Credentials are names such as `DEMO_PASSWORD`; values are resolved only at
runtime. The artifact deliberately includes approval state metadata: discovery output is a
draft and does not become trusted unattended automation merely because it succeeded once.

Schema strictness creates migration cost, but silent interpretation changes are more
dangerous. A production registry would store immutable versions by hash, run pure schema
migrations, enforce backward compatibility in CI, and promote hashes through draft,
reviewed, canary, and approved states.

# Determinism & error handling

Replay validates inputs, opens the declared entry point, and processes the same ordered
state machine every time. For each step it checks preconditions, resolves locators by rank,
requires exactly one match, applies policy, executes one action, and verifies
postconditions. Ambiguous matches are never clicked arbitrarily. Waits poll declared
conditions; retries are bounded with exponential backoff and seeded timing jitter. The
overall success checkpoint must pass before typed outputs are extracted.

The result algebra separates `success`, `business_outcome`, `recoverable_exhausted`,
`hard_failure`, and `intervention_required`. A no-result row is declared as
`PATIENT_NOT_FOUND` and returns no failure. Recoverable rules may retry, wait, dismiss a
known element, request reauthentication, or escalate. Exhaustion remains distinguishable
from an undeclared broken locator. Hard failures include step ID/index, expected state,
observed state, and evidence paths.

Outcome meaning is explicit in the artifact; replay never asks a model to infer whether
page text is an error. This is less flexible than an LLM fallback but preserves the core
guarantee. Unknown states stop with evidence and become candidates for a reviewed artifact
version. Locator-tier selection in structured logs is also drift telemetry: movement from
role/name to XPath or coordinates lowers confidence before total failure.

The committed HAR provides a hermetic offline path with unrecorded requests aborted. It is
a test fixture, not production replay. Curated evidence includes a genuine Claude discovery
run, success, not-found, and a bad-login hard failure with masked screenshot. Simulated
discovery tests are not represented as that live evidence.

# Heterogeneity & multi-tenant

`SurfaceDriver` is the seam between capability semantics and computer mechanics. It exposes
lifecycle, observation, action, and snapshot contracts. `PlaywrightWebSurface` is the only
implementation here; it returns screenshot pixels, visible semantic nodes, frame metadata,
viewport, URL, and state fingerprint. A legacy-web adapter can add frameset traversal and
image/OCR resolution. A desktop adapter can use Windows UI Automation, macOS Accessibility,
or a remote-desktop coordinate driver while preserving step, checkpoint, outcome, policy,
and result contracts. Resolver implementations are surface-specific; recorded flow
semantics are not.

Cross-tenant reuse should start with a vendor-product base artifact, not copies. The base
contains canonical parameterized routes, actions, outcome rules, and semantic locators.
Resolution order would be base → vendor-version overlay → tenant override. Overrides may
change branding text, frame paths, or one locator, but not silently weaken risk policy.
Artifacts identify product version and content hash; a tenant binding pins the approved
combination.

Drift is detected through entry fingerprint, locator-tier usage, checkpoint failures,
outcome rates, and replay reliability by tenant/version. A version change first runs
read-only canaries. Compatible overlays are promoted centrally; a tenant-specific override
is the last resort. Repeated coordinate fallback or correlated failures across tenants
trigger vendor-level re-discovery instead of hundreds of separate recordings.

# Escalation & handoff

Discovery stops on deadline, step budget, repeated identical actions, unchanged state,
model error, or policy interception. Replay escalates after bounded automatic recovery and
before risky or irreversible actions. `InterventionRequest` carries run/capability, reason,
current step, URL, expected versus observed state, timestamp, and a masked screenshot.

Control is explicit: `automation → pending_human → human → automation`. The minimal FastAPI
console runs inside the same process and changes the same `SessionManager`; the operator
uses the already-open headed Playwright window. No new context is created. Illegal
transitions return HTTP 409, and automation asserts ownership before acting. While the
human owns control, injected listeners capture clicks and field-change events without
capturing entered values.

For a risky replay step, automation does not click. The human performs it and resumes;
replay then requires the step's postcondition before advancing. For an unrecoverable step,
the human may repair state; replay verifies the postcondition or gets one final bounded
attempt. Discovery receives a fresh screenshot of the human-modified session and continues
its model conversation. The integration test asserts object identity of the browser context
before and after handoff.

The console is deliberately not a production co-browsing system. Production would retain
one worker lease per run, route commands through a broker, stream a redacted remote-browser
view, persist control events, and use fencing tokens so stale workers cannot act.

# Safety

`config/policy.yaml` is a versioned, strict, fail-closed policy. Exact origins, full route
patterns, and action types are allowlisted. It is checked before opening an entry URL and
immediately before every discovery/replay action. Artifact risk class is primary; text
patterns are conservative defense in depth. Risky or irreversible actions require human
control rather than silent unattended execution.

The system treats webpage instructions as untrusted, bounds model actions/time, and blocks
navigation outside the allowlist. Credentials are runtime references. Before any JSON or
JSONL write, `Redactor` recursively removes sensitive keys, exact runtime parameter and
credential values, SSNs, tokens, API-key patterns, and sensitive URL parameters. Persisted
screenshots mask every input plus known sensitive result regions. Human field changes are
logged only as `value_was_entered=true`.

Screenshot masking cannot guarantee removal of arbitrary sensitive text, and regexes are
not a complete DLP system. Production therefore also needs isolated least-privilege browser
containers, encrypted evidence, tenant-scoped access, short retention, egress controls,
central policy signing, and audit review. The committed HAR contains only the third-party
demo's publicly published synthetic fixture records and login; no real user data is used.

# Cuts

The project implements one web surface, one local operator console, filesystem artifact
storage, and one-process session ownership. It does not build a desktop driver, OCR,
distributed queue, database registry, remote video co-browsing, tenant administration,
artifact migration service, or automatic LLM repair during replay. Those additions would
increase breadth without improving the evaluated vertical slice.

The operator UI is intentionally minimal; its transfer protocol is real. The reviewed
golden artifact is hand-authored to prove replay before model use; live discovery emits a
separate draft artifact. The HAR exists only for no-service demonstration. Real production
evidence, credentials, and regulated data are not included.

The one completed stretch is an agent-facing catalog: `capability catalog` exports typed
tool specs and `capability invoke` calls deterministic replay by name. Next I would add
approval/reliability scoring and a vendor-version overlay against the demo's version-drift
mode. Only then would I split queues/workers or build a richer React operator console.
Live Claude discovery evidence is in `evidence/discovery/discovery-live/`: token usage,
computer-tool events, a draft artifact, a masked final screenshot, and a redacted HAR.
That draft is not the production replay contract; the reviewed golden artifact is.
