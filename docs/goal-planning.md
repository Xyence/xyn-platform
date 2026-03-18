# Goal Decomposition and Planning

Epic J adds a thin durable planning layer for Xyn.

## Ownership Boundaries

- Conversation requests planning work and reviews planning output.
- `Goal` stores the durable planning request and its decomposition state.
- `CoordinationThread` stores durable lines of effort created from a Goal.
- `DevTask` remains the current durable `WorkItem` substrate for executable work.
- XCO remains the source of truth for queueing and dispatch once work is approved.

Planning does not bypass coordination. A plan must persist into durable threads and work items before Xyn can schedule execution.

## Goal Model

`Goal` is the durable planning object.

Minimum fields:
- `id`
- `title`
- `description`
- `source_conversation_id`
- `requested_by`
- `goal_type`
- `planning_status`
- `priority`
- `planning_summary`
- `resolution_notes_json`
- `created_at`
- `updated_at`

Supported `planning_status` values:
- `proposed`
- `decomposed`
- `in_progress`
- `completed`
- `canceled`

## Planning Output Contract

Planning produces a machine-usable contract:

```json
{
  "goal_id": "goal-123",
  "planning_summary": "Start with the smallest vertical slice...",
  "threads": [
    {
      "title": "Listing Data Ingestion",
      "description": "Ingest the first listing source and normalize records.",
      "priority": "high"
    }
  ],
  "work_items": [
    {
      "thread_title": "Listing Data Ingestion",
      "title": "Identify the first listing source and capture the ingestion contract",
      "description": "Choose the first data source and capture normalization requirements.",
      "priority": "high",
      "sequence": 1
    }
  ],
  "resolution_notes": [
    "Prefer a small runnable slice over a broad component inventory."
  ]
}
```

The contract is persisted automatically into:
- `Goal`
- `CoordinationThread`
- `DevTask`

## Decomposition Rules

Epic J uses deterministic decomposition only.

Supported `goal_type` values in v1:
- `build_system`
- `extend_system`
- `investigate_problem`
- `stabilize_system`

Rules:
- prefer vertical capability threads over technology silos
- bias toward the smallest executable slice
- do not expand into exhaustive platform plans

## Review and Approval Flow

The default planning flow is:

```text
conversation request
  -> Goal created
  -> Goal decomposed into threads/work items
  -> planning review
  -> optional queue_first_slice
  -> XCO queue derivation
  -> runtime dispatch
```

Supported review actions:
- `approve_plan`
- `adjust_plan`
- `defer_execution`
- `queue_first_slice`

Planning does not auto-dispatch broad work by default.

## Queue Seeding Rules

`queue_first_slice`:
- keeps XCO as the scheduling authority
- activates only the selected first thread/slice
- leaves the resulting `DevTask` in queue-ready state
- does not bypass canonical queue derivation or runtime dispatch

## Illustrative Example

Illustrative examples may describe domain-specific plans, but those examples are not built-in runtime planner behavior in core Xyn.

## Panels and Conversation

Epic G / Epic J expose:
- `goal_list`
- `goal_detail`
- existing `thread_detail`
- existing `work_item_detail`

Conversation can:
- create goals
- decompose goals
- summarize plans
- summarize goal and thread progress
- queue the first slice
- list/show goals
- recommend the next smallest slice

## Goal and Thread Progress

Epic K adds a computed development-loop layer on top of durable coordination state.

No new durable progress table exists. Xyn computes progress directly from:
- `Goal`
- `CoordinationThread`
- `DevTask`
- runtime-backed `Run` state
- durable runtime artifacts

Supported computed goal statuses:
- `not_started`
- `in_progress`
- `stalled`
- `nearing_completion`
- `completed`

Supported computed thread statuses:
- `not_started`
- `active`
- `blocked`
- `completed`

These computed summaries appear in:
- `goal_detail`
- conversation progress answers

## Next Slice Detection

Epic K recommends the next slice deterministically from durable state.

Selection rules:
- prefer ready unblocked work
- prefer the smallest executable slice
- prefer earlier MVP threads when candidates are otherwise equal
- return no executable recommendation when nothing queueable exists

The recommendation includes:
- recommended thread
- recommended work item(s)
- concise reasoning derived from actual state

It does not create new planning structure.

## Queue Suggestion Mode

Epic K can suggest coordination actions without dispatching work automatically.

Supported suggestion actions:
- `queue_first_slice`
- `queue_next_slice`
- `resume_thread`

Rules:
- suggestions are read-only outputs derived from durable coordination state
- suggestions do not submit runtime runs
- XCO remains the only scheduling and dispatch authority
- blocked or review-required work does not silently become queueable

