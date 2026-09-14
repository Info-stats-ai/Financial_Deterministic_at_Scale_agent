# Build and System-Design Learning Journal

This document records the engineering reasoning behind each phase. It is intentionally
separate from `REPORT.md`: the report is the concise interview deliverable, while this is
the deeper learning trail.

## Phase 0 — Durable learning context

### Challenge

The project is both a working take-home and a curriculum. Explanations given only in one
chat are transient and cannot guide later sessions.

### Options considered

1. Keep the teaching contract only in chat.
2. Put it in the project repository.
3. Store the durable user preference separately and keep project-specific lessons here.

### Decision and reasons

Use two scopes: the personal agent store contains the durable teaching preference, and
this file contains project decisions. This mirrors a backend split between user-profile
configuration and domain data.

### Trade-off and bottleneck

Maintaining a journal adds documentation work and can drift from the code. We control that
by updating it at phase boundaries, after behavior is verified.

### Scale path

In a multi-user product, preferences belong in a versioned profile service. Project
decisions belong in repository-owned architecture decision records (ADRs), reviewed with
the code they describe.

## Phase 1 — Foundation and architecture shape

### Challenge

The system needs a live browser, an LLM loop, deterministic replay, an operator HTTP
surface, and evidence collection. Splitting these too early into services would introduce
network failure modes and make same-session browser ownership harder.

### Options considered

1. One script: fastest initially, but tightly coupled and hard to test.
2. Microservices: independently scalable, but excessive deployment and coordination cost.
3. Async modular monolith: one runtime with explicit internal boundaries.

### Decision and reasons

Use Python 3.11+ with asyncio as a modular monolith. Pydantic defines contracts, Playwright
owns the browser, Anthropic drives discovery, FastAPI exposes handoff, and pytest protects
load-bearing behavior. One event loop can pause automation while still serving the operator
console, and one process owns the browser context.

### Implementation

- `pyproject.toml` pins runtime and development dependency ranges and exposes one CLI.
- `.env.example` documents secret references without committing values.
- `config/policy.yaml` makes network, action, risk, and redaction policy explicit.
- `.gitignore` separates curated redacted evidence from runtime artifacts.
- The project is an isolated git repository with the requested GitHub remote.

### Trade-off and bottleneck

A single process has finite browser and CPU capacity and is one failure domain. That is an
appropriate cut for a take-home because the brief rewards boundaries, not premature
infrastructure.

### Scale path

Keep the module contracts and place run requests on a durable queue. Workers each own a
bounded pool of browser sessions; a run is sticky to one worker for its lifetime. Store
artifacts and evidence in object storage, run metadata in a database, and publish control
events through a broker. Idempotency keys prevent duplicate capability invocations.

### Concepts learned

Modular monolith, bounded contexts, process ownership, session affinity, configuration
boundaries, secret hygiene, and evolutionary architecture.

## Phase 2 — Artifact as a durable contract

### Challenge

A successful model transcript is evidence of one run, not a reusable capability. Raw
coordinates, prose, and model reasoning cannot tell a deterministic executor which inputs
are valid, what outputs to return, which outcomes are legitimate, or how to prove success.

### Options considered

1. Persist the model transcript and ask another model to replay it.
2. Generate Playwright source code directly.
3. Compile discovery into a typed, surface-aware intermediate representation.

### Decision and reasons

Use strict Pydantic models as a versioned intermediate representation. The contract has
typed inputs and outputs, credential references, ordered steps, ranked locator strategies
with reasoning, pre/postconditions, business-outcome rules, retry policy, risk class, and
an overall success checkpoint. It exports a JSON Schema that an upstream agent can use as
a tool contract.

The artifact is model-independent and the replay path never needs discovery reasoning.
Secrets are referenced by environment-variable name; values are never serialized.

### Implementation

- Unknown fields are rejected instead of silently ignored.
- Cross-field validators catch duplicate IDs, invalid action shapes, unknown parameter
  placeholders, unknown credential references, and ambiguous locator ranks.
- `schema_version` controls structural compatibility; `capability_version` controls
  behavioral evolution.
- Canonical JSON is hashed with SHA-256. Loading verifies the hash, detecting accidental
  edits or tampering.
