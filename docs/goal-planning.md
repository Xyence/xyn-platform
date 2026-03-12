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

## Real Estate Deal Finder Example

The domain seed for a real-estate deal finder goal biases toward MVP-first execution:

1. Listing Data Ingestion
2. Property Model and CRUD
3. Comparable Analysis
4. Deal Scoring
5. Opportunity Review UI
6. Lead and Outreach Workflow

The first work items intentionally start with:
- identifying the first listing source
- defining the property-centered entity model
- exposing CRUD/list/detail inspection before broader analysis

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
- queue the first slice
- list/show goals
- recommend the next smallest slice

## Developer Guidance

When adding a new planning seed:

1. keep decomposition deterministic
2. generate a `GoalPlanningOutput`
3. ensure output persists through `persist_goal_plan(...)`
4. prefer queue-ready work items over prose-only planning
5. keep review/approval explicit before broad execution

Do not:
- add a second queueing or dispatch path
- let plans remain only in conversation text
- expand into speculative autonomy beyond XCO scheduling
