# Prompt Affordance UX

Epic E adds a thin interpretation-transparency layer on top of Epic D. The UI does not parse prompts on its own. It renders a backend-derived `PromptInterpretation` object returned by `/xyn/api/xyn/intent/resolve`.

## Shipped Scope

Epic E is shipped as an interpretation-transparency layer for the supported Epic D prompt families:
- app operations
- development work
- run supervision

Users can see what Xyn detected before execution or dispatch:
- action
- target
- resolved fields
- capability state
- execution mode
- clarification or blocked state

Accepted bounded fallback:
- the console keeps the existing textarea
- recognized elements are shown in a preview-adjacent strip instead of inline rich-token highlighting
- legacy non-Epic-D prompt paths show an explicit unavailable/legacy preview state rather than pretending to support full structured affordances

## Contract

Backend types:
- `xyn_orchestrator.intent_engine.types.PromptInterpretation`
- `xyn_orchestrator.intent_engine.types.PromptInterpretationAction`
- `xyn_orchestrator.intent_engine.types.PromptInterpretationTarget`
- `xyn_orchestrator.intent_engine.types.PromptInterpretationField`
- `xyn_orchestrator.intent_engine.types.PromptInterpretationCapabilityState`
- `xyn_orchestrator.intent_engine.types.PromptInterpretationSpan`

Frontend mirrors:
- `apps/xyn-ui/src/api/types.ts`

The minimum interpretation shape is:

- `intent_family`
- `intent_type`
- `target_entity`
- `target_record`
- `target_work_item`
- `target_run`
- `action`
- `fields`
- `execution_mode`
- `confidence`
- `needs_clarification`
- `capability_state`
- `clarification_reason`
- `clarification_options`
- `resolution_notes`
- `missing_fields`
- `recognized_spans`

## Backend Mapping

The mapping seam is:
- `xyn_orchestrator.xyn_api._prompt_interpretation_from_intent(...)`

It derives `PromptInterpretation` directly from the Epic D `IntentEnvelope`. The UI must treat that object as authoritative and must not add a second prompt-understanding path.

## Rendering Path

The prompt preview path is:
- `apps/xyn-ui/src/api/xyn.ts` via `previewXynIntent(...)`
- `apps/xyn-ui/src/app/state/xynConsoleStore.tsx`
- `apps/xyn-ui/src/app/components/console/PromptInterpretationPreview.tsx`

Current behavior:
- initial prompt typing triggers a preview-only resolve request
- preview responses do not write prompt activity
- preview uses a debounced request path and suppresses stale out-of-order responses
- preview errors fall back to an explicit unavailable interpretation summary instead of leaving stale affordances on screen
- explicit common navigation/list commands may resolve through a deterministic fast path first
- broader natural-language phrasing falls through to backend intent resolution
- both paths must converge into the same canonical executable result shape, so direct open/view actions do not degrade into `DraftReady` unless the intent actually requires drafting
- the prompt card renders:
  - action
  - target
  - fields
  - capability state
  - execution mode
  - confidence
  - clarification state

## Acceptance Matrix

The current shipped affordance coverage is:

- App operations
  - pre-execution preview: yes
  - capability boundary rendering: yes
  - clarification blocking: yes
  - backend execution guard: yes
  - activity interpretation summary: yes
- Development work
  - pre-dispatch preview: yes
  - queued/work-item execution mode: yes
  - clarification blocking: yes
  - backend execution guard: bounded by Epic D resolve/apply contract
  - activity interpretation summary: yes
- Run supervision
  - pre-action preview: yes
  - review/hold execution mode: yes
  - clarification blocking: yes where Epic D marks ambiguity
  - backend execution guard: bounded by Epic D resolve/apply contract
  - activity interpretation summary: yes

## Capability States

Capability state is backend-derived and rendered explicitly:

- `enabled`
- `known_but_disabled`
- `unknown`
- `unavailable`

`known_but_disabled` is used for manifest-known but currently undeclared entities such as a generated app prompt that references `interfaces` before interfaces are declared. The preview may expose an alternative such as `propose_app_evolution`.

## Execution Modes

The normalized execution modes are:

