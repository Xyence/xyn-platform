from typing import Any, Callable, Dict, List

from xyn_orchestrator.xyn_api import (
    application_factories_collection,
    application_activate,
    application_runtime_binding_detail,
    application_plans_collection,
    application_plan_detail,
    application_plan_apply,
    applications_collection,
    application_detail,
    application_artifact_memberships_collection,
    application_artifact_membership_detail,
    application_solution_change_sessions_collection,
    application_solution_change_session_detail,
    application_solution_change_session_control,
    application_solution_change_session_control_action,
    application_solution_change_session_reply,
    application_solution_change_session_continue,
    application_solution_change_session_regenerate_options,
    application_solution_change_session_select_option,
    application_solution_change_session_checkpoint_decision,
    application_solution_change_session_plan,
    application_solution_change_session_stage_apply,
    application_solution_change_session_prepare_preview,
    application_solution_change_session_promote,
    application_solution_change_session_rollback,
    application_solution_change_session_commit,
    application_solution_change_session_validate,
    application_solution_change_session_commits,
    application_solution_change_session_promotion_evidence,
    application_solution_change_session_finalize,
    solution_change_sessions_collection,
    solution_change_session_detail,
    solution_change_session_control,
    solution_change_session_plan,
    solution_change_session_control_action,
    solution_change_session_checkpoint_decision,
    solution_bundle_install,
)


def solution_change_plan_generation(
    *,
    session,
    memberships: List[Any],
    force_code_aware_planning: bool,
    generate_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    payload = generate_fn(
        session=session,
        memberships=memberships,
        force_code_aware_planning=force_code_aware_planning,
    )
    plan = payload if isinstance(payload, dict) else {}
    if not isinstance(plan.get("proposed_work"), list):
        plan["proposed_work"] = []
    if not isinstance(plan.get("implementation_steps"), list):
        plan["implementation_steps"] = []
    return plan


def solution_change_preview_validation(
    *,
    session,
    mode: str,
    prepare_fn: Callable[..., Dict[str, Any]],
    validate_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    action = str(mode or "").strip().lower()
    if action == "prepare_preview":
        preview = prepare_fn(session=session)
        payload = preview if isinstance(preview, dict) else {}
        payload.setdefault("status", "failed")
        return payload
    if action == "validate":
        validation = validate_fn(session=session)
        payload = validation if isinstance(validation, dict) else {}
        payload.setdefault("status", "failed")
        if not isinstance(payload.get("checks"), list):
            payload["checks"] = []
        return payload
    raise ValueError(f"unsupported preview validation mode: {mode}")


def solution_change_session_workflow(
    *,
    session,
    memberships: List[Any],
    dispatch_runtime: bool,
    dispatch_user: Any,
    stage_apply_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    payload = stage_apply_fn(
        session=session,
        memberships=memberships,
        dispatch_runtime=dispatch_runtime,
        dispatch_user=dispatch_user,
    )
    staged = payload if isinstance(payload, dict) else {}
    if not isinstance(staged.get("artifact_states"), list):
        staged["artifact_states"] = []
    staged.setdefault("overall_state", "staged")
    return staged


__all__ = [
    "application_factories_collection",
    "application_activate",
    "application_runtime_binding_detail",
    "application_plans_collection",
    "application_plan_detail",
    "application_plan_apply",
    "applications_collection",
    "application_detail",
    "application_artifact_memberships_collection",
    "application_artifact_membership_detail",
    "application_solution_change_sessions_collection",
    "application_solution_change_session_detail",
    "application_solution_change_session_control",
    "application_solution_change_session_control_action",
    "application_solution_change_session_reply",
    "application_solution_change_session_continue",
    "application_solution_change_session_regenerate_options",
    "application_solution_change_session_select_option",
    "application_solution_change_session_checkpoint_decision",
    "application_solution_change_session_plan",
    "application_solution_change_session_stage_apply",
    "application_solution_change_session_prepare_preview",
    "application_solution_change_session_promote",
    "application_solution_change_session_rollback",
    "application_solution_change_session_commit",
    "application_solution_change_session_validate",
    "application_solution_change_session_commits",
    "application_solution_change_session_promotion_evidence",
    "application_solution_change_session_finalize",
    "solution_change_sessions_collection",
    "solution_change_session_detail",
    "solution_change_session_control",
    "solution_change_session_control_action",
    "solution_change_session_checkpoint_decision",
    "solution_change_session_plan",
    "solution_bundle_install",
    "solution_change_plan_generation",
    "solution_change_preview_validation",
    "solution_change_session_workflow",
]
