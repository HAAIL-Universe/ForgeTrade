# {PROJECT_NAME} — Manifesto (v0.1)

This document defines the non-negotiable principles for building {PROJECT_NAME}.
If implementation conflicts with this manifesto, implementation is wrong.

---

## 1) Product principle: {PRIMARY_INTERACTION}-first, data-backed

<!-- DIRECTOR: State the primary interaction model and what "data-backed" means
     for this specific project. The LittleChef version said "chat-first, data-backed."
     Adapt this to the project: "form-first," "dashboard-first," "API-first," etc. -->

{PROJECT_NAME} is a {PRIMARY_INTERACTION}-first application that {WHAT_IT_CONTROLS}.

- {PRIMARY_INTERACTION} is the primary control surface.
- {SECONDARY_SURFACES} are display surfaces of the current truth.
- {HOW_EDITS_HAPPEN}

---

## 2) Contract-first, schema-first

{PROJECT_NAME} is built from contracts, not vibes.

- `physics.yaml` is the API specification and is canonical.
- {SCHEMA_TECHNOLOGY} schemas mirror the physics spec.
- If it's not in `physics.yaml`, it isn't real.

---

## 3) No godfiles, no blurred boundaries

Everything has a lane.

<!-- DIRECTOR: List the layers and their responsibilities.
     Must match both blueprint.md §3 and boundaries.json. -->

- **{LAYER_1}** — {responsibility}
- **{LAYER_2}** — {responsibility}
- **{LAYER_3}** — {responsibility}
- **{LAYER_4}** — {responsibility (if applicable)}

No layer is allowed to do another layer's job.
Violations are bugs, even if the feature works.

---

## 4) Auditability over cleverness

We value "debuggable and correct" over "magic and fast."

<!-- DIRECTOR: Define how data changes are tracked. Adapt to the project's
     data model — event sourcing, audit columns, change logs, etc. -->

- {HOW_STATE_CHANGES_ARE_TRACKED}
- {CORRELATION_OR_IDEMPOTENCY_RULES}
- A developer should be able to answer: "Why did this data change?"

---

## 5) Reliability over {DOMAIN_SPECIFIC_RISK}

<!-- DIRECTOR: Identify the main integrity risk for this project.
     For LittleChef it was "hallucination" (LLM fabricating recipes).
     For an e-commerce app it might be "incorrect pricing."
     For a medical app it might be "unsourced claims." -->

The system must be honest about {WHAT_IT_PRESENTS}.

- {INTEGRITY_RULE_1}
- {INTEGRITY_RULE_2}
- {FALLBACK_BEHAVIOR_WHEN_UNCERTAIN}

---

## 6) Confirm-before-write (default)

<!-- DIRECTOR: Define the data mutation pattern. Adapt the specifics
     to the project's interaction model. -->

{PROJECT_NAME} should not mutate user data based on ambiguous input.

Default flow for writes:
1. {HOW_MUTATION_IS_PROPOSED}
2. {HOW_USER_CONFIRMS}
3. {HOW_MUTATION_IS_APPLIED}
4. {WHAT_HAPPENS_ON_DECLINE}

<!-- DIRECTOR: If some operations are exempt from confirm-before-write
     (e.g., incrementing a view count, logging), list them here. -->

### Exempt from confirmation
- {EXEMPT_OPERATION_1 (if any)}

---

## 7) {ADDITIONAL_PRINCIPLE (if needed)}

<!-- DIRECTOR: Add project-specific principles here. Examples:
     - "Offline-first" for apps that must work without internet
     - "Privacy by default" for apps handling sensitive data
     - "Multi-tenancy isolation" for SaaS products
     Delete this section if not needed. -->
