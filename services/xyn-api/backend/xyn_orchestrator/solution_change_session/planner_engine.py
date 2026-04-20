from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from jsonschema import ValidationError, validate


@dataclass(frozen=True)
class PlannerArtifactInput:
    artifact_id: str
    slug: str
    title: str
    role: str
    artifact_type: str
    responsibility_summary: str
    owner_paths: List[str]
    edit_mode: str


@dataclass(frozen=True)
class PlannerClassification:
    planning_mode: str
    plan_kind: str
    intents: List[str]
    confidence: float
    assumptions: List[str]


class SolutionPlanningError(RuntimeError):
    """Base class for solution planning orchestration failures."""


class SolutionPlanningAgentUnavailableError(SolutionPlanningError):
    """Raised when no planning-agent response is available to orchestrate."""


class SolutionPlanningAgentResponseValidationError(SolutionPlanningError):
    """Raised when planning-agent output fails canonical schema validation."""


_UI_FORBIDDEN_TERMS = (
    "width",
    "min-width",
    "max-width",
    "anchoring",
    "header",
    "navigation",
    "styling",
    "layout",
)

_DECOMPOSITION_PLACEHOLDER_PATTERNS = (
    "inspect file",
    "inspect the file",
    "update as needed",
    "confirm behavior",
    "adjust tests",
    "review module",
    "apply changes",
    "validate functionality",
)

_XYN_API_PREFERRED_DESTINATION_MODULES: List[str] = [
    "backend/xyn_orchestrator/api/solutions.py",
    "backend/xyn_orchestrator/api/runtime.py",
    "backend/xyn_orchestrator/solution_change_session/stage_apply_workflow.py",
    "backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py",
    "backend/xyn_orchestrator/solution_change_session/stage_apply_scoping.py",
    "backend/xyn_orchestrator/solution_change_session/stage_apply_git.py",
]

_PLANNING_AGENT_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "minLength": 1},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "ordered_steps": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "affected_files": {"type": "array", "items": {"type": "string"}},
        "affected_components": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "validation_checks": {"type": "array", "items": {"type": "string"}},
        "execution_constraints": {"type": "array", "items": {"type": "string"}},
        "file_operations": {"type": "array", "items": {"type": "object"}},
        "test_operations": {"type": "array", "items": {"type": "object"}},
        "rollback_notes": {"type": "array", "items": {"type": "string"}},
        "route_update_implications": {"type": "array", "items": {"type": "string"}},
        "affected_routes": {"type": "array", "items": {"type": "string"}},
        "source_files": {"type": "array", "items": {"type": "string"}},
        "destination_modules": {"type": "array", "items": {"type": "string"}},
        "extraction_seams": {"type": "array", "items": {"type": "string"}},
        "proposed_moves": {"type": "array", "items": {"type": "object"}},
        "compatibility_shims": {"type": "array", "items": {"type": "object"}},
        "ordered_migration_steps": {"type": "array", "items": {"type": "string"}},
        "compatibility_constraints": {"type": "array", "items": {"type": "string"}},
        "scaffold_plan": {"type": "object"},
        "risk_annotations": {"type": "array", "items": {"type": "string"}},
        "affected_tests": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "goal",
        "ordered_steps",
        "validation_checks",
    ],
    "additionalProperties": False,
}


def _targets_xyn_api_monolith(paths: Sequence[str]) -> bool:
    for path in [str(item).strip().lower() for item in paths if str(item).strip()]:
        if "backend/xyn_orchestrator/xyn_api.py" in path:
            return True
        if "services/xyn-api/backend/xyn_orchestrator/xyn_api.py" in path:
            return True
        if "xyn_orchestrator/xyn_api.py" in path:
            return True
    return False


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if token]