- Tests prove serialization round trips, hash verification, strict tool input schema, and
  invalid-contract rejection.

### Trade-off and bottleneck

Strict contracts make evolution deliberate. Adding or changing a required field needs a
migration rather than an ad hoc edit. That cost is desirable for replay reliability, but a
large artifact registry would need compatibility tooling.

### Scale path

Store immutable artifact versions in object storage and index metadata in a registry.
Publish schema migrations as pure functions, enforce backward-compatibility in CI, approve
specific hashes for unattended use, and route invocations by capability version. This is
the same discipline used for public APIs and event schemas.

### Concepts learned

Intermediate representations, design by contract, schema evolution, semantic versioning,
canonical serialization, integrity hashing, backward compatibility, and agent tool schemas.

## Phase 3 — Surface abstraction and computer perception

### Challenge

Discovery must act from human-visible evidence even when markup is hostile, while replay
needs machine-resolvable targets. Letting every module call Playwright directly would bind
the artifact, policy, and handoff logic to one browser library and make desktop extension
mostly fictional.

### Options considered

1. Expose Playwright objects throughout the application.
2. Design a large universal automation API covering every platform feature.
3. Define a small protocol around observation, action, snapshot, and lifecycle.

### Decision and reasons

Use a narrow `SurfaceDriver` protocol. The web adapter returns a screenshot, an
accessibility-oriented semantic snapshot, frame metadata, viewport size, URL/title, and a
state fingerprint. Discovery acts with normalized coordinates; after acting, the adapter
fingerprints the element under the point so stronger replay locators can be harvested.

### Implementation

- `Observation` combines pixels and semantics; neither is assumed sufficient alone.
- The semantic snapshot includes visible controls, roles, labels, text, and bounding boxes
  across reachable frames.
- `SurfaceAction` normalizes navigate, click, type, select, wait, extract, and dialog
  dismissal.
- Actions return duration, before/after URL, extracted value, and target fingerprint.
- Closing the browser context flushes an optional HAR for reproducible offline use.
- A real Chromium test proves observation, coordinate typing/clicking, element
  fingerprinting, and state-change detection.

### Trade-off and bottleneck

The protocol intentionally exposes a common subset. Browser-only features may require
adapter extensions. Screenshots are token-heavy for an LLM, and semantic snapshots can be
large on dense legacy pages, so discovery must cap and summarize observations.

The first test found that a label and input can share the same accessible name. That is
normal, not an edge case: names alone are ambiguous. Replay therefore resolves role plus
name and requires exactly one match.

### Scale path

Add web-frame and desktop accessibility implementations behind the same protocol. Assign
drivers through a factory keyed by surface type. Browser workers enforce per-run session
affinity and resource limits. Store large screenshots/HARs outside event records and pass
content-addressed references through the system.

### Concepts learned

Dependency inversion, ports and adapters, multimodal perception, session ownership,
content-addressed state fingerprints, resource bounding, and interface segregation.

## Phase 4 — Deterministic replay

### Challenge

Recorded clicks are not deterministic. Elements can be duplicated, rendering can be slow,
and an action can return without producing the intended state. Replay must make no model
decision yet still degrade through known target strategies and explain exactly where it
stopped.

### Options considered

1. Generate and execute a Playwright script.
2. Replay recorded coordinates and fixed delays.
3. Interpret the artifact with a bounded state machine.

### Decision and reasons

Use an interpreter. For each step it validates preconditions, walks locators by rank,
requires exactly one match, performs the declared action, waits on explicit conditions,
and validates postconditions. It checks a final success checkpoint before extracting typed
outputs. The replay package does not import the Anthropic client.

### Implementation

- Input parameters are checked for missing/unknown names, runtime type, and regex pattern.
- Locator resolution supports role/name, label, text, CSS, XPath, frame hints, and
  normalized coordinates as last resort.
- Ambiguous candidates do not cause an arbitrary click; the resolver continues to the next
  strategy and fails with every attempted tier if none is unique.
- Retry count is bounded. Backoff and seeded timing jitter avoid synchronized retries while
  preserving a predictable decision path.
- Every failure includes step ID/index, expected state, observed state, and screenshot path.
- Output extraction converts declared string, integer, number, money, date, and boolean
  values only after the overall checkpoint passes.
