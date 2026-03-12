# XCO Coordination Layer

Epic I adds XCO as Xyn's durable coordination layer for thread-based execution scheduling.

## Ownership Boundaries

- Conversation requests work and supervises it.
- XCO `Thread` and `WorkItem` state decide what is eligible to run next.
- Runtime `Run`, `Step`, and `Artifact` execute and record execution details.
- Panels inspect those same durable coordination and runtime objects.

No execution decision should be derived only from transient conversation text or UI state once a durable work object exists.

## Durable Models

### Thread

`CoordinationThread` is the durable line of effort.

Minimum fields:
- `id`
- `title`
- `description`
- `owner`
- `priority`
- `status`
- `domain`
- `work_in_progress_limit`
- `execution_policy`
- `source_conversation_id`
- `created_at`
- `updated_at`

Statuses:
- `active`
- `queued`
- `paused`
- `completed`
- `archived`

Priorities:
- `critical`
- `high`
- `normal`
- `low`

### WorkItem

Epic H keeps `DevTask` as the current durable WorkItem substrate.

Important fields for XCO:
- `work_item_id`
- `coordination_thread_id`
- `dependency_work_item_ids`
- `source_conversation_id`
- `intent_type`
- `target_repo`
- `target_branch`
- `execution_policy`
- `status`

### Run / RunStep / RunArtifact

Epic C/H remain authoritative:
- `Run` in `xyn-core`
- `Step` in `xyn-core`
- `Artifact` in `xyn-core`

XCO references runtime execution through durable `Run` IDs and runtime artifact provenance.

## Lifecycle

```text
conversation
  -> Thread action or WorkItem creation
  -> WorkItem linked to Thread
  -> derived XCO queue
  -> runtime Run dispatch
  -> RunStep / RunArtifact updates
  -> WorkItem and Thread status resolution
  -> panel / activity / thread context updates
```

## Queue Scheduling Rules

The queue is derived from durable state and is not stored as a second execution system.

Eligibility inputs:
- thread status
- thread priority
- thread `max_concurrent_runs` / `work_in_progress_limit`
- work item status
- dependency satisfaction
- thread policy gates such as `review_required`

Ordering:
1. thread priority: `critical`, `high`, `normal`, `low`
2. thread `created_at`
3. work item `priority`
4. work item `created_at`
5. work item ID

This ordering is deterministic for identical durable state.

## Coordination Policies

Supported thread-level policy fields:
- `max_concurrent_runs`
- `pause_on_failure`
- `auto_resume`
- `review_required`

Policy evaluation rules:
- `max_concurrent_runs` limits active dispatch from the thread
- `pause_on_failure` transitions the thread to `paused` when work resolves to failure/review-needed
- `auto_resume` allows queued or paused threads to return to `active` when blocking conditions clear
- `review_required` blocks queue promotion/dispatch for that thread

## Coordination Events

XCO emits durable coordination events through `CoordinationEvent`.

Current event families include:
- `thread_created`
- `thread_active`
- `thread_paused`
- `thread_completed`
- `thread_priority_changed`
- `work_item_promoted`
- `run_dispatched_from_queue`

These events are consumed by:
- thread detail timeline panels
- the shared activity feed

## Panel Surfaces

Epic G/Epic I expose:
- `thread_list`
- `thread_detail`
- `work_item_detail`
- `run_detail`
- `artifact_detail`

Navigation path:

```text
Thread -> WorkItem -> Run -> Artifact
Artifact -> Run
```

All panel data is loaded from durable stored objects rather than panel-local execution state.

## Developer Guidance

When introducing a new thread-managed work flow:

1. create or identify a `CoordinationThread`
2. create or attach a durable WorkItem (`DevTask`)
3. let XCO derive queue eligibility
4. dispatch through the canonical runtime submission seam
5. record coordination events for promotion and dispatch
6. expose the same IDs in panels, activity, and thread context

Do not:
- create a second queueing system
- dispatch directly from conversation when XCO scheduling should apply
- store active work only in UI state
