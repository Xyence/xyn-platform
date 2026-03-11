# Conversational Operating Model

Epic F makes conversation the human-visible execution plane for Xyn.

The seam is:
- conversation carries intent and narrative
- artifacts carry state
- runtime carries execution

Conversation must not become a second orchestration engine. It is the front door to the existing Epic C, D, and E contracts.

## Core Lifecycle

1. User message enters `/xyn/api/xyn/intent/resolve`
2. Epic D resolves the message into an `IntentEnvelope`
3. Xyn derives:
   - `PromptInterpretation`
   - `ConversationAction`
4. Supported executable conversation flows return `DraftReady`
5. Console apply calls `/xyn/api/xyn/intent/apply`
6. Apply re-resolves the prompt server-side and executes the same conversation action
7. Epic C runtime or declared app-operation execution performs the work
8. Runtime events and prompt activity are rendered back into conversation/activity surfaces

## ConversationAction

Backend contract:
- `xyn_orchestrator.intent_engine.types.ConversationAction`

Current action types:
- `create_work_item`
- `continue_work_item`
- `dispatch_run`
- `execute_entity_operation`
- `continue_run`
- `retry_run`
- `summarize_run`
- `show_status`
- `pause_run`
- `request_review`

`ConversationAction` is derived from Epic D intent. The UI does not synthesize it on its own.

## Worker Mentions

Worker mentions are parsed before Epic D resolution and then passed through the same intent pipeline.

Supported mention aliases:
- `@codex`
- `@test_runner`
- `@repo_inspector`

Current normalization:
- all three resolve to `codex_local`

Unknown or unavailable mentions fail safely with a structured unsupported intent instead of bypassing intent resolution.
Parsing notes:
- mentions are only parsed from the leading command token
- email-like strings such as `foo@codex.com` do not count as worker mentions
- leading wrapper punctuation such as `(@codex)` is accepted
- only the leading mention is normalized; later `@...` tokens remain ordinary message text

Mention examples:
- `@codex implement Step 2 of Epic F`
- `@test_runner run the relevant tests`
- `@repo_inspector inspect the current repo state`

## Run Control Commands

Supported conversational run-control phrases currently include:
- `pause the current run`
- `continue the run`
- `retry the run`
- `summarize the current run`
- `show me what failed`
- `show logs`
- `show artifacts`

These commands resolve through Epic D and execute through Epic C runtime APIs. They do not bypass runtime state.

## Conversation Context

Conversation shorthand is assisted by a lightweight backend context model:
- `current_work_item`
- `current_run`
- `active_epic`
- `recent_entities`

Rules:
- explicit references win
- context is only used when the prompt is otherwise shorthand or generic
- stale context must not override explicit targets
- in the current shipped model, context is workspace-scoped conversation context rather than a separate durable thread-local state model

The current implementation derives context from recent workspace activity and recent runtime/dev-task references.

## System Message Types

Conversation/activity can render these message types:
- `system_runtime`
- `escalation`
- `execution_summary`

Examples:
- `run.started` -> system runtime message
- `run.failed` -> escalation message
- `run.blocked` -> escalation message
- `run.completed` -> execution summary
- prompt-apply completion -> execution summary

## Escalation Behavior

Escalation messages are used when execution cannot proceed cleanly, including:
- ambiguity requiring clarification
- blocked runs
- failed runs
- review-required states

Escalations include:
- reason
- relevant run/work-item references when available
- bounded next options such as retry, continue, summarize, show logs, or show artifacts

The options are operational hints. Follow-up user messages still pass through Epic D; escalation does not bypass normal intent resolution.

## Execution Summaries

Execution summaries are concise conversation-facing closure messages for:
- completed entity operations
- run dispatch
- completed runs
- failed or blocked runs with terminal summaries

They are intentionally compact. Detailed state remains on runtime run detail and artifact APIs.

## Runtime Event Path

Authoritative runtime source:
- `xyn-core` Event ledger

Conversation delivery path:
- runtime events stream to `xyn-api`
- `xyn-api` maps them to conversation/activity entries
- `AgentActivityDrawer` renders them as system runtime, escalation, or execution-summary messages

This remains additive. No second event model is introduced.
Event hardening notes:
- replay or duplicate delivery is de-duplicated by event identity
- non-terminal late events do not overwrite terminal run state in the conversation-facing run view

## End-to-End Seam

The shipped Epic F lifecycle is:

1. user message
2. Epic D intent resolution
3. `PromptInterpretation` and `ConversationAction`
4. `DraftReady` conversation apply
5. Epic C runtime or declared app operation dispatch
6. runtime/system events mapped back into conversation
7. escalation or execution summary message
8. follow-up control from conversation using explicit references first, then lightweight conversation context

This is a seam integration epic. Conversation is the front door to the existing orchestration/runtime path, not a second orchestration subsystem.

## Debugging Checklist

If a conversation command does not behave correctly:

1. Inspect `/xyn/api/xyn/intent/resolve`
   - confirm `intent`
   - confirm `prompt_interpretation`
   - confirm `conversation_action`
   - confirm `draft_payload.__operation`

2. Inspect `/xyn/api/xyn/intent/apply`
   - confirm the prompt is re-resolved
   - confirm clarification or unsupported states are blocked server-side

3. Inspect runtime APIs
   - `/api/v1/runtime/runs`
   - `/api/v1/runs/{run_id}`
   - `/api/v1/runs/{run_id}/steps`
   - `/api/v1/runs/{run_id}/artifacts`

4. Inspect activity rendering
   - `AgentActivityDrawer.tsx`
   - `runtimeEventStream.ts`

5. Verify the path still follows the single orchestration rule
   - conversation -> Epic D -> ConversationAction -> Epic C / declared app operation
   - not conversation -> ad hoc local executor

## Shipped Scope

Epic F ships:
- conversation action generation
- worker mentions through Epic D
- runtime event visibility in conversation
- run-control command handling
- lightweight conversation context
- escalation messages
- execution summaries

Epic F does not ship:
- multi-agent orchestration
- advanced planning
- broad chat redesign
- migration of every preserved legacy prompt branch

## Follow-ons

Non-blocking Epic F follow-ons:
- keep the run-control phrase list and worker mention aliases aligned with Epic D tests as additional worker types are introduced
- add a small acceptance matrix mapping conversation action families to their runtime/event/message coverage
- watch for semantic drift between `ConversationAction`, `PromptInterpretation`, and runtime event summaries over time

Broader post-Epic-F work:
- migrate more preserved legacy prompt paths onto the conversation action seam when those paths are modernized
- revisit broader conversation ergonomics only after later execution/review epics define stronger operator workflows
- improve wider DB-backed and console integration stability so full-stack conversational supervision can rely on broader regression suites
