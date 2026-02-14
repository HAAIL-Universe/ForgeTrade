# {PROJECT_NAME} — UI/UX Blueprint

Canonical UI/UX specification for this project. The builder contract (§1) requires reading this file before making changes. All frontend implementation must align with the layout, navigation, and component decisions defined here.

**If this project has no frontend (`stack.md` frontend.enabled = false), this file should state "N/A — API-only project" and nothing else.**

---

## 1) App Shell & Layout

<!-- DIRECTOR: Describe the overall page structure.
     What does the user see when they first load the app?
     Where are the main content areas? Is there a sidebar, header, footer?
     Mobile-first or desktop-first?
     
     Keep it simple — describe it like you're sketching on a napkin. -->

### Device priority
- **Primary:** {MOBILE / DESKTOP / BOTH_EQUAL}
- **Responsive strategy:** {MOBILE_FIRST_SCALE_UP / DESKTOP_FIRST_SCALE_DOWN}

### Shell structure
```
┌─────────────────────────────────────────┐
│  {HEADER / NAV BAR / NONE}              │
├──────────┬──────────────────────────────┤
│          │                              │
│ {SIDEBAR}│    {MAIN CONTENT AREA}       │
│ {or NONE}│                              │
│          │                              │
├──────────┴──────────────────────────────┤
│  {FOOTER / BOTTOM NAV / NONE}           │
└─────────────────────────────────────────┘
```

### Navigation model
- **Primary nav:** {TAB_BAR / SIDEBAR / HAMBURGER / TOP_NAV / NONE}
- **Navigation items:** {list the main nav destinations}

---

## 2) Screens / Views

<!-- DIRECTOR: List every distinct screen or view the user can navigate to.
     For each screen, describe:
     - What the user sees (content, data displayed)
     - What the user can do (actions, inputs)
     - How they got here (navigation path)
     
     Use simple language. Think "wireframe in words." -->

### Screen: {SCREEN_1_NAME} (e.g., Home / Dashboard / Chat)
- **Route:** `/{path}`
- **Purpose:** {What is this screen for?}
- **Content:**
  - {What data/content is displayed}
  - {What components are visible}
- **Actions:**
  - {What can the user do here}
- **Reached via:** {How the user navigates here}

### Screen: {SCREEN_2_NAME}
- **Route:** `/{path}`
- **Purpose:** {What is this screen for?}
- **Content:**
  - {Content description}
- **Actions:**
  - {User actions}
- **Reached via:** {Navigation path}

<!-- DIRECTOR: Repeat for each screen. MVP apps typically have 3-7 screens.
     Don't over-design — list only what's needed for the features in blueprint.md §2. -->

---

## 3) Component Inventory

<!-- DIRECTOR: List the reusable UI components the app needs.
     Don't list every HTML element — list the meaningful building blocks.
     
     Examples: chat bubble, item card, form input group, modal dialog,
     data table, status badge, action button, toast notification. -->

| Component | Used on | Description |
|-----------|---------|-------------|
| {COMPONENT_1} | {Screen(s)} | {What it looks like and does} |
| {COMPONENT_2} | {Screen(s)} | {What it looks like and does} |
| {COMPONENT_3} | {Screen(s)} | {What it looks like and does} |

---

## 4) Visual Style

<!-- DIRECTOR: Define the visual direction. Not a full design system — 
     just enough that the builder makes consistent choices.
     
     If the user said "I don't care how it looks," pick sensible defaults
     and note them as defaults. -->

### Color palette
- **Primary:** {COLOR_OR_VIBE} (e.g., "blue", "warm earth tones", "dark mode with green accents")
- **Background:** {LIGHT / DARK / SYSTEM_PREFERENCE}
- **Accent:** {COLOR_OR_VIBE}

### Typography
- **Font family:** {SYSTEM_DEFAULT / SPECIFIC_FONT / "clean sans-serif"}
- **Scale:** {COMPACT / COMFORTABLE / SPACIOUS}

### Visual density
- {MINIMAL — lots of whitespace, few elements per screen}
- {MODERATE — balanced information density}
- {DENSE — information-rich, dashboard-style}

### Tone
- {PROFESSIONAL / FRIENDLY / PLAYFUL / NEUTRAL}

---

## 5) Interaction Patterns

<!-- DIRECTOR: Define how the app responds to user actions.
     These are the UX micro-behaviors that the builder needs to implement consistently. -->

### Data loading
- {SKELETON_LOADERS / SPINNERS / PROGRESSIVE / INSTANT_PLACEHOLDER}

### Empty states
- {How screens look when there's no data yet}
- {What message/action is shown}

### Error states
- {TOAST_NOTIFICATION / INLINE_ERROR / ERROR_PAGE / MODAL}
- {Retry behavior}

### Confirmation pattern
- {MODAL_DIALOG / INLINE_CONFIRMATION / TOAST_WITH_UNDO / NONE}
- This must align with `manifesto.md` §6 (confirm-before-write)

### Responsive behavior
- {What changes between mobile and desktop}
- {What collapses, stacks, or hides}

---

## 6) User Flows (Key Journeys)

<!-- DIRECTOR: Describe the 2-4 most important user journeys step by step.
     These are the paths the builder must get right for MVP.
     
     Format: numbered steps, one action per step.
     Include what the user sees and what they do. -->

### Flow: {FLOW_1_NAME} (e.g., First-time setup, Core task, Key action)

1. User {action} → sees {result}
2. User {action} → sees {result}
3. User {action} → sees {result}
4. {Completion state}

### Flow: {FLOW_2_NAME}

1. User {action} → sees {result}
2. User {action} → sees {result}
3. {Completion state}

---

## 7) What This Is NOT

<!-- DIRECTOR: Explicitly state what the UI does NOT need.
     This prevents the builder from over-building. -->

- No {THING_NOT_NEEDED_1} (e.g., "No dark mode toggle in MVP")
- No {THING_NOT_NEEDED_2} (e.g., "No drag-and-drop")
- No {THING_NOT_NEEDED_3} (e.g., "No animations beyond CSS transitions")
