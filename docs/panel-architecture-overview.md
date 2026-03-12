# Epic G Panel Architecture Overview

## Current seam

Epic G extends the existing Xyn workbench rather than introducing a second workspace shell.

Current insertion points:

- `apps/xyn-ui/src/app/state/xynConsoleStore.tsx`
  Current workspace-scoped console state, panel list, active panel tracking, and canvas context.
- `apps/xyn-ui/src/app/components/console/WorkbenchPanelHost.tsx`
  Current operational panel rendering for runs, artifacts, records, palette results, drafts, and jobs.
- `apps/xyn-ui/src/app/utils/runtimeEventStream.ts`
  Existing runtime stream reducer and subscription seam for run/activity updates.
- `apps/xyn-ui/src/app/components/activity/AgentActivityDrawer.tsx`
  Current conversation-visible execution supervision surface.
- `services/xyn-api/backend/xyn_orchestrator/xyn_api.py`
  Current conversation execution context, intent routing, and runtime/activity API mapping seam.

## Proposed Epic G insertion points

Epic G should layer in these seams:

- Add a canonical durable `Panel` model and `WorkspaceLayout` model in the UI/shared contract layer.
- Replace ad hoc panel creation with a panel registry and panel factory.
- Make FlexLayout the only authoritative layout engine and map panel identity directly to FlexLayout node identity.
- Keep runtime event propagation on the existing stream/reducer seam and route updates to panels by durable object identity.
- Pass focused panel context into the existing Epic D/F intent resolution pathway as advisory context only.
- Move execution context from workspace-scoped console state toward thread-scoped durable conversation state, while leaving layout state workspace-scoped.

## Key constraints

- Panels must map to durable objects only. No panel should represent purely transient UI state.
- Epic G must preserve the single orchestration path:
  `conversation -> Epic D -> ConversationAction -> Epic C runtime / declared app operation -> activity/runtime events`
- Explicit references must always override focus-derived or thread-derived context.
- FlexLayout is the required authoritative layout engine. Existing simple panel state is a migration source, not a second layout authority.
- Thread-scoped execution context is a boundary-hardening refactor, not a new planner or workspace shell.

## Migration risks

- The current `ConsolePanelState` shape is UI-oriented and does not cleanly encode durable object identity.
- `layout_engine: "simple" | "dockview"` is currently embedded in canvas context and will need migration to a FlexLayout-backed model.
- `openPanel(...)` is currently called ad hoc from multiple UI surfaces. Those paths need consolidation through a panel factory.
- Runtime events already update runs and activity, but entity/artifact panels do not yet share a single relevance-routing model.

## Durable `thread_id` prerequisite seam

Epic G Step 9 was blocked until `thread_id` became a real durable contract instead of a UI-side inference.

That contract now exists across the conversation, activity, and runtime mapping seam:

- conversation actions now carry `thread_id`
- prompt activity records persist `thread_id`
- runtime-to-conversation mapped events carry `thread_id`
- activity feed entries expose `thread_id`
- frontend console sessions own a durable `thread_id` instead of deriving execution context only from workspace scope

Correct boundary after this prerequisite:

- thread-scoped durable state:
  - `thread_id`
  - current work/run references
  - recent conversational execution context
- workspace-scoped state:
  - workspace metadata
  - open panels
  - layout configuration

Developer rule:

- new writes in the conversation/activity/runtime seam must include explicit `thread_id`
- legacy reads may tolerate missing `thread_id`, but new behavior must not infer thread identity from workspace or panel state

This unblocks Epic G Steps 5–10, especially Step 9, without introducing a second orchestration path.

## Epic G continuation seam

The next Epic G continuation steps should extend the existing workbench seams rather than inventing a new workspace shell:

- Standard operational panels should be added through the existing panel model, registry, and factory.
- Focus routing should flow through the existing intent resolve/apply path as advisory context:
  - `focused_panel_type`
  - `focused_object_id`
  - `thread_id`
- Panel updates should reuse the existing runtime event stream and entity-change seams, filtered by durable object identity.
- Artifact navigation should reuse existing artifact identities and runtime/conversation provenance references.

### Current continuation constraint

The remaining hard boundary is no longer `thread_id` itself. It is the frontend execution-session model.

Today, the console session store is still keyed primarily by workspace/context entry rather than by durable conversation thread. That is acceptable for the current single-thread conversational supervision model, but it becomes a risk for Epic G Step 9 because multiple conversation panels in one workspace could otherwise share mutable prompt/session state accidentally.

That means Epic G Step 9 should be treated as a boundary-hardening refactor of the existing console session model:

- workspace scope:
  - layout configuration
  - open panels
  - workspace metadata
- thread scope:
  - active work/run references
  - recent entities
  - execution history
  - intent-resolution context
  - conversation-local prompt/session state where needed for restoration

This is still a continuation of the current seam, not a new orchestration path. But it is the highest-risk insertion point for the remainder of Epic G and should be handled deliberately.