- Chromium integration tests prove successful replay and ranked fallback.

### Trade-off and bottleneck

An interpreter is more code than a generated script, but centralizes semantics and policy.
Web locator resolution currently belongs to the web runtime; a desktop runtime will need
its own resolver. Coordinate fallback cannot verify semantic state by itself and should
lower confidence.

### Scale path

Replay workers need no GPU or model quota. They can autoscale on queue depth and be pooled
by vendor application. Store each step transition as an append-only event, use invocation
idempotency keys, cap concurrency per tenant, and apply circuit breakers when a vendor
application is unhealthy.

### Concepts learned

Interpreter pattern, finite-state execution, idempotency, condition-based waits, exponential
backoff, jitter, circuit breakers, unique-match invariants, and typed result contracts.

## Phase 5 — Runtime outcome taxonomy

### Challenge

An expected “patient not found” answer, a temporarily unavailable service, and a broken
locator are operationally different. Returning all three as exceptions makes upstream
agents retry business answers and hides recoverable incidents.

### Options considered

1. Return success or exception only.
2. Infer error meaning from arbitrary page text at runtime.
3. Declare known observation rules and recovery behavior in the artifact.

### Decision and reasons

Use explicit artifact rules. Each rule names a stable code, deterministic checkpoint,
classification, and recovery action. The engine never guesses whether text is a business
outcome. Results distinguish `success`, `business_outcome`, `recoverable_exhausted`,
`hard_failure`, and `intervention_required`.

### Implementation

- Business outcomes stop cleanly with a code and message, without a failure object.
- Recoverable states have their own bounded retry policy and may wait, retry, dismiss a
  known element, request reauthentication, or escalate.
- Exhausted recovery returns `recoverable_exhausted`, not a hard failure.
- Undeclared exceptions, locator exhaustion, and checkpoint mismatch are hard failures.
- Tests prove that no-result and exhausted-transient states have different contracts and
  that a richer failure screenshot is captured.

### Trade-off and bottleneck

Known states must be modeled per vendor product. That is intentional: guessing semantics
with an LLM during replay would violate determinism. Unknown states escalate with evidence
and can become reviewed rules in the next artifact version.

### Scale path

Maintain a vendor-level outcome-rule library inherited by tenant artifacts. Aggregate
outcome codes and recovery exhaustion rates. Promote frequently observed unknown states
through review, canary the new artifact version, and roll back by immutable version hash.

### Concepts learned

Algebraic result types, domain errors versus technical failures, bounded recovery,
dead-letter handling, canary releases, and closed-loop artifact improvement.

## Phase 6 — Policy enforcement and redaction

### Challenge

Safety guidance in an LLM prompt is not enforcement. A model can misunderstand it, and
replay has no model prompt at all. Checking logs after execution also cannot undo an
unauthorized click or leaked credential.

### Options considered

1. Prompt-only restrictions.
2. Duplicate checks inside discovery and replay.
3. One fail-closed policy gate immediately before every action, plus redaction at writes.

### Decision and reasons

Use a shared `PolicyGate`. It allows only configured origins, routes, and action types.
Risk class is declared in the artifact, while text-pattern detection provides a conservative
second signal. Risky or irreversible actions are allowed only after human approval;
disallowed network/action scope stops execution.

### Implementation

- YAML policy is strictly validated and versioned.
- URL checks parse and compare origins instead of using unsafe prefix matching.
- Routes use full regular-expression matching.
- Replay validates the entry URL before opening a browser and every action immediately
  before execution.
- `Redactor` recursively scrubs sensitive keys, SSNs, bearer tokens, API-key patterns, and
  sensitive URL query values before persistence.
- Credential values are runtime inputs referenced by name in the artifact.
- Tests prove allowed/blocked origin and route behavior, risk escalation, recursive
  redaction, and fail-closed replay before navigation.

### Trade-off and bottleneck

Regex risk detection can produce false positives and cannot understand every visually
implied consequence. The artifact's explicit risk class is primary; pattern detection is
defense in depth. Screenshot redaction can only mask known sensitive fields and cannot
guarantee removal of arbitrary text rendered elsewhere, so access controls and retention
limits still matter.

