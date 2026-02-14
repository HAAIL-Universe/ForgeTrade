# {PROJECT_NAME} — Blueprint (v0.1)

Status: Draft (authoritative for v0.1 build)
Owner: {OWNER_NAME}
Purpose: Define product fundamentals, hard boundaries, and build targets so implementation cannot drift.

---

## 1) Product intent

<!-- DIRECTOR: 1-3 paragraphs describing what the app does, who it's for,
     and the primary interaction model (chat-first, form-first, dashboard-first, API-only). -->

{PROJECT_NAME} is a {INTERACTION_MODEL} {SHORT_DESCRIPTION}.

---

## Core interaction invariants (must hold)

<!-- DIRECTOR: List the UX rules that must always be true. These are derived from
     the user's answers about interaction model, data mutation, and confirmation needs.
     Examples below — keep only what's relevant. -->

- {INVARIANT_1}
- {INVARIANT_2}
- {INVARIANT_3}

---

## 2) MVP scope (v0.1)

### Must ship

<!-- DIRECTOR: Numbered list of features the user described as essential.
     Each feature should be 1-2 sentences with enough detail that a builder
     knows what to implement without guessing. -->

1. **{FEATURE_1_NAME}**
   - {Feature 1 description}
2. **{FEATURE_2_NAME}**
   - {Feature 2 description}
3. **{FEATURE_3_NAME}**
   - {Feature 3 description}

### Explicitly not MVP (v0.1)

<!-- DIRECTOR: List things the user might expect but are NOT in scope.
     This prevents the builder from scope-creeping. -->

- {NOT_MVP_1}
- {NOT_MVP_2}
- {NOT_MVP_3}

---

## 3) Hard boundaries (anti-godfile rules)

<!-- DIRECTOR: Define the layer separation rules for this project's architecture.
     These must align with Contracts/boundaries.json. Adapt the layers below
     to match the actual stack (e.g., "controllers" instead of "routers" for Express). -->

### {LAYER_1_NAME} (e.g., Router/API layer)
- {What this layer does}
- {What this layer must NOT do}

### {LAYER_2_NAME} (e.g., Service layer)
- {What this layer does}
- {What this layer must NOT do}

### {LAYER_3_NAME} (e.g., Repository/DAL layer)
- {What this layer does}
- {What this layer must NOT do}

### {LAYER_4_NAME} (e.g., LLM wrapper — only if LLM is in stack)
- {What this layer does}
- {What this layer must NOT do}

---

## 4) Deployment target

<!-- DIRECTOR: Where and how the app runs. Derived from user answers about
     hosting, scale, and budget. -->

- Target: {DEPLOYMENT_TARGET}
- Expected users: {USER_SCALE}
- {Any deployment-specific constraints}
