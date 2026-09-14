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