### Scale path

Resolve a tenant policy version at run admission, cache a signed snapshot with the run, and
enforce it locally for the run lifetime. Central policy management supports review and
rollout; workers fail closed if no valid policy is available. Publish every verdict to an
immutable audit stream without storing the sensitive action payload.

### Concepts learned

Policy enforcement points, fail-closed authorization, defense in depth, configuration
versioning, data-loss prevention, least privilege, audit logs, and TOCTOU avoidance.

## Phase 7 — Bounded LLM discovery and artifact compilation

### Challenge

An LLM is useful precisely because the first run is uncertain, but uncertainty cannot leak
into production replay. The discovery loop also processes untrusted pixels and page text,
incurs model cost, and can repeat actions forever without explicit limits.

### Options considered

1. Give Claude DOM selectors and persist its transcript.
2. Ask Claude to generate Playwright source code.
3. Let Claude use the UI visually, record successful targets, and compile a typed artifact.

### Decision and reasons

Use Anthropic's GA `computer_toolset_20260801` with Claude Sonnet 5. The model receives a
screenshot plus a bounded accessibility-oriented summary and returns official computer
member calls. Playwright executes coordinates after policy checks. A custom completion tool
provides structured success evidence, but the artifact compiler—not the model—owns schema
construction.

### Implementation

- The loop has wall-clock and action budgets, catches model errors, supports batched calls
  in order, and returns a result for every member call as required by the API contract.
- Repeated identical actions or unchanged UI states trigger stuck escalation.
- Page instructions are explicitly treated as untrusted; final consequential actions are
  forbidden by prompt and independently intercepted by policy.
- Element fingerprints from successful coordinate actions become ranked semantic,
  structural, and coordinate locator candidates.
- Click-then-type pairs compile into parameter or credential bindings. Unknown literal
  typed text fails compilation instead of leaking into the artifact.
- Output values locate elements only during compilation; the saved extraction locators do
  not persist those observed values.
- JSONL model/action evidence is append-only and all runtime credentials and parameter
  values are removed before writes.
- A fake-model Chromium integration test proves the complete goal-to-artifact loop without
  pretending it is the required real evidence run.

### Trade-off and bottleneck

Computer use adds roughly thousands of tool-definition tokens per model turn and screenshot
latency dominates. Semantic summaries are capped to control context size. Compilation is
conservative: ambiguous outputs or unbound typed values stop for review rather than
producing a weak artifact.

The code path is verified, but the mandatory genuine run remains blocked until an
`ANTHROPIC_API_KEY` is provided locally. Simulated tests are labeled as tests and will not
be presented as live evidence.

### Scale path

Discovery is an authoring/control-plane workload, not the production data plane. Queue it
separately, enforce per-user budgets, isolate browsers in short-lived sandboxes, require
artifact review/approval, and measure compiler rejection and locator-tier quality. Replay
remains a separate cheap worker pool with no model access.

### Concepts learned

Agent loops, client toolsets, tool-result protocols, prompt injection boundaries, control
plane versus data plane, compilation, conservative failure, token budgeting, and sandboxing.

## Phase 8 — Same-session escalation and human control

### Challenge

Creating a ticket or opening a fresh browser is not a handoff. Cookies, transient dialogs,
form state, and the exact failure context live inside one browser context. Automation and a
human must never act concurrently, and automation must not trust “done” without checking.

### Options considered

1. Emit an intervention event and terminate.
2. Start a replacement browser for an operator.
3. Pause one owned session, transfer explicit control, then resume after verification.

### Decision and reasons

Use a three-state ownership machine: `automation`, `pending_human`, and `human`. A
`SessionManager` owns the existing `PlaywrightWebSurface`. The FastAPI operator console
runs in the same process, so its take-control/resume commands mutate the same in-memory
ownership state instead of trying to reconstruct browser state elsewhere.

### Implementation

- `InterventionRequest` includes run/capability, reason, current step, URL, expected versus
  observed state, timestamp, and a screenshot from the live session.
- The operator console exposes current ownership and only permits legal transitions,
  returning HTTP 409 for invalid ones.
- While the owner is human, injected page listeners record clicks and changes without
  recording entered values.