## Supervised Recommendation Actions

Epic L extends the development loop with explicit supervised actions attached to
recommendations.

Supported recommendation actions:
- `approve_and_queue`
- `queue_first_slice`
- `queue_next_slice`
- `resume_thread`
- `review_thread`

Action payloads are suggestion metadata only. They:
- reference durable `Goal`, `CoordinationThread`, and `DevTask` identities
- remain read-only until the user explicitly approves an action
- do not dispatch runtime work directly

Recommendation actions must stay deterministic for unchanged durable state.

Actionable recommendations now also include a `recommendation_id`. Xyn uses
that identifier to verify that the user is approving the same durable
recommendation instance that was shown to them.

## Approval Workflow

Epic L adds an approval gate in front of supervised queueing.

Approved flow:

```text
recommendation
  -> user approval
  -> approval gate validation
  -> XCO queue path
  -> runtime dispatch later through Epic I / Epic C
```

Approval gate behavior:
- verifies thread state
- verifies work-item readiness
- validates `recommendation_id` when one is submitted
- queues work only through the existing XCO path
- records an approval event
- rejects invalid or stale approvals with no side effects

The approval gate does not:
- auto-queue on recommendation generation
- auto-dispatch runs
- bypass Epic I scheduling

If a submitted `recommendation_id` is stale, Xyn returns a safe explicit stale
result and performs no queue mutation.

Approval-related coordination events use explicit normalized event types:
- `approval_recommendation`
- `approval_queue_first_slice`
- `approval_queue_next_slice`
- `approval_thread_resume`

Rejected approvals do not emit a separate approval event in the current model.

## Thread Review Mode

Epic L exposes a narrow thread review workflow.

Thread review shows:
- thread status
- completed, active, and blocked work items
- recent run results
- produced artifacts

Supported supervised review actions:
- `resume_thread`
- `queue_next_slice`
- `mark_thread_completed`

These actions route through coordination APIs and follow the same supervised
queue/approval boundaries as the Goal development loop.

## Result Review Loop

After execution completes, Xyn recomputes the development loop from durable
state and surfaces:
- completed work-item result
- actual run/artifact outputs
- impact on thread progress
- impact on goal progress
- the next recommended slice

These summaries appear in:
- `goal_detail`
- `thread_detail`
- conversation progress and review responses

They are derived from durable `Run`, artifact, thread, and goal state rather
than freeform narration.

## Execution Observability

Epic M adds a read-only execution observability layer on top of the same
durable coordination state.

Observability derives only from:
- `Goal`
- `CoordinationThread`
- `DevTask`
- runtime-backed `Run` state
- durable runtime artifacts
- coordination events

Epic M does not:
- change planning
- change queue scheduling
- trigger execution
- introduce automation

### Thread Timeline

Each thread exposes a computed timeline reconstructed from:
- work-item lifecycle
- run lifecycle
- coordination events

Timeline entries are timestamped, ordered deterministically, and remain
reconstructable from durable state.

### Execution Metrics

Thread observability includes:
- average run duration
- total completed work items
- failed work items
- blocked work items

Goal observability includes:
- active threads
- blocked threads
- total completed work items
- artifact production count

These metrics are computed on demand and are not stored in a separate durable
metrics table.

### Artifact Evolution

Artifact detail now exposes a read-only evolution history grouped by logical
artifact identity and ordered by creation time. This uses existing runtime
artifact records and does not introduce a second artifact model.

### Goal Health Indicators

Goal detail includes a compact operational health view:
- progress percent
- active threads
- blocked threads
- recent artifacts

These indicators remain observational and do not alter recommendation or queue
behavior.

## Developer Guidance

When adding a new planning seed:

1. keep decomposition deterministic
2. generate a `GoalPlanningOutput`
3. ensure output persists through `persist_goal_plan(...)`
4. prefer queue-ready work items over prose-only planning
5. keep review/approval explicit before broad execution
6. keep progress evaluation and next-slice recommendation deterministic and derived from durable state
7. keep approval and queue actions supervised and routed through XCO only

Do not:
- add a second queueing or dispatch path
- let plans remain only in conversation text
- expand into speculative autonomy beyond XCO scheduling
- add autonomous replanning or dependency-graph planning in this layer
- introduce automatic queueing, background execution agents, or autonomous execution

## Runtime Agnostic Guard

Named example applications are allowed in tests, docs, and example fixtures only.
Core runtime modules in `services/xyn-api/backend/xyn_orchestrator` must stay
application-agnostic and must not embed product- or vertical-specific business
logic.
