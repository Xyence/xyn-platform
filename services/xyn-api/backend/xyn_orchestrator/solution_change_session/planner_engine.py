from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence


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
)


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


def _classify_request(
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


def _score_artifacts(
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


def _build_candidate_files(
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


def _build_decomposition_steps(candidate_files: Sequence[str]) -> List[str]:
    primary = str(candidate_files[0] if candidate_files else "target module").strip()
    secondary = str(candidate_files[1] if len(candidate_files) > 1 else "").strip()
    steps = [
        f"Freeze `{primary}` as a compatibility wrapper and map workflow entrypoints.",
        f"Extract cohesive workflow segments from `{primary}` into focused backend modules.",
        "Replace extracted sections with delegation wrappers while preserving request/response behavior.",
        "Run targeted regression checks for changed workflow paths and imports.",
    ]
    if secondary:
        steps.insert(2, f"Audit `{secondary}` for shared imports/constants that should move with extraction boundaries.")
    return steps


def _contains_placeholder_steps(steps: Sequence[str]) -> bool:
    lowered = "\n".join(str(step or "").lower() for step in steps)
    return any(token in lowered for token in _DECOMPOSITION_PLACEHOLDER_PATTERNS)


def _is_generic_placeholder_step(step: str) -> bool:
    lowered = str(step or "").strip().lower()
    if not lowered:
        return True
    return any(token in lowered for token in _DECOMPOSITION_PLACEHOLDER_PATTERNS)


def _validate_execution_packaging(
    *,
    planning_mode: str,
    implementation_steps: Sequence[str],
    file_operations: Sequence[Dict[str, Any]],
    test_operations: Sequence[Dict[str, Any]],
) -> None:
    if str(planning_mode or "").strip() != "decompose_existing_system":
        return
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
) -> Dict[str, Any]:
    ordered_work_items: List[Dict[str, Any]] = []
    for idx, operation in enumerate(file_operations, start=1):
        row = dict(operation) if isinstance(operation, dict) else {}
        if not row:
            continue
        row["order"] = idx
        ordered_work_items.append(row)
    route_registration_updates = _dedupe(
        [
            *[str(item).strip() for item in route_update_implications if str(item).strip()],
            *[f"Preserve existing route contract: {route}" for route in affected_routes if str(route).strip()],
        ]
    )
    return {
        "planning_mode": str(planning_mode or ""),
        "source_files": _dedupe([str(item).strip() for item in source_files if str(item).strip()]),
        "ordered_work_items": ordered_work_items,
        "targeted_tests": [dict(item) for item in test_operations if isinstance(item, dict)],
        "validation_order": _dedupe([str(item).strip() for item in validation_sequence if str(item).strip()]),
        "compatibility_constraints": _dedupe([str(item).strip() for item in compatibility_constraints if str(item).strip()]),
        "rollback_instructions": _dedupe([str(item).strip() for item in rollback_notes if str(item).strip()]),
        "route_registration_updates": route_registration_updates,
        "implementation_checklist": _dedupe([str(item).strip() for item in implementation_steps if str(item).strip()]),
    }


def _normalized_module_name(path: str) -> str:
    token = str(path or "").strip().replace("\\", "/")
    token = token.rsplit(".", 1)[0]
    return token.replace("/", ".").strip(".")


def _extract_planner_hints(base_plan: Dict[str, Any], planner_hints: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    merged = planner_hints if isinstance(planner_hints, dict) else {}

    def _collect(key: str) -> List[str]:
        out: List[str] = []
        for source in (merged.get(key), base_plan.get(key)):
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


def _build_modify_steps(candidate_files: Sequence[str], *, full_stack: bool) -> List[str]:
    primary = str(candidate_files[0] if candidate_files else "target module").strip()
    if full_stack:
        return [
            f"Update backend contracts and API handlers in `{primary}` (or equivalent backend module).",
            "Align UI integration points with updated API contracts and preserve compatibility.",
            "Validate end-to-end flow in preview with staged backend and UI artifacts.",
        ]
    return [
        f"Inspect `{primary}` and implement the requested behavior change with minimal scope.",
        "Update tests and validation checks covering impacted API/workflow behavior.",
        "Confirm no regressions in adjacent workflows before stage apply.",
    ]


def _build_create_app_steps() -> List[str]:
    return [
        "Create Python backend scaffold (app package, routing module, settings/env wiring).",
        "Define initial domain modules and API contract boundaries.",
        "Add baseline test scaffold (unit + API smoke) and validation harness.",
        "Prepare preview/deployment wiring for first vertical slice validation.",
    ]


class _BasePlanner:
    mode = "modify_existing_system"

    def synthesize(
        self,
        *,
        candidate_files: Sequence[str],
        classification: PlannerClassification,
        request_text: str,
        planner_hints: Optional[Dict[str, List[str]]] = None,
        codebase_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class PythonMonolithDecompositionPlanner(_BasePlanner):
    mode = "decompose_existing_system"

    def synthesize(
        self,
        *,
        candidate_files: Sequence[str],
        classification: PlannerClassification,
        request_text: str,
        planner_hints: Optional[Dict[str, List[str]]] = None,
        codebase_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        hints = planner_hints if isinstance(planner_hints, dict) else {}
        analysis = codebase_analysis if isinstance(codebase_analysis, dict) else {}
        hinted_sources = [str(item).strip() for item in (hints.get("target_source_files") or []) if str(item).strip()]
        source_files = _dedupe([*hinted_sources, *[str(item).strip() for item in candidate_files if str(item).strip()]])
        if not source_files:
            source_files = [str(candidate_files[0] if candidate_files else "services/xyn-api/backend/xyn_orchestrator/xyn_api.py").strip()]
        extraction_seams = _dedupe([str(item).strip() for item in (hints.get("extraction_seams") or []) if str(item).strip()])
        detected_seams = [str(item).strip() for item in (analysis.get("detected_extraction_seams") or []) if str(item).strip()]
        if detected_seams:
            extraction_seams = _dedupe([*extraction_seams, *detected_seams])
        if not extraction_seams:
            extraction_seams = [
                "solution_change_session_workflow",
                "runtime_run_handlers",
                "release_target_handlers",
            ]
        destination_modules = _dedupe([str(item).strip() for item in (hints.get("moved_handlers_modules") or []) if str(item).strip()])
        existing_destination_modules = [
            str(item).strip()
            for item in (analysis.get("candidate_destination_modules") or [])
            if str(item).strip()
        ]
        destination_modules = _dedupe([*destination_modules, *existing_destination_modules])
        if not destination_modules:
            destination_modules = [
                "backend/xyn_orchestrator/api/solutions.py",
                "backend/xyn_orchestrator/api/runtime.py",
                "backend/xyn_orchestrator/planning/plan_service.py",
                "backend/xyn_orchestrator/solution_change_session/stage_apply_workflow.py",
            ]
        required_tests = _dedupe([str(item).strip() for item in (hints.get("required_test_suites") or []) if str(item).strip()])
        analysis_tests = [str(item).strip() for item in (analysis.get("affected_tests") or []) if str(item).strip()]
        required_tests = _dedupe([*required_tests, *analysis_tests])
        if not required_tests:
            required_tests = [
                "xyn_orchestrator.tests.test_goal_planning",
                "xyn_orchestrator.tests.test_bearer_workflow_auth",
            ]
        affected_routes = [str(item).strip() for item in (analysis.get("affected_routes") or []) if str(item).strip()]
        import_rewrite_surface = [str(item).strip() for item in (analysis.get("import_rewrite_surface") or []) if str(item).strip()]
        proposed_moves = []
        sequence: List[str] = []
        concrete_steps: List[str] = [
            f"Freeze `{source_files[0]}` as orchestration entrypoint and map current handler clusters.",
        ]
        for index, seam in enumerate(extraction_seams):
            destination = destination_modules[index] if index < len(destination_modules) else destination_modules[-1]
            import_rewrite_target = import_rewrite_surface[index] if index < len(import_rewrite_surface) else source_files[0]
            proposed_moves.append(
                {
                    "seam": seam,
                    "from": source_files[0],
                    "to_module": destination,
                    "import_rewrite_target": import_rewrite_target,
                }
            )
            sequence.extend(
                [
                    f"extract_{seam}",
                    f"rewrite_imports_for_{seam}",
                    f"route_delegation_for_{seam}",
                ]
            )
            concrete_steps.append(
                f"Extract `{seam}` handlers from `{source_files[0]}` into `{destination}` and keep delegation wrappers in place."
            )
            concrete_steps.append(
                f"Rewrite imports in `{import_rewrite_target}` to consume `{destination}` without changing request/response contracts."
            )
        if affected_routes:
            concrete_steps.append(f"Update route delegation for: {', '.join(affected_routes[:6])}.")
        concrete_steps.append("Run targeted regression and planner/session workflow tests before stage_apply.")
        steps = _dedupe([*concrete_steps, *_build_decomposition_steps(source_files)])
        return {
            "implementation_steps": steps,
            "file_operations": [
                {
                    "operation": "extract_module",
                    "source": move.get("from"),
                    "destination": move.get("to_module"),
                    "seam": move.get("seam"),
                    "notes": "move cohesive workflow logic into existing module home when available",
                }
                for move in proposed_moves
            ] + [
                {
                    "operation": "rewrite_imports",
                    "source": str(move.get("import_rewrite_target") or source_files[0]),
                    "destination": str(move.get("to_module") or ""),
                    "seam": str(move.get("seam") or ""),
                }
                for move in proposed_moves
            ] + [
                {
                    "operation": "delegate_wrapper",
                    "source": str(source_files[0] if source_files else ""),
                    "notes": "preserve compatibility entrypoint",
                }
            ],
            "test_operations": [
                *[
                    {"operation": "run", "target": suite, "scope": "decomposition-regression"}
                    for suite in required_tests
                ],
            ],
            "compatibility_constraints": [
                "Maintain identical request/response behavior.",
                "Do not introduce new features during decomposition pass.",
            ],
            "risk_annotations": [
                "Import-cycle risk while extracting shared helpers.",
                "Compatibility wrapper drift if call sites are partially moved.",
            ],
            "rollback_notes": [
                "Rollback by restoring wrapper-only commit and reverting extracted module import wiring.",
            ],
            "source_files": source_files,
            "destination_modules": destination_modules,
            "extraction_seams": extraction_seams,
            "proposed_moves": proposed_moves,
            "compatibility_shims": [
                {
                    "source_module": _normalized_module_name(source_files[0]),
                    "shim_type": "delegation_wrapper",
                    "reason": "preserve import and route compatibility during incremental extraction",
                }
            ],
            "affected_routes": affected_routes,
            "route_update_implications": [
                f"Route `{route}` delegates to extracted seam modules."
                for route in affected_routes[:6]
            ] or [
                "Update xyn_api routing handlers to delegate into extracted modules.",
                "Preserve endpoint paths and response envelopes while extraction is in progress.",
            ],
            "ordered_migration_steps": _dedupe(
                [
                    "identify_domain_clusters",
                    *sequence,
                    "run_required_test_suites",
                    "verify_preview_and_commit_readiness",
                ]
            ),
            "affected_tests": required_tests,
        }


class PythonFeatureModificationPlanner(_BasePlanner):
    mode = "modify_existing_system"

    def synthesize(
        self,
        *,
        candidate_files: Sequence[str],
        classification: PlannerClassification,
        request_text: str,
        planner_hints: Optional[Dict[str, List[str]]] = None,
        codebase_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        full_stack = "ui_change" in classification.intents and "api_change" in classification.intents
        steps = _build_modify_steps(candidate_files, full_stack=full_stack)
        return {
            "implementation_steps": steps,
            "file_operations": [
                {"operation": "edit", "target": str(candidate_files[0] if candidate_files else "<target_file>")},
            ],
            "test_operations": [
                {"operation": "run", "target": "targeted tests"},
                {"operation": "run", "target": "smoke/preview checks"},
            ],
            "compatibility_constraints": [
                "Preserve existing contracts unless explicitly requested.",
            ],
            "risk_annotations": [
                "Behavior drift across adjacent handlers/components.",
            ],
            "rollback_notes": [
                "Revert scoped file edits and re-run validation sequence.",
            ],
        }


class PythonAppCreationPlanner(_BasePlanner):
    mode = "create_new_application"

    def synthesize(
        self,
        *,
        candidate_files: Sequence[str],
        classification: PlannerClassification,
        request_text: str,
        planner_hints: Optional[Dict[str, List[str]]] = None,
        codebase_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        steps = _build_create_app_steps()
        return {
            "implementation_steps": steps,
            "file_operations": [
                {"operation": "create", "target": "app/__init__.py"},
                {"operation": "create", "target": "app/api/routes.py"},
                {"operation": "create", "target": "app/domain/models.py"},
                {"operation": "create", "target": "tests/test_api_smoke.py"},
            ],
            "test_operations": [
                {"operation": "run", "target": "new app smoke tests"},
                {"operation": "run", "target": "lint/static checks"},
            ],
            "compatibility_constraints": [
                "Define explicit API/UI contracts before broadening scope.",
            ],
            "risk_annotations": [
                "Over-scaffolding risk; keep first slice minimal and runnable.",
            ],
            "rollback_notes": [
                "Rollback by removing scaffold commit if first slice is not viable.",
            ],
            "scaffold_plan": {
                "project_layout": ["app/api", "app/domain", "app/services", "tests"],
                "initial_boundaries": ["API handlers", "domain services", "integration seams"],
            },
        }


class FullStackCoordinationPlanner(_BasePlanner):
    mode = "cross_artifact_change"

    def synthesize(
        self,
        *,
        candidate_files: Sequence[str],
        classification: PlannerClassification,
        request_text: str,
        planner_hints: Optional[Dict[str, List[str]]] = None,
        codebase_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        steps = _build_modify_steps(candidate_files, full_stack=True)
        return {
            "implementation_steps": steps,
            "file_operations": [
                {"operation": "edit", "target": str(candidate_files[0] if candidate_files else "<backend_or_ui_target>")},
                {"operation": "edit", "target": str(candidate_files[1] if len(candidate_files) > 1 else "<paired_surface_target>")},
            ],
            "test_operations": [
                {"operation": "run", "target": "API contract tests"},
                {"operation": "run", "target": "UI integration tests"},
            ],
            "compatibility_constraints": [
                "Backend response contracts and UI assumptions must stay synchronized.",
            ],
            "risk_annotations": [
                "Cross-artifact release coupling can break preview validation if staged unevenly.",
            ],
            "rollback_notes": [
                "Rollback paired backend/UI commits together to avoid contract skew.",
            ],
        }


def _planner_for_mode(mode: str) -> _BasePlanner:
    if mode == "decompose_existing_system":
        return PythonMonolithDecompositionPlanner()
    if mode == "create_new_application":
        return PythonAppCreationPlanner()
    if mode == "cross_artifact_change":
        return FullStackCoordinationPlanner()
    return PythonFeatureModificationPlanner()


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


def _build_codebase_analysis(
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
            destination_modules = [
                "backend/xyn_orchestrator/api/solutions.py",
                "backend/xyn_orchestrator/api/runtime.py",
                "backend/xyn_orchestrator/planning/plan_service.py",
                "backend/xyn_orchestrator/solution_change_session/stage_apply_workflow.py",
            ]
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
) -> Dict[str, Any]:
    base = dict(base_plan or {})
    multi_artifact_required = _requires_multiple_artifacts(
        analysis=analysis,
        planner_hints=planner_hints,
        selected_artifact_ids=selected_artifact_ids,
    )
    classification = _classify_request(
        request_text,
        artifact_count=len(list(artifacts)),
        planner_hints=planner_hints,
        multi_artifact_required=multi_artifact_required,
    )
    ranked = _score_artifacts(
        request_text=request_text,
        artifacts=artifacts,
        selected_artifact_ids=selected_artifact_ids,
    )
    candidate_files = _build_candidate_files(
        request_text=request_text,
        base_plan=base,
        ranked_artifacts=ranked,
    )
    oversized = _compute_oversized_file_report(
        candidate_files=candidate_files,
        line_count_lookup=line_count_lookup,
    )

    selection = _resolve_artifact_scope(
        ranked=ranked,
        classification=classification,
        selected_artifact_ids=selected_artifact_ids,
        multi_artifact_required=multi_artifact_required,
    )
    selected_ids: List[str] = [str(item).strip() for item in (selection.get("selected_artifact_ids") or []) if str(item).strip()]

    planner = _planner_for_mode(classification.planning_mode)
    hints = _extract_planner_hints(base, planner_hints)
    if hints.get("target_source_files"):
        candidate_files = _dedupe([*hints.get("target_source_files", []), *candidate_files])
    codebase_analysis = _build_codebase_analysis(
        mode=classification.planning_mode,
        candidate_files=candidate_files,
        oversized=oversized,
        analysis=analysis,
    )
    synthesized = planner.synthesize(
        candidate_files=candidate_files,
        classification=classification,
        request_text=request_text,
        planner_hints=hints,
        codebase_analysis=codebase_analysis,
    )

    implementation_steps = _dedupe([str(item or "").strip() for item in (synthesized.get("implementation_steps") or []) if str(item or "").strip()])
    implementation_steps = [step for step in implementation_steps if not _prohibited_ui_step(step, request_text=request_text)]
    if not implementation_steps:
        if classification.planning_mode == "decompose_existing_system":
            implementation_steps = _build_decomposition_steps(candidate_files)
        else:
            implementation_steps = [
                "Inspect the primary target module and define minimal scoped edits.",
                "Apply implementation changes and run targeted validation before stage apply.",
            ]
    if classification.planning_mode == "decompose_existing_system" and _contains_placeholder_steps(implementation_steps):
        implementation_steps = _build_decomposition_steps(candidate_files)

    proposed_work = _dedupe([*implementation_steps])
    file_operations = synthesized.get("file_operations") if isinstance(synthesized.get("file_operations"), list) else []
    test_operations = synthesized.get("test_operations") if isinstance(synthesized.get("test_operations"), list) else []
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
    compatibility_constraints = synthesized.get("compatibility_constraints") if isinstance(synthesized.get("compatibility_constraints"), list) else []
    rollback_notes = synthesized.get("rollback_notes") if isinstance(synthesized.get("rollback_notes"), list) else []
    route_update_implications = (
        synthesized.get("route_update_implications")
        if isinstance(synthesized.get("route_update_implications"), list)
        else []
    )
    affected_routes = synthesized.get("affected_routes") if isinstance(synthesized.get("affected_routes"), list) else []

    _validate_execution_packaging(
        planning_mode=classification.planning_mode,
        implementation_steps=implementation_steps,
        file_operations=file_operations if isinstance(file_operations, list) else [],
        test_operations=test_operations if isinstance(test_operations, list) else [],
    )

    execution_package = _build_execution_package(
        planning_mode=classification.planning_mode,
        source_files=synthesized.get("source_files") if isinstance(synthesized.get("source_files"), list) else [],
        file_operations=file_operations if isinstance(file_operations, list) else [],
        test_operations=test_operations if isinstance(test_operations, list) else [],
        validation_sequence=validation_sequence,
        compatibility_constraints=compatibility_constraints if isinstance(compatibility_constraints, list) else [],
        rollback_notes=rollback_notes if isinstance(rollback_notes, list) else [],
        route_update_implications=route_update_implications if isinstance(route_update_implications, list) else [],
        affected_routes=affected_routes if isinstance(affected_routes, list) else [],
        implementation_steps=implementation_steps,
    )

    affected_tests = [
        item.get("target")
        for item in (test_operations if isinstance(test_operations, list) else [])
        if isinstance(item, dict) and str(item.get("target") or "").strip()
    ]
    if isinstance(synthesized.get("affected_tests"), list):
        for value in synthesized.get("affected_tests") or []:
            token = str(value or "").strip()
            if token:
                affected_tests.append(token)

    architecture = {
        "backend_artifacts": [item.get("artifact_id") for item in ranked if any(token in str(item.get("role") or "") for token in ("api", "worker", "runtime"))],
        "ui_artifacts": [item.get("artifact_id") for item in ranked if "ui" in str(item.get("role") or "")],
        "selected_surfaces": selected_ids,
        "cross_artifact": classification.planning_mode == "cross_artifact_change",
        "source_files": synthesized.get("source_files") if isinstance(synthesized.get("source_files"), list) else [],
        "destination_modules": synthesized.get("destination_modules") if isinstance(synthesized.get("destination_modules"), list) else [],
        "extraction_seams": synthesized.get("extraction_seams") if isinstance(synthesized.get("extraction_seams"), list) else [],
        "proposed_moves": synthesized.get("proposed_moves") if isinstance(synthesized.get("proposed_moves"), list) else [],
        "compatibility_shims": synthesized.get("compatibility_shims") if isinstance(synthesized.get("compatibility_shims"), list) else [],
        "affected_routes": synthesized.get("affected_routes") if isinstance(synthesized.get("affected_routes"), list) else [],
        "affected_tests": _dedupe([str(item).strip() for item in affected_tests if str(item).strip()]),
        "ordered_extraction_sequence": synthesized.get("ordered_migration_steps") if isinstance(synthesized.get("ordered_migration_steps"), list) else [],
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
        "assumptions": _dedupe([*classification.assumptions, *[str(item).strip() for item in (base.get("assumptions") if isinstance(base.get("assumptions"), list) else []) if str(item).strip()]]),
        "selected_artifact_ids": selected_ids,
        "artifact_relevance": ranked,
        "proposed_work": proposed_work,
        "candidate_files": candidate_files,
        "implementation_steps": implementation_steps,
        "file_operations": file_operations if isinstance(file_operations, list) else [],
        "test_operations": test_operations if isinstance(test_operations, list) else [],
        "validation_sequence": validation_sequence,
        "preview_requirements": preview_requirements,
        "risk_annotations": synthesized.get("risk_annotations") if isinstance(synthesized.get("risk_annotations"), list) else [],
        "rollback_notes": rollback_notes if isinstance(rollback_notes, list) else [],
        "affected_tests": _dedupe([str(item).strip() for item in affected_tests if str(item).strip()]),
        "compatibility_constraints": compatibility_constraints if isinstance(compatibility_constraints, list) else [],
        "source_files": synthesized.get("source_files") if isinstance(synthesized.get("source_files"), list) else [],
        "destination_modules": synthesized.get("destination_modules") if isinstance(synthesized.get("destination_modules"), list) else [],
        "extraction_seams": synthesized.get("extraction_seams") if isinstance(synthesized.get("extraction_seams"), list) else [],
        "proposed_moves": synthesized.get("proposed_moves") if isinstance(synthesized.get("proposed_moves"), list) else [],
        "compatibility_shims": synthesized.get("compatibility_shims") if isinstance(synthesized.get("compatibility_shims"), list) else [],
        "route_update_implications": route_update_implications if isinstance(route_update_implications, list) else [],
        "affected_routes": affected_routes if isinstance(affected_routes, list) else [],
        "ordered_migration_steps": synthesized.get("ordered_migration_steps") if isinstance(synthesized.get("ordered_migration_steps"), list) else [],
        "ordered_extraction_sequence": synthesized.get("ordered_migration_steps") if isinstance(synthesized.get("ordered_migration_steps"), list) else [],
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
                "ranked": ranked,
                "selected_artifact_ids": selected_ids,
                "resolved_artifact": selection.get("resolved_artifact") if isinstance(selection.get("resolved_artifact"), dict) else {},
                "scope_mode": str(selection.get("scope_mode") or "minimal"),
                "scope_reason": str(selection.get("scope_reason") or ""),
                "additional_artifacts": selection.get("additional_artifacts") if isinstance(selection.get("additional_artifacts"), list) else [],
            },
            "codebase_analysis": {
                "candidate_files": candidate_files,
                "oversized_file_report": oversized,
                "signals": codebase_analysis,
            },
            "architecture_inference": architecture,
            "analysis_snapshot": analysis if isinstance(analysis, dict) else {},
        },
        "resolved_artifact": selection.get("resolved_artifact") if isinstance(selection.get("resolved_artifact"), dict) else {},
        "scope_mode": str(selection.get("scope_mode") or "minimal"),
        "scope_reason": str(selection.get("scope_reason") or ""),
        "additional_artifacts": selection.get("additional_artifacts") if isinstance(selection.get("additional_artifacts"), list) else [],
        "scaffold_plan": synthesized.get("scaffold_plan") if isinstance(synthesized.get("scaffold_plan"), dict) else {},
    }