def _extract_path_hints(text: str) -> List[str]:
    hints: List[str] = []
    raw = str(text or "")
    for match in re.findall(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+", raw):
        normalized = str(match or "").strip().replace("\\", "/")
        if normalized and normalized not in hints:
            hints.append(normalized)
    return hints[:24]


def _request_forbids_ui_changes(text: str) -> bool:
    lowered = str(text or "").lower()
    patterns = (
        r"\bno\s+ui\b",
        r"\bno\s+styling\b",
        r"\bno\s+layout\b",
        r"\bdo\s+not\s+modify\s+ui\b",
        r"\bdo\s+not\s+change\s+ui\b",
        r"\bdo\s+not\s+modify\s+styling\b",
        r"\bdo\s+not\s+modify\s+layout\b",
        r"\bwithout\s+ui\s+changes\b",
        r"\bwithout\s+styling\s+changes\b",
        r"\bwithout\s+layout\s+changes\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def _normalize_planning_request_classification(
    text: str,
    *,
    artifact_count: int,
    planner_hints: Optional[Dict[str, Any]] = None,
    multi_artifact_required: bool = False,
) -> PlannerClassification:
    lowered = str(text or "").lower()
    hints = planner_hints if isinstance(planner_hints, dict) else {}
    intents: List[str] = []

    def _append_intent(token: str) -> None:
        if token not in intents:
            intents.append(token)

    structural_refactor = any(
        signal in lowered
        for signal in (
            "strict refactor",
            "structural refactor",
            "decompose",
            "decomposition",
            "split",
            "break up monolith",
            "extract into modules",
            "extract into smaller modules",
            "move handlers into modules",
            "separate domains",
            "delegation wrappers",
            "preserve behavior",
            "no feature additions",
            "do not introduce new features",
        )
    )
    structural_refactor = structural_refactor or bool(
        (isinstance(hints.get("target_source_files"), list) and len(hints.get("target_source_files") or []) > 0)
        or (isinstance(hints.get("extraction_seams"), list) and len(hints.get("extraction_seams") or []) > 0)
        or (isinstance(hints.get("moved_handlers_modules"), list) and len(hints.get("moved_handlers_modules") or []) > 0)
    )
    ui_change = (not _request_forbids_ui_changes(lowered)) and any(
        token in lowered
        for token in ("ui", "frontend", "layout", "styling", "css", "screen", "component", "panel", "page")
    )
    api_change = any(token in lowered for token in ("api", "endpoint", "backend", "schema", "payload", "workflow"))
    bug_fix = any(token in lowered for token in ("bug", "fix", "regression", "broken", "error"))
    test_only = any(token in lowered for token in ("test-only", "tests only", "validation only", "validate only"))
    new_app = any(
        signal in lowered
        for signal in (
            "create new application",
            "new application",
            "bootstrap app",
            "scaffold app",
            "greenfield",
            "from scratch",
        )
    )
    cross_artifact_terms = any(
        token in lowered
        for token in (
            "cross artifact",
            "cross-artifact",
            "across artifacts",
            "both ui and api",
            "frontend and backend",
        )
    )
    behavior_in_place = any(
        token in lowered
        for token in (
            "modify",
            "change",
            "update",
            "adjust",
            "fix",
            "preserve behavior",
            "in-place",
            "in place",
            "behavior-only",
            "behavior only",
        )
    ) or bool(bug_fix)

    if structural_refactor:
        _append_intent("decomposition/refactor")
    if bug_fix:
        _append_intent("bug_fix")
    if api_change:
        _append_intent("api_change")
    if ui_change:
        _append_intent("ui_change")
    if new_app:
        _append_intent("full_stack_app_creation")
    if test_only:
        _append_intent("test_or_validation_focus")
    if not intents:
        _append_intent("feature_addition")

    # Precedence:
    # 1) structural decomposition
    # 2) behavior-in-place modification
    # 3) create new app/scaffold
    # 4) true cross-artifact coordination
    if structural_refactor:
        planning_mode = "decompose_existing_system"
        plan_kind = "decomposition"
        confidence = 0.88
    elif behavior_in_place:
        planning_mode = "modify_existing_system"
        plan_kind = "incremental_change"
        confidence = 0.8
    elif new_app and artifact_count == 0:
        planning_mode = "create_new_application"
        plan_kind = "application_scaffold"
        confidence = 0.9
    elif multi_artifact_required and (cross_artifact_terms or (ui_change and api_change)):
        planning_mode = "cross_artifact_change"
        plan_kind = "full_stack_change"
        confidence = 0.82
    else:
        planning_mode = "modify_existing_system"
        plan_kind = "incremental_change"
        confidence = 0.75

    assumptions: List[str] = []
    if _request_forbids_ui_changes(lowered):
        assumptions.append("Explicit constraints prohibit UI/styling/layout modifications.")
    if any(token in lowered for token in ("preserve behavior", "identical request/response")):
        assumptions.append("Behavior compatibility is mandatory.")
    if any(token in lowered for token in ("no feature additions", "do not introduce new features")):
        assumptions.append("No net-new feature scope is allowed.")

    return PlannerClassification(
        planning_mode=planning_mode,
        plan_kind=plan_kind,
        intents=intents,
        confidence=confidence,
        assumptions=assumptions,
    )


def _artifact_is_ui(artifact: PlannerArtifactInput) -> bool:
    haystack = " ".join([artifact.role, artifact.slug, artifact.title, artifact.artifact_type, artifact.responsibility_summary]).lower()
    return any(token in haystack for token in ("ui", "frontend", "workbench", "layout", "component"))


def _artifact_is_backend(artifact: PlannerArtifactInput) -> bool:
    haystack = " ".join([artifact.role, artifact.slug, artifact.title, artifact.artifact_type, artifact.responsibility_summary]).lower()
    return any(token in haystack for token in ("api", "backend", "service", "orchestrator", "python"))


def _assemble_artifact_relevance(
    *,
    request_text: str,
    artifacts: Sequence[PlannerArtifactInput],
    selected_artifact_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    text = str(request_text or "").lower()
    token_set = set(_tokenize(text))
    path_hints = [hint.lower() for hint in _extract_path_hints(request_text)]
    forbids_ui = _request_forbids_ui_changes(request_text)
    has_ui_request = (not forbids_ui) and any(token in text for token in ("ui", "frontend", "layout", "styling", "component", "screen", "panel"))
    has_backend_request = any(token in text for token in ("api", "backend", "python", "endpoint", "workflow", "orchestrator"))

    ranked: List[Dict[str, Any]] = []
    selected = {str(item or "").strip() for item in selected_artifact_ids if str(item or "").strip()}
    for artifact in artifacts:
        score = 0
        reasons: List[str] = []
        title_slug = f"{artifact.slug} {artifact.title}".lower()
        owner_paths = [str(path or "").strip().lower() for path in (artifact.owner_paths or []) if str(path or "").strip()]

        if str(artifact.artifact_id) in selected:
            score += 8
            reasons.append("explicitly selected in session scope")

        exact_identity_match = False
        slug_tokens = [part for part in re.split(r"[-_.\s]+", str(artifact.slug or "").lower()) if part]
        title_tokens = [part for part in re.split(r"[-_.\s]+", str(artifact.title or "").lower()) if part]
        if str(artifact.slug or "").lower() in text:
            exact_identity_match = True
            score += 10
            reasons.append("request explicitly names artifact slug")
        elif slug_tokens and all(token in token_set for token in slug_tokens):
            exact_identity_match = True
            score += 6
            reasons.append("request token set matches artifact slug identity")
        elif title_tokens and len(title_tokens) >= 2 and all(token in token_set for token in title_tokens[:2]):
            exact_identity_match = True
            score += 4
            reasons.append("request token set matches artifact title identity")

        source_evidence_score = 0
        for hint in path_hints:
            if hint and any(hint.startswith(path) or path in hint for path in owner_paths):
                score += 14
                source_evidence_score += 14
                reasons.append("explicit file path hint matched owned source scope")
                break

        if path_hints and any("xyn_api.py" in hint or "xyn_orchestrator" in hint for hint in path_hints):
            if _artifact_is_backend(artifact):
                score += 6
                source_evidence_score += 6
                reasons.append("request references backend python modules")
            if _artifact_is_ui(artifact):
                score -= 4
                reasons.append("backend module path demotes UI artifact")

        if has_backend_request and _artifact_is_backend(artifact):
            score += 5
            reasons.append("backend/API intent alignment")
        if has_backend_request and _artifact_is_ui(artifact):
            score -= 2
            reasons.append("backend/API intent de-prioritizes UI artifact")

        if has_ui_request and _artifact_is_ui(artifact):
            score += 5
            reasons.append("UI intent alignment")
        if has_ui_request and _artifact_is_backend(artifact):
            score -= 1
            reasons.append("UI intent de-prioritizes backend artifact")

        if forbids_ui and _artifact_is_ui(artifact):
            score -= 9
            reasons.append("request explicitly forbids UI/styling/layout changes")

        if any(token in text for token in ("decompose", "extract", "refactor", "delegation wrappers")) and _artifact_is_backend(artifact):
            score += 4
            reasons.append("structural refactor intent aligns with backend artifact")

        if any(token in text for token in (artifact.slug.lower(), artifact.title.lower())):
            score += 3
            reasons.append("request text directly references artifact")

        ranked.append(
            {
                "artifact_id": str(artifact.artifact_id),
                "slug": artifact.slug,
                "title": artifact.title,
                "role": artifact.role,
                "score": score,
                "exact_identity_match": bool(exact_identity_match),
                "source_evidence_score": int(source_evidence_score),
                "reasons": reasons,
            }
        )

    ranked.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("title") or "")))
    return ranked


