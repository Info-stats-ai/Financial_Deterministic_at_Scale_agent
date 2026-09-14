# Architecture

**Situation.** US bank and credit-union staff work in back-office apps with no API. The UI
for a given vendor product is fairly stable; the expensive mistake is calling an LLM on
every lookup. Production must invoke a reusable capability, not a chat.

**Task.** Build a small end-to-end record→replay system: natural-language goal, real UI
control, typed artifact, deterministic replay, same-session human handoff, and safety —
against one concrete surface, designed so the contracts could extend.

**Action.** I used an async Python modular monolith. `DiscoveryLoop` owns stochastic
authoring (Claude computer-use: screenshot + coordinates, no hidden DOM).
`CapabilityArtifact` is the durable contract. `ReplayEngine` is a no-LLM interpreter.
`PolicyGate`, `SessionManager`, and `EvidenceRecorder` own allowlisting, control, and
redacted logs. Playwright is the only `SurfaceDriver` implementation. One process owns the
browser and the operator console so handoff cannot split the session. The proxy target is
CloudCruise United's public synthetic claims portal (login → search → select → claims,
shuffled columns, no real PII). After each successful coordinate click, `LocatorHarvester`
fingerprints the real control and `ArtifactCompiler` binds typed `{member_id}` /
`DEMO_PASSWORD` references. Model transcripts stay in evidence; they are never the replay
source.

**Result / trade-off.** Discovery is a slow control plane; replay is a cheap data plane.
A single process is one failure domain and cannot fan out browsers — appropriate for this
slice. At scale, keep these module ports and put runs on a durable queue with one worker
lease per live session. The artifact contract would not change.

# Artifact schema

**Situation.** A successful Claude transcript is proof of one run, not a tool an upstream
agent can call with typed args.

**Task.** Emit a reviewable, versioned capability: ordered actions, how each control is
identified (with robustness reasoning), typed inputs/outputs, and a success checkpoint.

**Action.** The Pydantic v2 schema is an intermediate representation. It carries
`schema_version`, `capability_version`, capability id, target/vendor/version, typed
parameters (JSON Schema export), credential *names*, extraction rules (not remembered
values), ranked locators (`role_name` → label/text → css/xpath → normalized coordinates),
pre/postconditions, observation rules, retry policy, and `safe|reversible|risky|irreversible`.
Unknown fields are forbidden. Canonical JSON is hashed; load fails on tamper. Discovery
writes a draft (`approved_for_unattended_replay: false`). The reviewed golden locates a row
by `data-column='mrn'` and `{member_id}` so column shuffle is irrelevant.

**Result / trade-off.** Strictness costs migrations; silent extra-field interpretation is
worse. Production would promote hashes through draft → reviewed → canary → approved. The
live compile in `/evidence/discovery/` is the authoring output; the golden file is the
invocable contract.

# Determinism & error handling

**Situation.** Enterprise UIs change slowly. Replay that only handles the happy path is
useless: “no such member,” validation, dialogs, timeouts, and slow loads are legitimate
runtime states. Reviewers also ask how the deterministic path is “trained.”

**Task.** Replay the artifact with no LLM in the decision loop; verify checkpoints; return
outputs; classify expected business outcomes vs recoverable conditions vs hard failures.
Author the skill without fine-tuning weights.

**Action — authoring (not training).** No gradient update, no offline neural fit. Claude
discovers once (observe → decide → act). The compiler writes a draft JSON skill. A human
reviews locators/outcomes (the golden artifact). That JSON *is* the learned capability.
Later invocations never call Claude. A new version is a new discovery or a reviewed edit
plus a new hash — the same loop as promoting a runbook, not retraining a model. Offline
HAR replay is a hermetic *stage* for the already-authored skill; it is not training data.

**Action — replay.** Same ordered steps every time: validate params → open allowlisted
entry → unique locator match (never click 2-of-N) → policy → one action → postcondition.
Waits are condition polls with bounded exponential backoff. Declared observation rules
fire first: `PATIENT_NOT_FOUND` is `business_outcome` with `failure: null`. Recoverable
rules may retry, wait, dismiss, or reauthenticate; exhaustion is not a hard crash. Unknown
UI → `hard_failure` with step, expected, observed, masked screenshot. Replay never asks a
model “is this an error?” Locator-tier logs are secondary drift telemetry (role/name
falling to coordinates).

