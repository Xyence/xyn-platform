# Operator Runbook

## System startup

Start the local stack from the repo root:

```bash
docker compose up
```

For API-only work, ensure the local API container is healthy before continuing.

## Readiness check

Check system readiness before operating development workflows:

```bash
GET /xyn/api/system/readiness
```

Expected outcome:
- AI providers are configured
- planning and coding agents are present
- at least one repository is registered and reachable
- workspace and artifact storage roots are writable

If readiness is not green, fix configuration before dispatching work.

## Normal development workflow

1. Create or select a goal.
2. Review the generated development task and execution brief.
3. Approve the brief.
4. Dispatch the approved task from the queue.
5. Wait for the execution run to complete.

## Inspecting execution results

From the task or workbench surfaces, confirm:
- execution state is `completed` or inspect failure details
- result summary looks correct
- validation status is acceptable
- any execution artifacts are present when expected

## Inspecting workspace changes

Before publishing, inspect the task change set:
- confirm changed file count
- review the file list
- inspect the diff/patch text for the current workspace result

If no changes are present, publishing will be a no-op.

## Publishing branch changes

Use the task publish action to:
- commit changes to `xyn/task/<dev_task_id>`
- optionally push that branch to the configured remote

After publishing, confirm:
- branch name
- commit hash
- push status

## Troubleshooting

### Readiness failures

- Missing AI provider or agent: configure the required provider credentials and enabled planning/coding agents.
- Missing repository: register an active repository and verify branch access.

### Repository authentication issues

- Re-check repository auth mode and credentials.
- Verify the remote branch exists and `git ls-remote` succeeds.

### Workspace permission issues

- Ensure the managed workspace root exists.
- Ensure the process can write to the workspace root and artifact storage root.

### Execution failures

- Inspect the latest execution run state and summary.
- Review runtime artifacts and failure reason.
- Use retry or requeue only after confirming the brief and target state are still valid.