def _assemble_candidate_files_context(
    *,
    request_text: str,
    base_plan: Dict[str, Any],
    ranked_artifacts: Sequence[Dict[str, Any]],
) -> List[str]:
    files: List[str] = []
    for item in (base_plan.get("candidate_files") if isinstance(base_plan.get("candidate_files"), list) else []):
        token = str(item or "").strip()
        if token and token not in files:
            files.append(token)
    for hint in _extract_path_hints(request_text):
        if hint and hint not in files:
            files.append(hint)
    if not files:
        top = ranked_artifacts[0] if ranked_artifacts else {}
        top_slug = str(top.get("slug") or "").strip().lower()
        if top_slug in {"xyn-api", "core.xyn-runtime"}:
            files.append("services/xyn-api/backend/xyn_orchestrator/xyn_api.py")
    return files[:20]


def _compute_oversized_file_report(
    *,
    candidate_files: Sequence[str],
    line_count_lookup: Optional[Callable[[str], Optional[int]]],
) -> Dict[str, Any]:
    thresholds = (500, 1000, 3000, 10000)
    by_threshold: Dict[str, List[Dict[str, Any]]] = {str(value): [] for value in thresholds}
    largest: List[Dict[str, Any]] = []
    if line_count_lookup is None:
        return {"available": False, "largest_files": [], "thresholds": by_threshold}
    for path in candidate_files:
        lines = line_count_lookup(str(path))
        if not isinstance(lines, int) or lines <= 0:
            continue
        row = {"path": str(path), "line_count": int(lines)}
        largest.append(row)
        for threshold in thresholds:
            if lines >= threshold:
                by_threshold[str(threshold)].append(row)
    largest.sort(key=lambda row: (-int(row.get("line_count") or 0), str(row.get("path") or "")))
    return {
        "available": True,
        "largest_files": largest[:10],
        "thresholds": {key: value[:10] for key, value in by_threshold.items()},
    }


def _prohibited_ui_step(step: str, *, request_text: str) -> bool:
    if not _request_forbids_ui_changes(request_text):
        return False
    lowered = str(step or "").lower()
    return any(token in lowered for token in _UI_FORBIDDEN_TERMS)