**Result.** Offline eval (5× happy path + 5× not-found, no LLM): 100% success, 100%
`PATIENT_NOT_FOUND`, identical outputs, 0 coordinate fallbacks, locator quality 0.885,
contract score 0.981, composite **99.81**. Report: `evidence/eval/lookup_patient_recent_claims.eval.json`.
The golden artifact is now `approved_for_unattended_replay`. The live discovery draft fails
those gates (no business rule; brittle CSS). Replay packages contain no Anthropic import.

# Heterogeneity & multi-tenant

**Situation.** Surfaces include modern web, frameset/legacy markup, and native desktop.
Hundreds of institutions run ~20 apps; many share one vendor product with different
branding and versions. Re-recording per tenant does not scale.

**Task.** Implement one web surface, but keep a seam so artifact/replay/policy do not assume
Playwright selectors or one bank's labels.

**Action.** `SurfaceDriver` is perception/action (observe, act, snapshot). The artifact
stores flow semantics (step, checkpoint, outcome, risk). A desktop adapter would swap the
driver, not the schema. Reuse is a vendor *base* artifact (parameterized routes, semantic
locators, outcome rules), then version overlay, then tenant override. Overrides may change
a label or frame path; they must not silently weaken risk class. Tenant bindings pin
`(hash, product_version)`. Drift: entry fingerprint, locator-tier mix, outcome rates.
Correlated coordinate fallback across tenants triggers vendor-level re-discovery, not N
copies.

**Result / trade-off.** Only Playwright web is implemented — as the brief allows. The
corner not painted: replay does not embed tenant strings or DOM-only APIs in the contract.

# Escalation & handoff

**Situation.** Discovery can loop; replay can hit an undeclared state; a risky click must
not be unattended. A fresh browser is not a handoff — cookies and dialogs live in the
session.

**Task.** Detect stuck, route context, let a human use the *same* live session, resume,
record what they did. Full co-browsing is out of scope.

**Action.** Stuck = deadline, step budget, repeated action, unchanged fingerprint, or
policy block. `InterventionRequest` carries capability/goal, step, URL, expected vs
observed, masked screenshot. Control is `automation → pending_human → human → automation`
(HTTP 409 on illegal jumps). The FastAPI page mutates in-process `SessionManager`; the
operator uses the headed Playwright window. Listeners log click/change without values.
After resume, replay re-verifies the postcondition; discovery re-observes with a fresh
screenshot. Tests assert `BrowserContext` object identity.

**Result / trade-off.** The transfer protocol is real; the UI is a mock. Production would
add a worker lease, redacted remote view, and fencing tokens. In-memory ownership dies
with the process.

# Safety

**Situation.** This is a stand-in for regulated financial operations. An agent that can
click can also navigate off-policy or persist secrets.

**Task.** Configurable allowlist; conservative risky/irreversible handling; never persist
credentials or raw PII in artifacts or logs.

**Action.** `config/policy.yaml` is fail-closed: exact origin, route regex, action types.
Checked before navigation and before every act. Page text is untrusted. Risk class on the
step is primary; regexes are defense in depth. Risky/irreversible requires human control,
not a silent click. Artifacts store `DEMO_PASSWORD`, not the value. `Redactor` runs on
every JSON/JSONL write. Screenshots mask inputs and known sensitive regions.

**Result / trade-off.** Regex DLP is incomplete (the live run over-matched `"provider"`
inside an element id). Production needs isolated browsers, encryption, short retention,
and signed policy. No real bank data is in the repo.

# Cuts

**Situation.** The brief grades a vertical slice and explicitly does not reward queues,
clusters, or multi-tenant plumbing.

**Task.** Touch every core requirement thinly-but-really; pick at most one stretch; write
next steps.

**Action.** Built: one web driver, filesystem artifacts, one-process handoff, catalog +
`invoke`, and `capability evaluate` (reliability gates + approval). Not built: desktop
driver, OCR, distributed queue, registry DB, remote video co-browsing, tenant admin,
schema migration service, or automatic LLM repair during replay. Operator UI is minimal;
live compile is a separate draft; HAR is a demo fixture.

**Result.** `/evidence/discovery/discovery-live/` is the genuine Claude run. Production
replay uses the eval-promoted golden artifact. Unattended `invoke` is refused for drafts.
Next: a vendor-version overlay on the demo's drift mode — then workers, not before.
