# Architecture

**Situation.** Bank and credit-union servicing still runs on vendor UIs with no API.
Staff look up a member, read recent activity, and move on. The UI for a given product is
fairly stable. Calling an LLM to re-drive that screen on every request is the expensive
mistake: latency, cost, and non-determinism in a regulated path. Production needs a
**reusable capability**, not a chat.

**Task.** Build a small end-to-end record→replay system: a natural-language goal on a
real UI, a typed artifact, deterministic replay, same-session human handoff, and safety —
one concrete surface, contracts that could extend to other surfaces and tenants.

**Action.** Two different agents share one browser seam; they are not the same runtime.

- **Discovery agent (authoring).** `DiscoveryLoop` + Anthropic computer-use. Claude sees
  a screenshot and coordinates (no hidden clean-DOM shortcut). After each successful
  click, `LocatorHarvester` fingerprints the control. `ArtifactCompiler` emits a **draft**
  JSON skill with `{member_id}` and credential *names*. Model transcripts stay in
  evidence; they are never the replay source.
- **Replay engine (production).** `ReplayEngine` is a no-LLM interpreter. It does not
  import Anthropic. Same ordered steps: validate → allowlisted entry → unique locator
  (never 2-of-N) → `PolicyGate` → act → checkpoint → classify outcome.
- **Human clerk (escalation).** `SessionManager` + FastAPI console on `:8787`. One
  process owns Playwright and the console so handoff cannot split the session.

Stack: Python 3.11 async modular monolith, Pydantic v2 artifacts, Playwright Chromium,
Typer CLI, FastAPI/Uvicorn operator UI, YAML policy, HAR offline restage. The proxy
target is CloudCruise’s public synthetic claims portal (login → search → select → claims,
shuffled columns, no real PII) standing in for a multi-tenant vendor core.

**Result.**

- Discovery (control plane): 15 computer actions, 68,305 / 1,054 tokens, `success`
- Replay (data plane): ~2.6s happy path, 6 steps, no LLM
- Trade-off: one process = one failure domain — correct for this slice
- At scale: same ports, queue + one worker lease per live session; artifact contract unchanged

# Artifact schema

**Situation.** A successful Claude transcript proves one run. An upstream agent cannot
call a transcript with typed args. A servicing platform needs a **tool**, versioned and
reviewable.

**Task.** Emit a capability: ordered actions, how each control is identified (with
robustness reasoning), typed inputs/outputs, checkpoints, and outcome rules.

**Action.** The Pydantic v2 schema is the IR. It carries `schema_version`,
`capability_version`, capability id, target/vendor/version, typed parameters (JSON Schema
export), credential names, extraction rules (not remembered values), ranked locators
(`role_name` → label/text → css/xpath → coordinates), pre/postconditions, observation
rules, retry policy, and `safe|reversible|risky|irreversible`. Extra fields are forbidden.
Canonical JSON is hashed; load fails on tamper. Discovery writes
`approved_for_unattended_replay: false`. The reviewed golden finds a row by
`data-column='mrn'` and `{member_id}`, so shuffled columns do not matter. `catalog` /
`invoke` expose the skill by name; drafts are refused until eval `--promote`.

**Result.**

- Golden: contract **0.981**, locator quality **0.885**, 12 locators, parameterized, business rule present, 0 rank-1 coordinates
- Live draft: contract **0.706** — fails promotion (no `PATIENT_NOT_FOUND`, brittle CSS)
- Trade-off: strict schema costs migrations; silent extra fields are worse
- Promotion path: draft → reviewed → eval gates → `approved_for_unattended_replay`

# Determinism & error handling

**Situation.** Replay that only handles the happy path is useless. “No such member,”
validation, timeouts, and bad credentials are legitimate runtime states. Reviewers also
ask how the deterministic path is “trained.”

**Task.** Replay with no LLM in the decision loop. Verify checkpoints. Return outputs.
Separate expected business outcomes, recoverable conditions, and hard failures. Author the
skill without fine-tuning.

**Action — authoring (not training).** No gradient update. Claude discovers once. The
compiler writes draft JSON. A human reviews locators/outcomes. That JSON *is* the skill.
Later invocations never call Claude. A new version is a new discovery or a reviewed edit
plus a new hash — promoting a runbook, not retraining a model. Offline HAR restages the
site for scoring; it is not training data.

**Action — replay.** Validate params → open allowlisted URL → unique locator → policy →
one action → postcondition. Waits are bounded condition polls. Observation rules fire
first: missing MRN is `business_outcome` `PATIENT_NOT_FOUND` with `failure: null`.
Recoverable rules may retry/wait/dismiss/reauthenticate; exhaustion is not a crash.
Unknown UI → `hard_failure` with step, expected, observed, masked screenshot. Replay never
asks a model “is this an error?” Locator-tier mix is drift telemetry.

**Result.**

