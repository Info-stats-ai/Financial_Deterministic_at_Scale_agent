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