def _dedupe(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        token = str(value or "").strip()
        if token and token not in out:
            out.append(token)
    return out


def _contains_placeholder_steps(steps: Sequence[str]) -> bool:
    lowered = "\n".join(str(step or "").lower() for step in steps)
    return any(token in lowered for token in _DECOMPOSITION_PLACEHOLDER_PATTERNS)


def _is_generic_placeholder_step(step: str) -> bool:
    lowered = str(step or "").strip().lower()
    if not lowered:
        return True
    return any(token in lowered for token in _DECOMPOSITION_PLACEHOLDER_PATTERNS)


def _is_decomposition_meaningful_line(line: str) -> bool:
    lowered = str(line or "").strip().lower()
    if not lowered or _is_generic_placeholder_step(lowered):
        return False
    has_file_or_module_ref = any(token in lowered for token in ("/", ".py", "module", "handler", "route", "helper", "import", "shim"))
    has_extraction_verb = any(
        token in lowered
        for token in ("extract", "move", "rewrite", "delegate", "preserve", "split", "carve")
    )
    return bool(has_file_or_module_ref and has_extraction_verb)


def decomposition_implementation_steps_meaningful(implementation_steps: Sequence[str]) -> bool:
    rows = [str(item or "").strip() for item in implementation_steps if str(item or "").strip()]
    if not rows:
        return False
    return any(_is_decomposition_meaningful_line(item) for item in rows)


def decomposition_proposed_work_meaningful(proposed_work: Sequence[str]) -> bool:
    rows = [str(item or "").strip() for item in proposed_work if str(item or "").strip()]
    if not rows:
        return False
    return any(_is_decomposition_meaningful_line(item) for item in rows)


def validate_decomposition_plan_quality(plan: Dict[str, Any]) -> None:
    payload = plan if isinstance(plan, dict) else {}
    if str(payload.get("planning_mode") or "").strip() != "decompose_existing_system":
        return
    implementation_steps = payload.get("implementation_steps") if isinstance(payload.get("implementation_steps"), list) else []
    proposed_work = payload.get("proposed_work") if isinstance(payload.get("proposed_work"), list) else []
    extraction_seams = payload.get("extraction_seams") if isinstance(payload.get("extraction_seams"), list) else []
    proposed_moves = payload.get("proposed_moves") if isinstance(payload.get("proposed_moves"), list) else []
    if not decomposition_implementation_steps_meaningful(implementation_steps):
        raise ValueError("invalid_decomposition_plan: implementation_steps not decomposition-meaningful")
    if not decomposition_proposed_work_meaningful(proposed_work):
        raise ValueError("invalid_decomposition_plan: proposed_work not decomposition-meaningful")
    if not [str(item).strip() for item in extraction_seams if str(item).strip()]:
        raise ValueError("invalid_decomposition_plan: empty extraction_seams")
    if not [item for item in proposed_moves if isinstance(item, dict)]:
        raise ValueError("invalid_decomposition_plan: empty proposed_moves")


def _validate_execution_packaging(
    *,
    planning_mode: str,
    implementation_steps: Sequence[str],
    file_operations: Sequence[Dict[str, Any]],
    test_operations: Sequence[Dict[str, Any]],
    extraction_seams: Sequence[str],
    proposed_moves: Sequence[Dict[str, Any]],
) -> None:
    if str(planning_mode or "").strip() != "decompose_existing_system":
        return
    if not [str(item).strip() for item in extraction_seams if str(item).strip()]:
        raise ValueError("invalid_decomposition_plan: empty extraction_seams")
    if not [item for item in proposed_moves if isinstance(item, dict)]:
        raise ValueError("invalid_decomposition_plan: empty proposed_moves")
    if not list(file_operations):
        raise ValueError("invalid_decomposition_plan: empty file_operations")
    if not list(test_operations):
        raise ValueError("invalid_decomposition_plan: empty test_operations")
    filtered_steps = [str(step or "").strip() for step in implementation_steps if str(step or "").strip()]
    if not filtered_steps:
        raise ValueError("invalid_decomposition_plan: empty implementation_steps")
    if all(_is_generic_placeholder_step(step) for step in filtered_steps):
        raise ValueError("invalid_decomposition_plan: implementation_steps are generic placeholders")


def _build_execution_package(
    *,
    planning_mode: str,
    source_files: Sequence[str],
    file_operations: Sequence[Dict[str, Any]],
    test_operations: Sequence[Dict[str, Any]],
    validation_sequence: Sequence[str],
    compatibility_constraints: Sequence[str],
    rollback_notes: Sequence[str],
    route_update_implications: Sequence[str],
    affected_routes: Sequence[str],
    implementation_steps: Sequence[str],
    extraction_seams: Sequence[str],
    proposed_moves: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    ordered_work_items: List[Dict[str, Any]] = []
    import_rewrite_operations: List[Dict[str, Any]] = []
    route_operations: List[Dict[str, Any]] = []
    for idx, operation in enumerate(file_operations, start=1):
        row = dict(operation) if isinstance(operation, dict) else {}
        if not row:
            continue
        row["order"] = idx
        ordered_work_items.append(row)
        op_name = str(row.get("operation") or "").strip().lower()
        if op_name in {"rewrite_imports", "import_rewrite"}:
            import_rewrite_operations.append(row)
        if op_name in {"route_update", "route_delegation", "route_registration"}:
            route_operations.append(row)
    route_registration_updates = _dedupe(
        [
            *[str(item).strip() for item in route_update_implications if str(item).strip()],
            *[f"Preserve existing route contract: {route}" for route in affected_routes if str(route).strip()],
        ]
    )
    for route in [str(item).strip() for item in affected_routes if str(item).strip()]:
        route_operations.append(
            {
                "operation": "preserve_route_binding",
                "route": route,
                "requirement": "preserve route binding while handlers move",
            }
        )
    for move in [item for item in proposed_moves if isinstance(item, dict)]:
        seam = str(move.get("seam") or "").strip()
        source = str(move.get("from") or "").strip()
        destination = str(move.get("to_module") or "").strip()
        if seam and source and destination:
            route_operations.append(
                {
                    "operation": "preserve_route_binding",
                    "seam": seam,
                    "source": source,
                    "destination": destination,
                    "requirement": "maintain existing route behavior through delegation wrappers",
                }
            )
    file_ops_structured = [dict(item) for item in file_operations if isinstance(item, dict)]
    test_ops_structured = [dict(item) for item in test_operations if isinstance(item, dict)]
    return {
        "planning_mode": str(planning_mode or ""),
        "source_files": _dedupe([str(item).strip() for item in source_files if str(item).strip()]),
        "extraction_seams": _dedupe([str(item).strip() for item in extraction_seams if str(item).strip()]),
        "proposed_moves": [dict(item) for item in proposed_moves if isinstance(item, dict)],
        "file_operations": file_ops_structured,
        "test_operations": test_ops_structured,
        "route_operations": route_operations,
        "import_rewrite_operations": import_rewrite_operations,
        "validation_sequence": _dedupe([str(item).strip() for item in validation_sequence if str(item).strip()]),
        "preview_requirements": [
            "Run decomposition validation sequence in order before stage_apply.",
            "Verify route continuity and smoke checks in preview before commit/promotion.",
        ],
        "rollback_instructions": _dedupe([str(item).strip() for item in rollback_notes if str(item).strip()]),
        "compatibility_constraints": _dedupe([str(item).strip() for item in compatibility_constraints if str(item).strip()]),
        # Backward-compatible aliases consumed by earlier handlers.
        "ordered_work_items": ordered_work_items,
        "targeted_tests": test_ops_structured,
        "validation_order": _dedupe([str(item).strip() for item in validation_sequence if str(item).strip()]),
        "route_registration_updates": route_registration_updates,
        "implementation_checklist": _dedupe([str(item).strip() for item in implementation_steps if str(item).strip()]),
    }


def _extract_planner_hints(base_plan: Dict[str, Any], planner_hints: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    merged = planner_hints if isinstance(planner_hints, dict) else {}
    base = base_plan if isinstance(base_plan, dict) else {}
    containers: List[Dict[str, Any]] = []
    for payload in (merged, base):
        if isinstance(payload, dict):
            containers.append(payload)
            for key in ("decomposition_campaign", "decomposition_session", "planner_hints", "campaign_metadata", "campaign"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    containers.append(nested)

    def _collect(key: str) -> List[str]:
        out: List[str] = []
        for container in containers:
            source = container.get(key)
            if isinstance(source, list):
                for item in source:
                    token = str(item or "").strip()
                    if token and token not in out:
                        out.append(token)
        return out

    return {
        "target_source_files": _collect("target_source_files"),
        "extraction_seams": _collect("extraction_seams"),
        "moved_handlers_modules": _collect("moved_handlers_modules"),
        "required_test_suites": _collect("required_test_suites"),
    }


def _requires_multiple_artifacts(
    *,
    analysis: Optional[Dict[str, Any]],
    planner_hints: Optional[Dict[str, Any]],
    selected_artifact_ids: Sequence[str],
) -> bool:
    if len([str(item).strip() for item in selected_artifact_ids if str(item).strip()]) > 1:
        return True
    hints = planner_hints if isinstance(planner_hints, dict) else {}
    if bool(hints.get("requires_multiple_artifacts")) or bool(hints.get("cross_artifact_required")):
        return True
    required_ids = hints.get("required_artifact_ids")
    if isinstance(required_ids, list) and len([str(item).strip() for item in required_ids if str(item).strip()]) > 1:
        return True
    payload = analysis if isinstance(analysis, dict) else {}
    impacted = payload.get("impacted_artifacts")
    if isinstance(impacted, list):
        strong = [
            row for row in impacted
            if isinstance(row, dict) and int(row.get("score") or 0) >= 6 and str(row.get("artifact_id") or "").strip()
        ]
        strong_ids = {str(row.get("artifact_id") or "").strip() for row in strong if str(row.get("artifact_id") or "").strip()}
        if len(strong_ids) > 1:
            return True
    return False


def _planning_agent_payload_types_valid(payload: Dict[str, Any]) -> bool:
    list_fields = (
        "assumptions",
        "ordered_steps",
        "affected_files",
        "affected_components",
        "risks",
        "open_questions",
        "validation_checks",
        "execution_constraints",
        "file_operations",
        "test_operations",
        "rollback_notes",
        "route_update_implications",
        "affected_routes",
        "source_files",
        "destination_modules",
        "extraction_seams",
        "proposed_moves",
        "compatibility_shims",
        "ordered_migration_steps",
        "compatibility_constraints",
        "risk_annotations",
        "affected_tests",
    )
    if not isinstance(payload.get("goal"), str):
        return False
    for field in list_fields:
        if field in payload and not isinstance(payload.get(field), list):
            return False
    if "scaffold_plan" in payload and not isinstance(payload.get("scaffold_plan"), dict):
        return False
    return True


def _normalize_planning_agent_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "goal": str(payload.get("goal") or "").strip(),
        "assumptions": _dedupe([str(item).strip() for item in (payload.get("assumptions") or []) if str(item).strip()]),
        "ordered_steps": _dedupe([str(item).strip() for item in (payload.get("ordered_steps") or []) if str(item).strip()]),
        "affected_files": _dedupe([str(item).strip() for item in (payload.get("affected_files") or []) if str(item).strip()]),
        "affected_components": _dedupe([str(item).strip() for item in (payload.get("affected_components") or []) if str(item).strip()]),
        "risks": _dedupe([str(item).strip() for item in (payload.get("risks") or []) if str(item).strip()]),
        "open_questions": _dedupe([str(item).strip() for item in (payload.get("open_questions") or []) if str(item).strip()]),
        "validation_checks": _dedupe([str(item).strip() for item in (payload.get("validation_checks") or []) if str(item).strip()]),
        "execution_constraints": _dedupe([str(item).strip() for item in (payload.get("execution_constraints") or []) if str(item).strip()]),
        "file_operations": [dict(item) for item in (payload.get("file_operations") or []) if isinstance(item, dict)],
        "test_operations": [dict(item) for item in (payload.get("test_operations") or []) if isinstance(item, dict)],
        "rollback_notes": _dedupe([str(item).strip() for item in (payload.get("rollback_notes") or []) if str(item).strip()]),
        "route_update_implications": _dedupe([str(item).strip() for item in (payload.get("route_update_implications") or []) if str(item).strip()]),
        "affected_routes": _dedupe([str(item).strip() for item in (payload.get("affected_routes") or []) if str(item).strip()]),
        "source_files": _dedupe([str(item).strip() for item in (payload.get("source_files") or []) if str(item).strip()]),
        "destination_modules": _dedupe([str(item).strip() for item in (payload.get("destination_modules") or []) if str(item).strip()]),
        "extraction_seams": _dedupe([str(item).strip() for item in (payload.get("extraction_seams") or []) if str(item).strip()]),
        "proposed_moves": [dict(item) for item in (payload.get("proposed_moves") or []) if isinstance(item, dict)],
        "compatibility_shims": [dict(item) for item in (payload.get("compatibility_shims") or []) if isinstance(item, dict)],
        "ordered_migration_steps": _dedupe([str(item).strip() for item in (payload.get("ordered_migration_steps") or []) if str(item).strip()]),
        "compatibility_constraints": _dedupe([str(item).strip() for item in (payload.get("compatibility_constraints") or []) if str(item).strip()]),
        "scaffold_plan": dict(payload.get("scaffold_plan") or {}) if isinstance(payload.get("scaffold_plan"), dict) else {},
        "risk_annotations": _dedupe([str(item).strip() for item in (payload.get("risk_annotations") or []) if str(item).strip()]),
        "affected_tests": _dedupe([str(item).strip() for item in (payload.get("affected_tests") or []) if str(item).strip()]),
    }
    return normalized


def _build_planning_agent_input(
    *,
    request_text: str,
    base_plan: Dict[str, Any],
    classification: PlannerClassification,
    hints: Dict[str, List[str]],
    codebase_analysis: Dict[str, Any],
    ranked: Sequence[Dict[str, Any]],
    selected_ids: Sequence[str],
    candidate_files: Sequence[str],
) -> Dict[str, Any]:
    return {
        "request_text": str(request_text or ""),
        "classification": asdict(classification),
        "hints": hints,
        "context": {
            "candidate_files": [str(item).strip() for item in candidate_files if str(item).strip()],
            "artifact_relevance": [dict(item) for item in ranked if isinstance(item, dict)],
            "selected_artifact_ids": [str(item).strip() for item in selected_ids if str(item).strip()],
            "codebase_analysis": codebase_analysis if isinstance(codebase_analysis, dict) else {},
        },
        "base_plan": base_plan if isinstance(base_plan, dict) else {},
    }


def _default_planning_agent_call(planning_input: Dict[str, Any]) -> Dict[str, Any]:
    payload = planning_input if isinstance(planning_input, dict) else {}
    base_plan = payload.get("base_plan") if isinstance(payload.get("base_plan"), dict) else {}
    explicit = base_plan.get("planning_agent_response")
    if isinstance(explicit, dict):
        return explicit
    if "goal" in base_plan and "ordered_steps" in base_plan:
        return base_plan
    raise SolutionPlanningAgentUnavailableError(
        "Planning-agent response is unavailable. No deterministic fallback planning is permitted."
    )


def _call_planning_agent(
    *,
    planning_input: Dict[str, Any],
    planning_agent_invoke: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]],
) -> Dict[str, Any]:
    invoke = planning_agent_invoke or _default_planning_agent_call
    try:
        response = invoke(planning_input)
    except SolutionPlanningError:
        raise
    except Exception as exc:
        raise SolutionPlanningError(f"Planning-agent call failed: {exc}") from exc
    if not isinstance(response, dict):
        raise SolutionPlanningAgentResponseValidationError("Planning-agent response must be a JSON object.")
    if not _planning_agent_payload_types_valid(response):
        raise SolutionPlanningAgentResponseValidationError("Planning-agent response has invalid top-level field types.")
    normalized = _normalize_planning_agent_response(response)
    try:
        validate(instance=normalized, schema=_PLANNING_AGENT_RESPONSE_SCHEMA)
    except ValidationError as exc:
        raise SolutionPlanningAgentResponseValidationError(
            f"Planning-agent response failed schema validation: {exc.message}"
        ) from exc
    return normalized


def _resolve_artifact_scope(
    *,
    ranked: Sequence[Dict[str, Any]],
    classification: PlannerClassification,
    selected_artifact_ids: Sequence[str],
    multi_artifact_required: bool,
) -> Dict[str, Any]:
    ranked_rows = [row for row in ranked if isinstance(row, dict)]
    if not ranked_rows:
        return {
            "selected_artifact_ids": [],
            "resolved_artifact": {},
            "scope_mode": "minimal",
            "scope_reason": "no_ranked_artifacts",
            "additional_artifacts": [],
        }

    selected_seed = [str(item).strip() for item in selected_artifact_ids if str(item).strip()]
    top = ranked_rows[0]
    top_id = str(top.get("artifact_id") or "").strip()
    top_score = int(top.get("score") or 0)
    second_score = int((ranked_rows[1].get("score") if len(ranked_rows) > 1 else -999) or -999)
    dominant_gap = top_score - second_score
    exact_identity = bool(top.get("exact_identity_match"))
    source_evidence = int(top.get("source_evidence_score") or 0)

    scope_mode = "cross_artifact" if classification.planning_mode == "cross_artifact_change" and multi_artifact_required else "minimal"
    if scope_mode == "minimal":
        if top_id:
            selected = [top_id]
        elif selected_seed:
            selected = [selected_seed[0]]
        else:
            selected = []
    else:
        selected = []
        for row in ranked_rows:
            row_id = str(row.get("artifact_id") or "").strip()
            row_score = int(row.get("score") or 0)
            if not row_id:
                continue
            if row_score >= max(5, top_score - 4):
                selected.append(row_id)
        if len(selected) < 2:
            fallback = [
                str(row.get("artifact_id") or "").strip()
                for row in ranked_rows
                if str(row.get("artifact_id") or "").strip() and int(row.get("score") or 0) > 0
            ]
            selected = fallback[:2] if len(fallback) >= 2 else ([top_id] if top_id else (selected_seed[:1] if selected_seed else []))

    selected = _dedupe(selected)
    resolved_artifact = {
        "artifact_id": top_id,
        "slug": str(top.get("slug") or ""),
        "title": str(top.get("title") or ""),
        "score": top_score,
        "selection_reason": (
            "exact_identity_and_source_evidence"
            if exact_identity and source_evidence > 0
            else "exact_identity_match"
            if exact_identity
            else "source_evidence_match"
            if source_evidence > 0
            else "highest_ranked_artifact"
        ),
        "dominance_gap": dominant_gap,
    }
    scope_reason = (
        "coordinated_cross_artifact_change_required"
        if scope_mode == "cross_artifact"
        else "minimal_scope_for_strongest_match"
    )
    additional_artifacts: List[Dict[str, Any]] = []
    for row in ranked_rows:
        row_id = str(row.get("artifact_id") or "").strip()
        if not row_id or row_id == top_id or row_id not in selected:
            continue
        additional_artifacts.append(
            {
                "artifact_id": row_id,
                "slug": str(row.get("slug") or ""),
                "score": int(row.get("score") or 0),
                "included_reason": "explicit_multi_artifact_requirement_with_strong_relevance",
            }
        )
    return {
        "selected_artifact_ids": selected,
        "resolved_artifact": resolved_artifact,
        "scope_mode": scope_mode,
        "scope_reason": scope_reason,
        "additional_artifacts": additional_artifacts,
    }


def _assemble_codebase_context(
    *,
    mode: str,
    candidate_files: Sequence[str],
    oversized: Dict[str, Any],
    analysis: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = analysis if isinstance(analysis, dict) else {}
    affected_tests = _dedupe(
        [
            *[str(item).strip() for item in (payload.get("affected_tests") or []) if str(item).strip()],
        ]
    )
    affected_routes = _dedupe(
        [
            *[str(item).strip() for item in (payload.get("route_inventory") or []) if str(item).strip()],
            *[str(item).strip() for item in (payload.get("affected_routes") or []) if str(item).strip()],
        ]
    )
    existing_module_layout = _dedupe(
        [
            *[str(item).strip() for item in (payload.get("module_layout") or []) if str(item).strip()],
        ]
    )
    destination_modules = _dedupe(
        [
            *[str(item).strip() for item in (payload.get("candidate_destination_modules") or []) if str(item).strip()],
        ]
    )
    import_surface = _dedupe(
        [
            *[str(item).strip() for item in (payload.get("import_rewrite_surface") or []) if str(item).strip()],
        ]
    )
    coupling = payload.get("coupling_hotspots")
    if not isinstance(coupling, list):
        coupling = []
    large_functions = payload.get("large_function_signals")
    if not isinstance(large_functions, list):
        large_functions = []
    detected_seams = payload.get("detected_extraction_seams")
    if not isinstance(detected_seams, list):
        detected_seams = []

    if mode == "decompose_existing_system":
        if not destination_modules:
            destination_modules = [*list(_XYN_API_PREFERRED_DESTINATION_MODULES), "backend/xyn_orchestrator/planning/plan_service.py"]
        if _targets_xyn_api_monolith(candidate_files):
            destination_modules = _dedupe([*destination_modules, *list(_XYN_API_PREFERRED_DESTINATION_MODULES)])
        if not existing_module_layout:
            existing_module_layout = [
                "backend/xyn_orchestrator/api/solutions.py",
                "backend/xyn_orchestrator/api/runtime.py",
                "backend/xyn_orchestrator/planning",
                "backend/xyn_orchestrator/solution_change_session",
            ]
        if not import_surface:
            import_surface = _dedupe(
                [
                    "backend/xyn_orchestrator/xyn_api.py",
                    *[str(path).strip() for path in candidate_files if str(path).strip()],
                ]
            )
        if not affected_routes and any("xyn_api.py" in str(path) for path in candidate_files):
            affected_routes = [
                "/xyn/api/applications",
                "/xyn/api/applications/{application_id}",
                "/xyn/api/applications/{application_id}/change-sessions",
                "/xyn/api/runs",
            ]
        if not affected_tests:
            affected_tests = [
                "xyn_orchestrator.tests.test_goal_planning",
                "xyn_orchestrator.tests.test_bearer_workflow_auth",
                "xyn_orchestrator.tests.test_solution_change_session_repo_commits",
            ]
        if not detected_seams:
            detected_seams = [
                "solution_change_session_workflow",
                "runtime_run_handlers",
                "planning_checkpoint_handlers",
            ]
        if not coupling:
            coupling = [
                {"module": "backend/xyn_orchestrator/xyn_api.py", "fan_out": 32, "fan_in": 18},
            ]

    return {
        "oversized_file_signals": oversized if isinstance(oversized, dict) else {},
        "large_function_signals": large_functions,
        "coupling_hotspots": coupling,
        "existing_module_layout": existing_module_layout,
        "candidate_destination_modules": destination_modules,
        "affected_routes": affected_routes,
        "affected_tests": affected_tests,
        "import_rewrite_surface": import_surface,
        "detected_extraction_seams": _dedupe([str(item).strip() for item in detected_seams if str(item).strip()]),
    }


def build_solution_change_execution_plan(
    *,
    request_text: str,
    base_plan: Optional[Dict[str, Any]],
    artifacts: Sequence[PlannerArtifactInput],
    selected_artifact_ids: Sequence[str],
    analysis: Optional[Dict[str, Any]] = None,
    planner_hints: Optional[Dict[str, Any]] = None,
    line_count_lookup: Optional[Callable[[str], Optional[int]]] = None,
    planning_agent_invoke: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    base = dict(base_plan or {})
    hints = _extract_planner_hints(base, planner_hints)
    multi_artifact_required = _requires_multiple_artifacts(
        analysis=analysis,
        planner_hints={**(planner_hints if isinstance(planner_hints, dict) else {}), **hints},
        selected_artifact_ids=selected_artifact_ids,
    )
    classification = _normalize_planning_request_classification(
        request_text,
        artifact_count=len(list(artifacts)),
        planner_hints=hints,
        multi_artifact_required=multi_artifact_required,
    )
    artifact_relevance = _assemble_artifact_relevance(
        request_text=request_text,
        artifacts=artifacts,
        selected_artifact_ids=selected_artifact_ids,
    )
    candidate_files = _assemble_candidate_files_context(
        request_text=request_text,
        base_plan=base,
        ranked_artifacts=artifact_relevance,
    )
    oversized = _compute_oversized_file_report(
        candidate_files=candidate_files,
        line_count_lookup=line_count_lookup,
    )

    selection = _resolve_artifact_scope(
        ranked=artifact_relevance,
        classification=classification,
        selected_artifact_ids=selected_artifact_ids,
        multi_artifact_required=multi_artifact_required,
    )
    selected_ids: List[str] = [str(item).strip() for item in (selection.get("selected_artifact_ids") or []) if str(item).strip()]

    if hints.get("target_source_files"):
        candidate_files = _dedupe([*hints.get("target_source_files", []), *candidate_files])
    codebase_context = _assemble_codebase_context(
        mode=classification.planning_mode,
        candidate_files=candidate_files,
        oversized=oversized,
        analysis=analysis,
    )
    planning_input = _build_planning_agent_input(
        request_text=request_text,
        base_plan=base,
        classification=classification,
        hints=hints,
        codebase_analysis=codebase_context,
        ranked=artifact_relevance,
        selected_ids=selected_ids,
        candidate_files=candidate_files,
    )
    agent_response = _call_planning_agent(
        planning_input=planning_input,
        planning_agent_invoke=planning_agent_invoke,
    )

    implementation_steps = _dedupe([str(item or "").strip() for item in (agent_response.get("ordered_steps") or []) if str(item or "").strip()])
    implementation_steps = [step for step in implementation_steps if not _prohibited_ui_step(step, request_text=request_text)]
    if not implementation_steps:
        raise SolutionPlanningAgentResponseValidationError("Planning-agent response returned no usable ordered_steps.")
    if classification.planning_mode == "decompose_existing_system" and _contains_placeholder_steps(implementation_steps):
        raise SolutionPlanningAgentResponseValidationError(
            "Planning-agent response for decomposition contains placeholder-only ordered_steps."
        )

    proposed_work = _dedupe([*implementation_steps])
    file_operations = agent_response.get("file_operations") if isinstance(agent_response.get("file_operations"), list) else []
    test_operations = agent_response.get("test_operations") if isinstance(agent_response.get("test_operations"), list) else []
    validation_sequence = _dedupe(
        [
            "scope_confirmed",
            "architecture_confirmed",
            "execution_plan_confirmed",
            "stage_apply",
            "preview_ready",
            "validate",
        ]
    )
    preview_requirements = [
        "Preview should include selected artifacts in a single deploy set when multiple artifacts are involved.",
        "Run validation sequence before commit/promotion.",
    ]
    compatibility_constraints = agent_response.get("compatibility_constraints") if isinstance(agent_response.get("compatibility_constraints"), list) else []
    compatibility_constraints = _dedupe([*compatibility_constraints, *[str(item).strip() for item in (agent_response.get("execution_constraints") or []) if str(item).strip()]])
    rollback_notes = agent_response.get("rollback_notes") if isinstance(agent_response.get("rollback_notes"), list) else []
    route_update_implications = (
        agent_response.get("route_update_implications")
        if isinstance(agent_response.get("route_update_implications"), list)
        else []
    )
    affected_routes = agent_response.get("affected_routes") if isinstance(agent_response.get("affected_routes"), list) else []
    extraction_seams = agent_response.get("extraction_seams") if isinstance(agent_response.get("extraction_seams"), list) else []
    proposed_moves = agent_response.get("proposed_moves") if isinstance(agent_response.get("proposed_moves"), list) else []

    _validate_execution_packaging(
        planning_mode=classification.planning_mode,
        implementation_steps=implementation_steps,
        file_operations=file_operations if isinstance(file_operations, list) else [],
        test_operations=test_operations if isinstance(test_operations, list) else [],
        extraction_seams=extraction_seams if isinstance(extraction_seams, list) else [],
        proposed_moves=proposed_moves if isinstance(proposed_moves, list) else [],
    )

    execution_package = _build_execution_package(
        planning_mode=classification.planning_mode,
        source_files=agent_response.get("source_files") if isinstance(agent_response.get("source_files"), list) else [],
        file_operations=file_operations if isinstance(file_operations, list) else [],
        test_operations=test_operations if isinstance(test_operations, list) else [],
        validation_sequence=validation_sequence,
        compatibility_constraints=compatibility_constraints if isinstance(compatibility_constraints, list) else [],
        rollback_notes=rollback_notes if isinstance(rollback_notes, list) else [],
        route_update_implications=route_update_implications if isinstance(route_update_implications, list) else [],
        affected_routes=affected_routes if isinstance(affected_routes, list) else [],
        implementation_steps=implementation_steps,
        extraction_seams=extraction_seams if isinstance(extraction_seams, list) else [],
        proposed_moves=proposed_moves if isinstance(proposed_moves, list) else [],
    )

    validate_decomposition_plan_quality(
        {
            "planning_mode": classification.planning_mode,
            "implementation_steps": implementation_steps,
            "proposed_work": proposed_work,
            "extraction_seams": extraction_seams,
            "proposed_moves": proposed_moves,
        }
    )

    affected_tests = [
        item.get("target")
        for item in (test_operations if isinstance(test_operations, list) else [])
        if isinstance(item, dict) and str(item.get("target") or "").strip()
    ]
    if isinstance(agent_response.get("affected_tests"), list):
        for value in agent_response.get("affected_tests") or []:
            token = str(value or "").strip()
            if token:
                affected_tests.append(token)

    architecture = {
        "backend_artifacts": [item.get("artifact_id") for item in artifact_relevance if any(token in str(item.get("role") or "") for token in ("api", "worker", "runtime"))],
        "ui_artifacts": [item.get("artifact_id") for item in artifact_relevance if "ui" in str(item.get("role") or "")],
        "selected_surfaces": selected_ids,
        "cross_artifact": classification.planning_mode == "cross_artifact_change",
        "source_files": agent_response.get("source_files") if isinstance(agent_response.get("source_files"), list) else [],
        "destination_modules": agent_response.get("destination_modules") if isinstance(agent_response.get("destination_modules"), list) else [],
        "extraction_seams": extraction_seams if isinstance(extraction_seams, list) else [],
        "proposed_moves": proposed_moves if isinstance(proposed_moves, list) else [],
        "compatibility_shims": agent_response.get("compatibility_shims") if isinstance(agent_response.get("compatibility_shims"), list) else [],
        "affected_routes": agent_response.get("affected_routes") if isinstance(agent_response.get("affected_routes"), list) else [],
        "affected_tests": _dedupe([str(item).strip() for item in affected_tests if str(item).strip()]),
        "ordered_extraction_sequence": agent_response.get("ordered_migration_steps") if isinstance(agent_response.get("ordered_migration_steps"), list) else [],
    }

    confidence = classification.confidence
    if oversized.get("available") and isinstance(oversized.get("largest_files"), list) and oversized.get("largest_files"):
        top_lines = int((oversized.get("largest_files") or [{}])[0].get("line_count") or 0)
        if top_lines >= 10000:
            confidence = min(0.95, confidence + 0.05)

    return {
        "planning_mode": classification.planning_mode,
        "plan_kind": classification.plan_kind,
        "confidence": float(round(confidence, 3)),
        "goal": str(agent_response.get("goal") or "").strip(),
        "assumptions": _dedupe(
            [
                *classification.assumptions,
                *[str(item).strip() for item in (base.get("assumptions") if isinstance(base.get("assumptions"), list) else []) if str(item).strip()],
                *[str(item).strip() for item in (agent_response.get("assumptions") or []) if str(item).strip()],
            ]
        ),
        "selected_artifact_ids": selected_ids,
        "artifact_relevance": artifact_relevance,
        "proposed_work": proposed_work,
        "candidate_files": candidate_files,
        "implementation_steps": implementation_steps,
        "file_operations": file_operations if isinstance(file_operations, list) else [],
        "test_operations": test_operations if isinstance(test_operations, list) else [],
        "route_operations": execution_package.get("route_operations") if isinstance(execution_package.get("route_operations"), list) else [],
        "import_rewrite_operations": execution_package.get("import_rewrite_operations") if isinstance(execution_package.get("import_rewrite_operations"), list) else [],
        "validation_sequence": validation_sequence,
        "preview_requirements": preview_requirements,
        "rollback_instructions": execution_package.get("rollback_instructions") if isinstance(execution_package.get("rollback_instructions"), list) else [],
        "risk_annotations": _dedupe(
            [
                *[str(item).strip() for item in (agent_response.get("risk_annotations") or []) if str(item).strip()],
                *[str(item).strip() for item in (agent_response.get("risks") or []) if str(item).strip()],
            ]
        ),
        "rollback_notes": rollback_notes if isinstance(rollback_notes, list) else [],
        "open_questions": agent_response.get("open_questions") if isinstance(agent_response.get("open_questions"), list) else [],
        "affected_tests": _dedupe([str(item).strip() for item in affected_tests if str(item).strip()]),
        "compatibility_constraints": compatibility_constraints if isinstance(compatibility_constraints, list) else [],
        "source_files": agent_response.get("source_files") if isinstance(agent_response.get("source_files"), list) else [],
        "destination_modules": agent_response.get("destination_modules") if isinstance(agent_response.get("destination_modules"), list) else [],
        "extraction_seams": agent_response.get("extraction_seams") if isinstance(agent_response.get("extraction_seams"), list) else [],
        "proposed_moves": agent_response.get("proposed_moves") if isinstance(agent_response.get("proposed_moves"), list) else [],
        "compatibility_shims": agent_response.get("compatibility_shims") if isinstance(agent_response.get("compatibility_shims"), list) else [],
        "route_update_implications": route_update_implications if isinstance(route_update_implications, list) else [],
        "affected_routes": affected_routes if isinstance(affected_routes, list) else [],
        "ordered_migration_steps": agent_response.get("ordered_migration_steps") if isinstance(agent_response.get("ordered_migration_steps"), list) else [],
        "ordered_extraction_sequence": agent_response.get("ordered_migration_steps") if isinstance(agent_response.get("ordered_migration_steps"), list) else [],
        "validation_checks": agent_response.get("validation_checks") if isinstance(agent_response.get("validation_checks"), list) else [],
        "execution_package": execution_package,
        "planning_checkpoints": [
            {"checkpoint_key": "scope_confirmed", "label": "Scope confirmed", "required_before": "architecture_confirmed"},
            {"checkpoint_key": "architecture_confirmed", "label": "Architecture confirmed", "required_before": "execution_plan_confirmed"},
            {"checkpoint_key": "execution_plan_confirmed", "label": "Execution plan confirmed", "required_before": "stage_apply"},
            {"checkpoint_key": "preview_ready", "label": "Preview readiness confirmed", "required_before": "validate"},
        ],
        "planner_state": {
            "request_classification": asdict(classification),
            "artifact_targeting": {
                "ranked": artifact_relevance,
                "selected_artifact_ids": selected_ids,
                "resolved_artifact": selection.get("resolved_artifact") if isinstance(selection.get("resolved_artifact"), dict) else {},
                "scope_mode": str(selection.get("scope_mode") or "minimal"),
                "scope_reason": str(selection.get("scope_reason") or ""),
                "additional_artifacts": selection.get("additional_artifacts") if isinstance(selection.get("additional_artifacts"), list) else [],
            },
            "codebase_analysis": {
                "candidate_files": candidate_files,
                "oversized_file_report": oversized,
                "signals": codebase_context,
            },
            "architecture_inference": architecture,
            "analysis_snapshot": analysis if isinstance(analysis, dict) else {},
            "planning_agent_input": planning_input,
        },
        "resolved_artifact": selection.get("resolved_artifact") if isinstance(selection.get("resolved_artifact"), dict) else {},
        "scope_mode": str(selection.get("scope_mode") or "minimal"),
        "scope_reason": str(selection.get("scope_reason") or ""),
        "additional_artifacts": selection.get("additional_artifacts") if isinstance(selection.get("additional_artifacts"), list) else [],
        "scaffold_plan": agent_response.get("scaffold_plan") if isinstance(agent_response.get("scaffold_plan"), dict) else {},
    }