- `immediate_execution`
- `queued_run`
- `work_item_creation`
- `work_item_continuation`
- `awaiting_clarification`
- `awaiting_review`
- `blocked`

These are rendered before submission so the user can see whether Xyn will mutate data immediately, queue runtime work, create/continue work, wait for clarification, or stop.

## Backend Execution Guards

Prompt affordance UX is not enforced only in the browser.

For Epic D-backed generated app CRUD:
- `/xyn/api/xyn/intent/resolve` returns `intent` and `prompt_interpretation`
- `/xyn/api/xyn/intent/apply` re-resolves the raw prompt before execution
- clarification-required prompts are rejected with `IntentClarificationRequired`
- known-but-disabled entities are rejected with `UnsupportedIntent`

This keeps ambiguous or blocked requests from executing even if a client bypasses UI submit controls.

For non-Epic-D legacy flows:
- the UI may still surface a prompt result summary
- but it does not invent `PromptInterpretation`
- the preview clears old structured affordances and shows an explicit unavailable/legacy state instead

## Examples

App operation:
- prompt: `create a device called r1 in St. Louis`
- expected interpretation:
  - `intent_family = app_operation`
  - `intent_type = create_record`
  - `target_entity.key = devices`
  - `fields = [{name: "name", value: "r1"}, ...]`
  - `execution_mode = immediate_execution`

Development work:
- prompt: `continue Epic D implementation using the current plan`
- expected interpretation:
  - `intent_family = development_work`
  - `intent_type = create_and_dispatch_run`
  - `target_work_item.label = Epic D`
  - `execution_mode = queued_run`

Run supervision:
- prompt: `pause here and wait for review`
- expected interpretation:
  - `intent_family = run_supervision`
  - `intent_type = pause_or_hold`
  - `execution_mode = awaiting_review` or `awaiting_clarification` depending on resolution context

Ambiguity:
- prompt: `continue the work`
- expected interpretation:
  - `needs_clarification = true`
  - `clarification_reason = ambiguous_target`
  - `clarification_options` populated when candidates are available

Unsupported or legacy path:
- prompt: `build a new app`
- expected preview behavior:
  - no `PromptInterpretation`
  - preview shows an explicit unavailable/legacy summary
  - no stale recognized-elements strip remains from the previous prompt

## Conversation Summaries

Conversation/activity summaries use the same `prompt_interpretation` object:
- `apps/xyn-ui/src/app/components/activity/AgentActivityDrawer.tsx`

They render a compact interpretation summary from backend data only.

## Deferred Follow-ons

Non-blocking Epic E follow-ons:
- reduce the remaining React `act(...)` warning noise in the broader console harness without changing Epic E behavior
- keep a small acceptance matrix note like the one above aligned with tests as Epic D/E behavior evolves
- watch for resolve/apply semantic drift by keeping `PromptInterpretation`, `execution_mode`, and clarification semantics centralized

Broader post-Epic-E UX work:
- consider a future rich-input architecture if inline token highlighting becomes worth the added complexity
- migrate preserved legacy non-Epic-D prompt paths onto `PromptInterpretation` when those flows are modernized
- revisit broader console affordances for predictive help, suggestions, or advanced editing only after later epic priorities justify it
- improve broader DB-backed and full-console regression stability so future UX work can rely on wider suites

## Debugging

Fastest backend checks:
- inspect `IntentEnvelope` generation in `intent_engine/engine.py`
- inspect `PromptInterpretation` mapping in `_prompt_interpretation_from_intent(...)`
- inspect `/xyn/api/xyn/intent/resolve` responses for the `intent` and `prompt_interpretation` fields

Fastest frontend checks:
- inspect `session.previewResolution` in `XynConsoleStore`
- inspect `PromptInterpretationPreview` props
- inspect `AgentActivityDrawer` rendering for `prompt_interpretation`
- inspect preview request sequencing in `XynConsoleStore` when debugging stale typing results

If the UI and backend disagree:
1. verify `prompt_interpretation` is present in the resolve response
2. verify the frontend is using that field, not reconstructing intent from text
3. verify capability state came from the installed manifest path rather than a local heuristic
4. verify the latest prompt text won the preview race and an older response did not overwrite it
