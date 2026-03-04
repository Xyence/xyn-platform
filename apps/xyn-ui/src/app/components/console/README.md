# Xyn Console (V1)

Xyn Console is a non-chat collaboration layer for governed intent resolution.

## Invocation
- Click the minimized `Xyn` node in the app shell.
- Keyboard shortcut: `Cmd+K` (macOS) or `Ctrl+K`.

## Behavior
- Sends intent to backend resolver (`/xyn/api/xyn/intent/resolve`).
- Renders structured `ResolutionResult` cards.
- Handles explicit apply transitions (`/xyn/api/xyn/intent/apply`).
- Supports options lookups (`/xyn/api/xyn/intent/options`).
- Persists the latest session state per context key (`artifact_id` or `global`).

## Non-chat constraints
- No transcript rendering.
- Only latest structured state is shown.
- Proposal apply is explicit and guarded.

## Extending renderers
- Add new `ResolutionResult.status` render blocks in `XynConsolePanel.tsx`.
- Keep rendering deterministic and action-centric.

## Language-driven form loop
- On artifact editor pages, Console receives `artifact_id`/`artifact_type` context and a live form snapshot.
- `resolve` uses snapshot context to propose diffs against current unsaved form state.
- `ProposedPatch` in editor context provides:
  - `Apply to form` (local unsaved mutation only)
  - `Apply & Save` (persist through `/xyn/api/xyn/intent/apply`)
- Missing fields can be focused directly from Console (`Focus field`), and options can be applied directly to form fields when editor context is active.