- Risky replay steps are not executed by automation. A human performs them, resumes, and
  replay verifies the declared postcondition before advancing.
- After automatic retries are exhausted, replay offers the same session for recovery, then
  rechecks postconditions or makes one final bounded retry.
- Discovery can hand off on no progress or policy interception, then sends the model a new
  screenshot of the human-modified session and continues.
- Integration tests prove that the browser context object is identical before and after
  handoff, that human actions are captured, and that replay succeeds only after checkpoint
  verification.

### Trade-off and bottleneck

The local operator controls the headed browser window; this is intentionally not a full
remote co-browsing product. In-memory ownership means the run and console share one process.
That is the simplest real implementation of the required seam, but a crashed worker loses
the live browser unless the browser itself is remotely hosted.

### Scale path

Give each run a lease held by one browser worker. Route operator commands through a broker
to that worker, stream a redacted view through a remote-browser gateway, and persist
control-transition events durably. Lease expiry prevents two workers from controlling the
same session; heartbeats and fencing tokens prevent stale owners from acting.

### Concepts learned

Finite-state machines, mutual exclusion, session affinity, leases, fencing tokens,
human-in-the-loop control planes, event capture, and post-handoff invariant verification.

## Phase 9 — Evidence, failure forensics, and offline replay

### Challenge

A successful terminal message is not auditable evidence, and a third-party demo may be
offline when a reviewer runs the project. Evidence must be useful for debugging without
leaking entered values, while offline replay must never silently fall back to the network.

### Options considered

1. Save only console output.
2. Mock the entire application.
3. Record structured events plus masked screenshots and a network HAR fixture.

### Decision and reasons

Use append-only JSONL for event timelines, JSON for caller result contracts, masked PNGs
for failure state, and a Playwright HAR for network-isolated replay. The HAR adapter uses
`not_found="abort"`, proving an unrecorded request fails rather than reaching the internet.
The same reviewed artifact runs live and against the fixture.

### Implementation

- Replay records start, step, policy, selected locator tier/reasoning, action completion,
  business outcome, success, and detailed failure events.
- Evidence correlation uses one explicit run ID through CLI, engine, filenames, and logs.
- Sensitive parameters and credential values are registered before the first write.
- All input fields and known sensitive result regions are masked in persisted screenshots.
- Three curated replay cases exist: success, `PATIENT_NOT_FOUND`, and a wrong-password hard
  failure with masked screenshot and expected/observed details.
- The golden artifact uses parameterized XPath anchored to semantic table-column names, so
  shuffled columns do not affect the selected row.
- An automated test replays the full artifact from the committed HAR with live network
  fallback disabled.

### Trade-off and bottleneck

HAR files are relatively large and couple tests to captured frontend assets. They are test
fixtures, not production replay. The bundled third-party JavaScript contains only the
vendor's public synthetic test records and demo login; artifacts and logs contain no raw
values. Attempts to text-rewrite minified code were rejected because they corrupted
identifiers and reduced reproducibility.

### Scale path

Send event envelopes to an append-only stream, store screenshots/traces in encrypted object
storage, and retain only content-addressed references in run metadata. Apply tenant-specific
retention, access control, legal hold, and deletion policy. Sample successful rich evidence
while retaining complete failure evidence, with regulated fields masked before upload.

### Concepts learned

Correlation IDs, structured logging, append-only events, forensic evidence, data retention,
network virtualization, hermetic tests, content masking, and test-versus-production boundaries.

## Phase 10 — Agent-facing catalog

### Challenge

A capability that only exists as a file path is not how an upstream agent should work. The
caller needs a name, a typed input schema, and a deterministic result. If invoke re-enters
discovery, production becomes expensive and non-deterministic.

### Decision and reasons

Add a thin catalog over hashed artifact files. `list_tools()` exports the same JSON Schema
the artifact already owns. `invoke` resolves a name to a path and calls replay. There is no
new execution engine and no model in the production path.

### Scale path

Replace the filesystem directory with a registry service: artifact blob in object storage,
metadata and approval state in Postgres, and `invoke` as an idempotent API. The contract
stays the same.

### Concepts learned

Service catalogs, tool/function calling, facade pattern, and separating discovery (write
path) from invocation (read path).