- Offline eval: 48 trials, composite **99.77**, `approve_unattended_replay`
- Happy path **8/8**, not-found **16/16**, invalid MRN **8/8**, bad password **8/8**, origin block **8/8**
- Identical successful outputs, **0** coordinate fallbacks, 0 unexpected policy denials, mean **4.5s**
- Committed: success (6 steps), `PATIENT_NOT_FOUND` (3 steps), hard-failure at `sign-in` + masked PNG
- Replay packages contain no Anthropic import; live draft fails the same gates on purpose

# Heterogeneity & multi-tenant

**Situation.** Surfaces include modern web, framesets, and native desktop. Hundreds of
institutions run ~20 apps; many share one vendor product with different branding and
versions. Re-recording per tenant does not scale.

**Task.** Implement one web surface, but keep a seam so artifact/replay/policy do not
assume Playwright selectors or one bank’s labels.

**Action.** `SurfaceDriver` is observe/act/snapshot. The artifact stores flow semantics
(step, checkpoint, outcome, risk). A desktop adapter would swap the driver, not the
schema. Reuse is a vendor **base** artifact (parameterized routes, semantic locators,
outcome rules), then version overlay, then tenant override. Overrides may change a label
or frame path; they must not silently weaken risk class. Bindings pin
`(content_hash, product_version)`. Drift signals: entry fingerprint, locator-tier mix,
outcome rates. Correlated coordinate fallback across tenants triggers vendor-level
re-discovery, not N copies. The CloudCruise demo is the stand-in vendor product.

**Result.**

- Only Playwright web is implemented — as the brief allows
- Replay does not embed tenant strings or DOM-only APIs in the contract
- Next overlay: demo layout-drift mode, not a second bank’s production core

# Escalation & handoff

**Situation.** Discovery can loop. Replay can hit an undeclared state. A risky click must
not be unattended. A **new** browser is not a handoff — cookies, CSRF, and the filled
login form live in the session.

**Task.** Detect stuck, route context, let a human use the same live session, resume,
record what they did. Full co-browsing video is out of scope.

**Action.** Stuck = deadline, step budget, repeated action, unchanged fingerprint, or
policy block. `InterventionRequest` carries capability/goal, step, URL, expected vs
observed, masked screenshot. Ownership is
`automation → pending_human → human → automation` (HTTP 409 on illegal jumps). The FastAPI
page mutates in-process `SessionManager`; the clerk uses the headed Playwright window.
Listeners log click/change without values. After resume, replay re-verifies the
postcondition. Tests assert `BrowserContext` object identity.

**Result.**

- Transfer protocol is real; operator UI is a mock
- HITL pack: **100** failed-login escalations on a hermetic portal (not live CloudCruise)
- **70** recover, **15** abandon (`HANDOFF_NOT_RESUMED`), **15** fail-again (`STEP_FAILED`)
- **100/100** same `BrowserContext`, all expected statuses matched
- Production next: worker lease, redacted remote view, fencing tokens
- Trade-off: in-memory ownership dies with the process

# Safety

**Situation.** This stands in for regulated financial operations. An agent that can click
can also leave the allowlist or persist secrets.

**Task.** Configurable allowlist; conservative risky/irreversible handling; never persist
credentials or raw PII in artifacts or logs.

**Action.** `config/policy.yaml` is fail-closed: exact origin, route regex, action types.
Checked before navigation and before every act. Page text is untrusted. Step risk class is
primary; regexes are defense in depth. Risky/irreversible requires human control. Artifacts
store `DEMO_PASSWORD`, not the value. `Redactor` runs on every JSON/JSONL write.
Screenshots mask inputs and known sensitive regions. Secret-scan tests skip `.env` and
fail on committed Anthropic keys.

**Result.**

- Policy-egress eval: **8/8** `ORIGIN_NOT_ALLOWED`
- Regex DLP is incomplete (live run over-matched `"provider"` inside an element id)
- Production needs isolated browsers, encryption, short retention, signed policy
- No real bank data in the repo

# Cuts

**Situation.** The brief grades a vertical slice and does not reward queues, clusters, or
multi-tenant plumbing.

**Task.** Touch every core requirement thinly-but-really; pick at most two stretches;
write next steps.

**Action.** Built: one web driver, filesystem artifacts, one-process handoff, **catalog +
invoke**, **evaluate + approval gate**, and a **100-case HITL ledger**. Not built: desktop
driver, OCR, distributed queue, registry DB, remote video co-browsing, tenant admin,
schema migration service, or bounded LLM repair during replay. Operator UI is minimal;
live compile stays a draft; HAR is a demo fixture.

**Result.**

- Genuine Claude run: `/evidence/discovery/discovery-live/`
- Production replay: eval-promoted golden hash `sha256:6fc6023896d060df027b0f9e598e9405843b715699ac1fd23b0c58fdb1f917a7`
- Unattended `invoke` refused for drafts
- Next: vendor-version overlay on the demo’s drift mode — then workers, not before
