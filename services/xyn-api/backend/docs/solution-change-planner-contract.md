# Solution Change Planner Contract

This planner is an orchestration boundary, not a deterministic plan synthesizer.

## Responsibilities

1. Validate/normalize request and planner hints.
2. Gather planning context (artifact ranking, candidate files, codebase analysis signals).
3. Build planning-agent input payload.
4. Call planning agent.
5. Validate planning-agent response against canonical schema.
6. Produce execution-ready packaging metadata for downstream stage-apply flow.

## Intentionally Removed

- Deterministic request-shape-to-plan synthesis.
- Hardcoded step templates used as primary plan output.
- Silent fallback replacement plans when planning-agent output is missing/malformed.

## Canonical Planning-Agent Schema

Planner expects a single structured payload with fields including:

- `goal`
- `assumptions`
- `ordered_steps`
- `affected_files`
- `affected_components`
- `risks`
- `open_questions`
- `validation_checks`
- `execution_constraints`
- optional execution metadata (`file_operations`, `test_operations`, `source_files`, `extraction_seams`, etc.)

Schema enforcement lives in `solution_change_session/planner_engine.py` via `_PLANNING_AGENT_RESPONSE_SCHEMA`.

## Failure Behavior

- Planning agent unavailable: `SolutionPlanningAgentUnavailableError`
- Planning call failure: `SolutionPlanningError`
- Schema/type validation failure: `SolutionPlanningAgentResponseValidationError`

Planner does not synthesize replacement plans on these failures.

## Planner vs Execution Boundary

- Planner: context assembly, planning-agent invocation, response validation, execution-package assembly.
- Execution: stage apply, runtime execution, deployment operations, and side effects.
