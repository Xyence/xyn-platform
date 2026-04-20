from unittest.mock import patch

from django.test import SimpleTestCase

from xyn_orchestrator.solution_change_session.planner_engine import (
    PlannerArtifactInput,
    SolutionPlanningAgentResponseValidationError,
    build_solution_change_execution_plan,
    validate_decomposition_plan_quality,
)


class SolutionPlannerEngineTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._planning_agent_patcher = patch(
            "xyn_orchestrator.solution_change_session.planner_engine._default_planning_agent_call",
            side_effect=self._mock_planning_agent_response,
        )
        self._planning_agent_patcher.start()

    def tearDown(self):
        self._planning_agent_patcher.stop()
        super().tearDown()

    def _mock_planning_agent_response(self, planning_input):
        payload = planning_input if isinstance(planning_input, dict) else {}
        classification = payload.get("classification") if isinstance(payload.get("classification"), dict) else {}
        hints = payload.get("hints") if isinstance(payload.get("hints"), dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        codebase = context.get("codebase_analysis") if isinstance(context.get("codebase_analysis"), dict) else {}
        mode = str(classification.get("planning_mode") or "modify_existing_system")
        candidate_files = [str(item).strip() for item in (context.get("candidate_files") or []) if str(item).strip()]
        primary = str(candidate_files[0] if candidate_files else "services/xyn-api/backend/xyn_orchestrator/xyn_api.py")
        affected_routes = [str(item).strip() for item in (codebase.get("affected_routes") or []) if str(item).strip()]

        if mode == "decompose_existing_system":
            source_files = [str(item).strip() for item in (hints.get("target_source_files") or []) if str(item).strip()]
            if not source_files:
                source_files = [primary]
            extraction_seams = [str(item).strip() for item in (hints.get("extraction_seams") or []) if str(item).strip()]
            if not extraction_seams:
                extraction_seams = ["solution_change_session_workflow", "runtime_run_handlers", "release_target_handlers"]
            destination_modules = [str(item).strip() for item in (hints.get("moved_handlers_modules") or []) if str(item).strip()]
            for module in (codebase.get("candidate_destination_modules") or []):
                token = str(module or "").strip()
                if token and token not in destination_modules:
                    destination_modules.append(token)
            for module in (
                "backend/xyn_orchestrator/api/solutions.py",
                "backend/xyn_orchestrator/api/runtime.py",
                "backend/xyn_orchestrator/solution_change_session/stage_apply_workflow.py",
                "backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py",
                "backend/xyn_orchestrator/solution_change_session/stage_apply_scoping.py",
                "backend/xyn_orchestrator/solution_change_session/stage_apply_git.py",
                "backend/xyn_orchestrator/planning/plan_service.py",
            ):
                if module not in destination_modules:
                    destination_modules.append(module)
            test_targets = [str(item).strip() for item in (hints.get("required_test_suites") or []) if str(item).strip()]
            if not test_targets:
                test_targets = ["xyn_orchestrator.tests.test_goal_planning", "xyn_orchestrator.tests.test_bearer_workflow_auth"]
            proposed_moves = []
            ordered_sequence = ["identify_domain_clusters"]
            for index, seam in enumerate(extraction_seams):
                destination = destination_modules[index] if index < len(destination_modules) else destination_modules[-1]
                proposed_moves.append(
                    {
                        "seam": seam,
                        "from": source_files[0],
                        "to_module": destination,
                        "import_rewrite_target": source_files[0],
                    }
                )
                ordered_sequence.extend([f"extract_{seam}", f"rewrite_imports_for_{seam}", f"route_delegation_for_{seam}"])
            ordered_sequence.extend(["run_required_test_suites", "verify_preview_and_commit_readiness"])
            ordered_steps = [
                f"Extract `{extraction_seams[0]}` handlers from `{source_files[0]}` into `{destination_modules[0]}` and preserve delegation wrappers.",
                f"Rewrite imports in `{source_files[0]}` to reference extracted modules without changing request/response behavior.",
                "Run targeted regression and planner/session workflow tests before stage_apply.",
            ]
            if affected_routes:
                ordered_steps.append(f"Preserve route delegation for: {', '.join(affected_routes[:6])}.")
            return {
                "goal": f"Decompose {source_files[0]} while preserving runtime behavior.",
                "assumptions": ["No net-new feature additions.", "Compatibility wrappers stay in place during extraction."],
                "ordered_steps": ordered_steps,
                "affected_files": source_files + destination_modules,
                "affected_components": ["xyn-api"],
                "risks": [
                    "Import-cycle risk while extracting shared helpers.",
                    "Compatibility wrapper drift if call sites are partially moved.",
                ],
                "open_questions": [],
                "validation_checks": ["scope_confirmed", "architecture_confirmed", "execution_plan_confirmed", "preview_ready", "validate"],
                "execution_constraints": [
                    "Maintain identical request/response behavior.",
                    "Do not introduce new features during decomposition pass.",
                ],
                "file_operations": [
                    {
                        "operation": "extract_module",
                        "source": move.get("from"),
                        "destination": move.get("to_module"),
                        "seam": move.get("seam"),
                    }
                    for move in proposed_moves
                ]
                + [
                    {
                        "operation": "rewrite_imports",
                        "source": str(move.get("import_rewrite_target") or source_files[0]),
                        "destination": str(move.get("to_module") or ""),
                        "seam": str(move.get("seam") or ""),
                    }
                    for move in proposed_moves
                ]
                + [{"operation": "delegate_wrapper", "source": source_files[0], "notes": "preserve compatibility entrypoint"}],
                "test_operations": [{"operation": "run", "target": suite, "scope": "decomposition-regression"} for suite in test_targets],
                "rollback_notes": ["Rollback by reverting extracted module import wiring and wrapper delegation."],
                "route_update_implications": [f"Route `{route}` delegates to extracted seam modules." for route in affected_routes],
                "affected_routes": affected_routes,
                "source_files": source_files,
                "destination_modules": destination_modules,
                "extraction_seams": extraction_seams,
                "proposed_moves": proposed_moves,
                "compatibility_shims": [
                    {
                        "source_module": "backend.xyn_orchestrator.xyn_api",
                        "shim_type": "delegation_wrapper",
                        "reason": "preserve import and route compatibility during incremental extraction",
                    }
                ],
                "ordered_migration_steps": ordered_sequence,
                "compatibility_constraints": [
                    "Maintain identical request/response behavior.",
                    "Do not introduce new features during decomposition pass.",
                ],
                "risk_annotations": [
                    "Import-cycle risk while extracting shared helpers.",
                    "Compatibility wrapper drift if call sites are partially moved.",
                ],
                "affected_tests": test_targets,
            }

        if mode == "create_new_application":
            return {
                "goal": "Create a new runnable application scaffold.",
                "assumptions": ["Initial scope is a minimal vertical slice."],
                "ordered_steps": [
                    "Create Python backend scaffold and routing entrypoints.",
                    "Define initial domain boundaries and contracts.",
                    "Add baseline smoke tests for first slice.",
                ],
                "affected_files": ["app/__init__.py", "app/api/routes.py", "app/domain/models.py", "tests/test_api_smoke.py"],
                "affected_components": ["backend", "api"],
                "risks": ["Over-scaffolding risk; keep first slice minimal and runnable."],
                "open_questions": [],
                "validation_checks": ["scope_confirmed", "execution_plan_confirmed", "validate"],
                "execution_constraints": ["Define explicit API/UI contracts before broadening scope."],
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
                "rollback_notes": ["Rollback by removing scaffold commit if first slice is not viable."],
                "scaffold_plan": {"project_layout": ["app/api", "app/domain", "app/services", "tests"]},
            }

        if mode == "cross_artifact_change":
            secondary = str(candidate_files[1] if len(candidate_files) > 1 else "apps/xyn-ui/src/app/App.tsx")
            return {
                "goal": "Coordinate backend and UI contract changes across artifacts.",
                "assumptions": ["Backend and UI are deployed together for preview validation."],
                "ordered_steps": [
                    f"Update backend behavior in `{primary}` while preserving compatibility constraints.",
                    f"Align paired UI integration in `{secondary}` with backend contract updates.",
                    "Validate end-to-end flow in preview with staged backend and UI artifacts.",
                ],
                "affected_files": [primary, secondary],
                "affected_components": ["xyn-api", "xyn-ui"],
                "risks": ["Cross-artifact release coupling can break preview validation if staged unevenly."],
                "open_questions": [],
                "validation_checks": ["scope_confirmed", "execution_plan_confirmed", "preview_ready", "validate"],
                "execution_constraints": ["Backend response contracts and UI assumptions must stay synchronized."],
                "file_operations": [{"operation": "edit", "target": primary}, {"operation": "edit", "target": secondary}],
                "test_operations": [{"operation": "run", "target": "API contract tests"}, {"operation": "run", "target": "UI integration tests"}],
                "rollback_notes": ["Rollback paired backend/UI commits together to avoid contract skew."],
            }

        return {
            "goal": "Deliver requested behavior change with minimal scope.",
            "assumptions": ["Behavior compatibility remains mandatory unless explicitly changed."],
            "ordered_steps": [
                f"Inspect `{primary}` and implement scoped behavior changes.",
                "Update targeted tests and validation checks for impacted workflows.",
                "Confirm no regressions in adjacent workflows before stage apply.",
            ],
            "affected_files": [primary],
            "affected_components": ["xyn-api"],
            "risks": ["Behavior drift across adjacent handlers/components."],
            "open_questions": [],
            "validation_checks": ["scope_confirmed", "execution_plan_confirmed", "validate"],
            "execution_constraints": ["Preserve existing contracts unless explicitly requested."],
            "file_operations": [{"operation": "edit", "target": primary}],
            "test_operations": [{"operation": "run", "target": "targeted tests"}, {"operation": "run", "target": "smoke/preview checks"}],
            "rollback_notes": ["Revert scoped file edits and re-run validation sequence."],
        }

    def _artifacts(self):
        return [
            PlannerArtifactInput(
                artifact_id="api-1",
                slug="xyn-api",
                title="Xyn API",
                role="primary_api",
                artifact_type="service",
                responsibility_summary="API and orchestration workflows",
                owner_paths=["services/xyn-api/backend"],
                edit_mode="repo_backed",
            ),
            PlannerArtifactInput(
                artifact_id="ui-1",
                slug="xyn-ui",
                title="Xyn UI",
                role="primary_ui",
                artifact_type="web",
                responsibility_summary="Workbench shell and frontend",
                owner_paths=["apps/xyn-ui"],
                edit_mode="repo_backed",
            ),
            PlannerArtifactInput(
                artifact_id="wb-1",
                slug="core.workbench",
                title="Workbench",
                role="shared_library",
                artifact_type="library",
                responsibility_summary="Shared UI/runtime primitives",
                owner_paths=["apps/workbench"],
                edit_mode="repo_backed",
            ),
        ]

    def test_case_a_exact_backend_refactor_request_routes_to_api_and_no_ui_terms(self):
        request_text = (
            "STRICT REFACTOR: Decompose xyn_orchestrator/xyn_api.py into smaller modules by extracting "
            "solution-change-session workflow logic only. DO NOT modify UI, styling, layout, or behavior. "
            "DO NOT introduce new features. Only move existing logic into new modules and replace with "
            "delegation wrappers. Maintain identical request/response behavior."
        )
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={"candidate_files": [], "implementation_steps": [], "proposed_work": []},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
            line_count_lookup=lambda path: 46000 if path.endswith("xyn_api.py") else 200,
        )

        self.assertEqual(plan["planning_mode"], "decompose_existing_system")
        ranked = plan.get("artifact_relevance") or []
        self.assertTrue(ranked)
        self.assertEqual((ranked[0] or {}).get("slug"), "xyn-api")
        ui_rank = next((idx for idx, row in enumerate(ranked) if (row or {}).get("slug") == "xyn-ui"), 999)
        self.assertGreater(ui_rank, 0)

        forbidden = ("width", "min-width", "max-width", "anchoring", "header", "navigation", "layout", "styling")
        joined = "\n".join(plan.get("implementation_steps") or []).lower()
        for token in forbidden:
            self.assertNotIn(token, joined)
        self.assertTrue(plan.get("proposed_work"))
        self.assertTrue(plan.get("implementation_steps"))

    def test_case_b_explicit_file_path_dominates_routing(self):
        request_text = "Refactor services/xyn-api/backend/xyn_orchestrator/xyn_api.py to isolate planner workflow handlers."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
        )
        ranked = plan.get("artifact_relevance") or []
        self.assertTrue(ranked)
        self.assertEqual((ranked[0] or {}).get("slug"), "xyn-api")
        self.assertEqual((plan.get("resolved_artifact") or {}).get("slug"), "xyn-api")
        self.assertEqual(plan.get("scope_mode"), "minimal")
        self.assertLessEqual(len(plan.get("selected_artifact_ids") or []), 1)

    def test_case_c_negative_ui_constraints_penalize_ui_artifacts(self):
        request_text = "Backend workflow refactor for API orchestration, no UI changes, no styling changes, no layout changes."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
        )
        ranked = plan.get("artifact_relevance") or []
        api_score = next((int((row or {}).get("score") or 0) for row in ranked if (row or {}).get("slug") == "xyn-api"), 0)
        ui_score = next((int((row or {}).get("score") or 0) for row in ranked if (row or {}).get("slug") == "xyn-ui"), 0)
        self.assertGreater(api_score, ui_score)

    def test_case_d_genuine_ui_request_still_routes_to_ui(self):
        request_text = "Adjust UI layout and styling for apps/xyn-ui/src/components/Header.tsx to fix dropdown alignment."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
        )
        ranked = plan.get("artifact_relevance") or []
        self.assertTrue(ranked)
        self.assertEqual((ranked[0] or {}).get("slug"), "xyn-ui")

    def test_case_e_structural_refactor_language_generates_extraction_steps(self):
        request_text = "Extract into modules with delegation wrappers, preserve behavior, no feature additions."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
        )
        steps = "\n".join(plan.get("implementation_steps") or []).lower()
        self.assertIn("extract", steps)
        self.assertIn("delegation", steps)
        self.assertIn("preserv", steps)

    def test_behavior_only_request_stays_modify_existing_system(self):
        request_text = "Modify existing endpoint behavior in-place and preserve current contracts."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
        )
        self.assertEqual(plan.get("planning_mode"), "modify_existing_system")
        self.assertEqual(plan.get("plan_kind"), "incremental_change")

    def test_create_new_application_mode_returns_scaffold_plan(self):
        request_text = "Create new application from scratch with Python API and initial UI."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=[],
            selected_artifact_ids=[],
        )
        self.assertEqual(plan.get("planning_mode"), "create_new_application")
        self.assertTrue(plan.get("scaffold_plan"))
        self.assertTrue(plan.get("file_operations"))

    def test_cross_artifact_change_mode_for_ui_and_api_request(self):
        request_text = "Coordinate a cross-artifact API/UI contract transition across backend and frontend artifacts."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1", "ui-1"],
            planner_hints={"requires_multiple_artifacts": True},
        )
        self.assertEqual(plan.get("planning_mode"), "cross_artifact_change")
        self.assertGreaterEqual(len(plan.get("selected_artifact_ids") or []), 2)
        self.assertEqual(plan.get("scope_mode"), "cross_artifact")
        self.assertTrue(plan.get("additional_artifacts"))

    def test_ui_api_wording_without_multi_artifact_requirement_stays_modify(self):
        request_text = "Update API payload and UI rendering, but keep scope narrow and in-place."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
            analysis={"impacted_artifacts": [{"artifact_id": "api-1", "score": 8}, {"artifact_id": "ui-1", "score": 4}]},
        )
        self.assertEqual(plan.get("planning_mode"), "modify_existing_system")
        self.assertLessEqual(len(plan.get("selected_artifact_ids") or []), 1)

    def test_multi_artifact_scope_allowed_when_strongly_implied_by_analysis(self):
        request_text = "Coordinate backend and frontend contract transition across artifacts."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
            analysis={
                "impacted_artifacts": [
                    {"artifact_id": "api-1", "score": 9},
                    {"artifact_id": "ui-1", "score": 8},
                ]
            },
        )
        self.assertEqual(plan.get("planning_mode"), "cross_artifact_change")
        self.assertGreaterEqual(len(plan.get("selected_artifact_ids") or []), 2)
        self.assertEqual(plan.get("scope_mode"), "cross_artifact")

    def test_execution_ready_fields_are_non_empty_for_code_bearing_request(self):
        request_text = "Modify backend endpoint behavior in services/xyn-api/backend/xyn_orchestrator/xyn_api.py."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={"implementation_steps": [], "proposed_work": [], "candidate_files": []},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
        )
        self.assertTrue(plan.get("proposed_work"))
        self.assertTrue(plan.get("implementation_steps"))
        self.assertTrue(plan.get("candidate_files"))
        self.assertTrue(plan.get("file_operations"))
        self.assertTrue(plan.get("test_operations"))
        self.assertTrue(plan.get("validation_sequence"))

    def test_decomposition_plan_uses_metadata_hints_and_returns_extraction_fields(self):
        request_text = "Decompose xyn_api.py by extracting handlers into modules with compatibility wrappers."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
            planner_hints={
                "target_source_files": ["services/xyn-api/backend/xyn_orchestrator/xyn_api.py"],
                "extraction_seams": ["runtime_run_handlers", "solution_change_session_handlers"],
                "moved_handlers_modules": [
                    "xyn_orchestrator.runtime_runs.handlers",
                    "xyn_orchestrator.solution_change_session.workflow_handlers",
                ],
                "required_test_suites": ["xyn_orchestrator.tests.test_goal_planning"],
            },
        )
        self.assertEqual(plan.get("planning_mode"), "decompose_existing_system")
        self.assertEqual(plan.get("plan_kind"), "decomposition")
        self.assertTrue(plan.get("source_files"))
        self.assertTrue(plan.get("destination_modules"))
        self.assertTrue(plan.get("extraction_seams"))
        self.assertTrue(plan.get("proposed_moves"))
        self.assertTrue(plan.get("compatibility_shims"))
        self.assertTrue(plan.get("ordered_migration_steps"))
        self.assertIn("xyn_orchestrator.tests.test_goal_planning", plan.get("affected_tests") or [])
        self.assertTrue(plan.get("file_operations"))
        self.assertTrue(plan.get("test_operations"))
        self.assertTrue(plan.get("candidate_files"))
        forbidden_placeholders = ("inspect file", "update as needed", "confirm behavior", "adjust tests")
        steps = "\n".join(plan.get("implementation_steps") or []).lower()
        for token in forbidden_placeholders:
            self.assertNotIn(token, steps)

    def test_decomposition_plan_biases_to_existing_xyn_orchestrator_destination_modules(self):
        request_text = "Decompose backend/xyn_orchestrator/xyn_api.py by moving handlers into existing modules."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
            analysis={
                "large_function_signals": [{"name": "application_solution_change_session_control_action", "line_count": 300}],
                "coupling_hotspots": [{"module": "backend/xyn_orchestrator/xyn_api.py", "fan_in": 18, "fan_out": 34}],
            },
        )
        self.assertEqual(plan.get("planning_mode"), "decompose_existing_system")
        destinations = plan.get("destination_modules") or []
        self.assertIn("backend/xyn_orchestrator/api/solutions.py", destinations)
        self.assertIn("backend/xyn_orchestrator/api/runtime.py", destinations)
        self.assertIn("backend/xyn_orchestrator/planning/plan_service.py", destinations)
        self.assertTrue(plan.get("extraction_seams"))
        self.assertTrue(plan.get("file_operations"))
        self.assertTrue(plan.get("test_operations"))
        codebase_signals = (((plan.get("planner_state") or {}).get("codebase_analysis") or {}).get("signals") or {})
        self.assertTrue(codebase_signals.get("coupling_hotspots"))
        self.assertTrue(codebase_signals.get("large_function_signals"))

    def test_decomposition_plan_for_xyn_api_emits_concrete_extraction_work(self):
        request_text = (
            "Decompose backend/xyn_orchestrator/xyn_api.py into modules; extract handlers and preserve behavior."
        )
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
        )
        self.assertEqual(plan.get("planning_mode"), "decompose_existing_system")
        self.assertEqual(plan.get("plan_kind"), "decomposition")
        self.assertTrue(plan.get("source_files"))
        self.assertTrue(plan.get("destination_modules"))
        self.assertTrue(plan.get("extraction_seams"))
        self.assertTrue(plan.get("proposed_moves"))
        self.assertTrue(plan.get("ordered_extraction_sequence"))
        self.assertTrue(plan.get("candidate_files"))
        self.assertTrue(plan.get("implementation_steps"))
        destinations = plan.get("destination_modules") or []
        self.assertIn("backend/xyn_orchestrator/api/solutions.py", destinations)
        self.assertIn("backend/xyn_orchestrator/api/runtime.py", destinations)
        required_stage_apply_destinations = {
            "backend/xyn_orchestrator/solution_change_session/stage_apply_workflow.py",
            "backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py",
            "backend/xyn_orchestrator/solution_change_session/stage_apply_scoping.py",
            "backend/xyn_orchestrator/solution_change_session/stage_apply_git.py",
        }
        self.assertTrue(required_stage_apply_destinations.intersection(set(destinations)))
        rendered = " ".join([*(str(item) for item in (plan.get("implementation_steps") or [])), *(str(item) for item in (plan.get("proposed_work") or []))]).lower()
        for token in ("width", "min-width", "max-width", "header", "navigation", "styling", "layout"):
            self.assertNotIn(token, rendered)
        candidate_rendered = " ".join(str(item) for item in (plan.get("candidate_files") or []))
        self.assertNotIn("Inspect the owning UI component", candidate_rendered)

    def test_decomposition_execution_package_is_stage_apply_ready(self):
        request_text = "Decompose backend/xyn_orchestrator/xyn_api.py and preserve route behavior."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
        )
        package = plan.get("execution_package") or {}
        self.assertTrue(package)
        self.assertEqual(package.get("planning_mode"), "decompose_existing_system")
        self.assertTrue(package.get("file_operations"))
        self.assertTrue(package.get("test_operations"))
        self.assertTrue(package.get("import_rewrite_operations"))
        self.assertTrue(package.get("route_operations"))
        self.assertTrue(package.get("validation_sequence"))
        self.assertTrue(package.get("preview_requirements"))
        self.assertTrue(package.get("compatibility_constraints"))
        self.assertTrue(package.get("rollback_instructions"))
        # Decomposition packaging fields are also surfaced at the plan root for stage_apply callers.
        self.assertTrue(plan.get("file_operations"))
        self.assertTrue(plan.get("test_operations"))
        self.assertTrue(plan.get("route_operations"))
        self.assertTrue(plan.get("import_rewrite_operations"))
        self.assertTrue(plan.get("validation_sequence"))
        self.assertTrue(plan.get("preview_requirements"))
        self.assertTrue(plan.get("rollback_instructions"))

    def test_placeholder_decomposition_plan_is_rejected_by_validation_gate(self):
        request_text = "Decompose backend/xyn_orchestrator/xyn_api.py"
        with patch(
            "xyn_orchestrator.solution_change_session.planner_engine._default_planning_agent_call",
            return_value={
                "goal": "decompose",
                "ordered_steps": ["Inspect file", "Update as needed", "Confirm behavior", "Adjust tests"],
                "validation_checks": ["validate"],
                "file_operations": [],
                "test_operations": [],
            },
        ):
            with self.assertRaises(SolutionPlanningAgentResponseValidationError):
                build_solution_change_execution_plan(
                    request_text=request_text,
                    base_plan={},
                    artifacts=self._artifacts(),
                    selected_artifact_ids=["api-1"],
                    planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
                )

    def test_placeholder_only_decomposition_quality_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_decomposition_plan_quality(
                {
                    "planning_mode": "decompose_existing_system",
                    "implementation_steps": ["Inspect file", "Apply changes", "Validate functionality"],
                    "proposed_work": ["Review module", "Update as needed"],
                    "extraction_seams": ["solution_change_session_workflow"],
                    "proposed_moves": [{"seam": "solution_change_session_workflow"}],
                }
            )

    def test_file_specific_decomposition_quality_passes(self):
        validate_decomposition_plan_quality(
            {
                "planning_mode": "decompose_existing_system",
                "implementation_steps": [
                    "Extract solution_change_session handlers from backend/xyn_orchestrator/xyn_api.py into backend/xyn_orchestrator/api/solutions.py.",
                    "Rewrite imports in backend/xyn_orchestrator/xyn_api.py to delegate route handlers.",
                ],
                "proposed_work": [
                    "Move runtime_run handlers to backend/xyn_orchestrator/api/runtime.py and preserve route delegation.",
                ],
                "extraction_seams": ["solution_change_session_workflow", "runtime_run_handlers"],
                "proposed_moves": [
                    {"seam": "solution_change_session_workflow", "from": "backend/xyn_orchestrator/xyn_api.py", "to_module": "backend/xyn_orchestrator/api/solutions.py"},
                ],
            }
        )

    def test_code_aware_ui_plan_still_passes_quality_gate(self):
        validate_decomposition_plan_quality(
            {
                "planning_mode": "code_aware",
                "implementation_steps": ["Inspect apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx and adjust dropdown width."],
                "proposed_work": ["Apply scoped UI styling fix for header dropdown."],
            }
        )

    def test_modify_mode_packaging_remains_backward_compatible(self):
        request_text = "Adjust dropdown behavior in apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["ui-1"],
        )
        self.assertEqual(plan.get("planning_mode"), "modify_existing_system")
        self.assertTrue(plan.get("file_operations"))
        self.assertTrue(plan.get("test_operations"))
        self.assertTrue(plan.get("validation_sequence"))
        self.assertIn("route_operations", plan)
        self.assertIn("import_rewrite_operations", plan)
        self.assertIn("rollback_instructions", plan)

    def test_decomposition_plan_without_seams_or_moves_is_rejected_by_packaging_guard(self):
        request_text = "Decompose backend/xyn_orchestrator/xyn_api.py"
        with patch(
            "xyn_orchestrator.solution_change_session.planner_engine._default_planning_agent_call",
            return_value={
                "goal": "decompose",
                "ordered_steps": ["Extract handlers into modules with wrappers."],
                "validation_checks": ["validate"],
                "file_operations": [
                    {
                        "operation": "extract_module",
                        "source": "backend/xyn_orchestrator/xyn_api.py",
                        "destination": "backend/xyn_orchestrator/api/solutions.py",
                    }
                ],
                "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
                "extraction_seams": [],
                "proposed_moves": [],
            },
        ):
            with self.assertRaises(ValueError):
                build_solution_change_execution_plan(
                    request_text=request_text,
                    base_plan={},
                    artifacts=self._artifacts(),
                    selected_artifact_ids=["api-1"],
                    planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
                )

    def test_planner_calls_planning_agent_for_normal_requests(self):
        request_text = "Modify backend endpoint behavior in services/xyn-api/backend/xyn_orchestrator/xyn_api.py."
        with patch(
            "xyn_orchestrator.solution_change_session.planner_engine._default_planning_agent_call",
            wraps=self._mock_planning_agent_response,
        ) as invoke_mock:
            build_solution_change_execution_plan(
                request_text=request_text,
                base_plan={},
                artifacts=self._artifacts(),
                selected_artifact_ids=["api-1"],
            )
        invoke_mock.assert_called_once()

    def test_malformed_planning_agent_output_fails_validation_explicitly(self):
        request_text = "Modify backend endpoint behavior in services/xyn-api/backend/xyn_orchestrator/xyn_api.py."
        with patch(
            "xyn_orchestrator.solution_change_session.planner_engine._default_planning_agent_call",
            return_value={"goal": "bad", "ordered_steps": ["one"], "validation_checks": "not-a-list"},
        ):
            with self.assertRaises(SolutionPlanningAgentResponseValidationError):
                build_solution_change_execution_plan(
                    request_text=request_text,
                    base_plan={},
                    artifacts=self._artifacts(),
                    selected_artifact_ids=["api-1"],
                )

    def test_missing_ordered_steps_never_triggers_deterministic_repair(self):
        request_text = "Modify backend endpoint behavior in services/xyn-api/backend/xyn_orchestrator/xyn_api.py."
        with patch(
            "xyn_orchestrator.solution_change_session.planner_engine._default_planning_agent_call",
            return_value={"goal": "bad", "ordered_steps": [], "validation_checks": ["validate"]},
        ):
            with self.assertRaises(SolutionPlanningAgentResponseValidationError):
                build_solution_change_execution_plan(
                    request_text=request_text,
                    base_plan={},
                    artifacts=self._artifacts(),
                    selected_artifact_ids=["api-1"],
                )

    def test_decomposition_missing_moves_triggers_single_retry(self):
        request_text = "STRICT REFACTOR: Decompose services/xyn-api/backend/xyn_orchestrator/xyn_api.py into backend modules."
        calls = {"count": 0}

        def _invoke(payload):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "goal": "Decompose xyn_api.py while preserving behavior.",
                    "ordered_steps": [
                        "Extract solution_change_session handlers from backend/xyn_orchestrator/xyn_api.py into backend/xyn_orchestrator/api/solutions.py."
                    ],
                    "validation_checks": ["scope_confirmed", "validate"],
                    "source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                    "extraction_seams": ["solution_change_session_workflow"],
                    "proposed_moves": [],
                    "file_operations": [
                        {
                            "operation": "extract_module",
                            "source": "backend/xyn_orchestrator/xyn_api.py",
                            "destination": "backend/xyn_orchestrator/api/solutions.py",
                        }
                    ],
                    "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
                }
            return {
                "goal": "Decompose xyn_api.py while preserving behavior.",
                "ordered_steps": [
                    "Extract solution_change_session handlers from backend/xyn_orchestrator/xyn_api.py into backend/xyn_orchestrator/api/solutions.py."
                ],
                "validation_checks": ["scope_confirmed", "validate"],
                "source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                "extraction_seams": ["solution_change_session_workflow"],
                "proposed_moves": [
                    {
                        "seam": "solution_change_session_workflow",
                        "from": "backend/xyn_orchestrator/xyn_api.py",
                        "to_module": "backend/xyn_orchestrator/api/solutions.py",
                        "import_rewrite_target": "backend/xyn_orchestrator/xyn_api.py",
                    }
                ],
                "file_operations": [
                    {
                        "operation": "extract_module",
                        "source": "backend/xyn_orchestrator/xyn_api.py",
                        "destination": "backend/xyn_orchestrator/api/solutions.py",
                    },
                    {
                        "operation": "rewrite_imports",
                        "source": "backend/xyn_orchestrator/xyn_api.py",
                        "destination": "backend/xyn_orchestrator/api/solutions.py",
                    },
                ],
                "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
            }

        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
            planning_agent_invoke=_invoke,
        )
        self.assertEqual(calls["count"], 2)
        self.assertTrue(plan.get("proposed_moves"))

    def test_decomposition_missing_moves_after_retry_fails_explicitly(self):
        request_text = "STRICT REFACTOR: Decompose services/xyn-api/backend/xyn_orchestrator/xyn_api.py into backend modules."

        def _invoke(_payload):
            return {
                "goal": "Decompose xyn_api.py while preserving behavior.",
                "ordered_steps": [
                    "Extract solution_change_session handlers from backend/xyn_orchestrator/xyn_api.py into backend/xyn_orchestrator/api/solutions.py."
                ],
                "validation_checks": ["scope_confirmed", "validate"],
                "source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                "extraction_seams": ["solution_change_session_workflow"],
                "proposed_moves": [],
                "file_operations": [
                    {
                        "operation": "extract_module",
                        "source": "backend/xyn_orchestrator/xyn_api.py",
                        "destination": "backend/xyn_orchestrator/api/solutions.py",
                    }
                ],
                "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
            }

        with self.assertRaises(SolutionPlanningAgentResponseValidationError) as exc:
            build_solution_change_execution_plan(
                request_text=request_text,
                base_plan={},
                artifacts=self._artifacts(),
                selected_artifact_ids=["api-1"],
                planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
                planning_agent_invoke=_invoke,
            )
        self.assertIn("missing required fields", str(exc.exception))
        self.assertIn("proposed_moves", str(exc.exception))

    def test_decomposition_missing_file_operations_triggers_single_retry(self):
        request_text = "STRICT REFACTOR: Decompose services/xyn-api/backend/xyn_orchestrator/xyn_api.py into backend modules."
        calls = {"count": 0}

        def _invoke(_payload):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "goal": "Decompose xyn_api.py while preserving behavior.",
                    "ordered_steps": [
                        "Extract solution_change_session handlers from backend/xyn_orchestrator/xyn_api.py into backend/xyn_orchestrator/api/solutions.py."
                    ],
                    "validation_checks": ["scope_confirmed", "validate"],
                    "source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                    "extraction_seams": ["solution_change_session_workflow"],
                    "proposed_moves": [
                        {
                            "seam": "solution_change_session_workflow",
                            "from": "backend/xyn_orchestrator/xyn_api.py",
                            "to_module": "backend/xyn_orchestrator/api/solutions.py",
                        }
                    ],
                    "file_operations": [],
                    "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
                }
            return {
                "goal": "Decompose xyn_api.py while preserving behavior.",
                "ordered_steps": [
                    "Extract solution_change_session handlers from backend/xyn_orchestrator/xyn_api.py into backend/xyn_orchestrator/api/solutions.py."
                ],
                "validation_checks": ["scope_confirmed", "validate"],
                "source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                "extraction_seams": ["solution_change_session_workflow"],
                "proposed_moves": [
                    {
                        "seam": "solution_change_session_workflow",
                        "from": "backend/xyn_orchestrator/xyn_api.py",
                        "to_module": "backend/xyn_orchestrator/api/solutions.py",
                    }
                ],
                "file_operations": [
                    {
                        "operation": "extract_module",
                        "source": "backend/xyn_orchestrator/xyn_api.py",
                        "destination": "backend/xyn_orchestrator/api/solutions.py",
                    }
                ],
                "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
            }

        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
            planning_agent_invoke=_invoke,
        )
        self.assertEqual(calls["count"], 2)
        self.assertTrue(plan.get("file_operations"))

    def test_decomposition_placeholder_steps_trigger_single_retry(self):
        request_text = "STRICT REFACTOR: Decompose services/xyn-api/backend/xyn_orchestrator/xyn_api.py into backend modules."
        calls = {"count": 0}

        def _invoke(_payload):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "goal": "Decompose xyn_api.py while preserving behavior.",
                    "ordered_steps": ["Inspect file", "Update as needed", "Confirm behavior"],
                    "validation_checks": ["scope_confirmed", "validate"],
                    "source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                    "extraction_seams": ["solution_change_session_workflow"],
                    "proposed_moves": [
                        {
                            "seam": "solution_change_session_workflow",
                            "from": "backend/xyn_orchestrator/xyn_api.py",
                            "to_module": "backend/xyn_orchestrator/api/solutions.py",
                        }
                    ],
                    "file_operations": [
                        {
                            "operation": "extract_module",
                            "source": "backend/xyn_orchestrator/xyn_api.py",
                            "destination": "backend/xyn_orchestrator/api/solutions.py",
                        }
                    ],
                    "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
                }
            return {
                "goal": "Decompose xyn_api.py while preserving behavior.",
                "ordered_steps": [
                    "Extract solution_change_session_workflow from backend/xyn_orchestrator/xyn_api.py into backend/xyn_orchestrator/api/solutions.py.",
                    "Rewrite imports in backend/xyn_orchestrator/xyn_api.py to delegate calls to backend/xyn_orchestrator/api/solutions.py.",
                ],
                "validation_checks": ["scope_confirmed", "validate"],
                "source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                "extraction_seams": ["solution_change_session_workflow"],
                "proposed_moves": [
                    {
                        "seam": "solution_change_session_workflow",
                        "from": "backend/xyn_orchestrator/xyn_api.py",
                        "to_module": "backend/xyn_orchestrator/api/solutions.py",
                    }
                ],
                "file_operations": [
                    {
                        "operation": "extract_module",
                        "source": "backend/xyn_orchestrator/xyn_api.py",
                        "destination": "backend/xyn_orchestrator/api/solutions.py",
                    },
                    {
                        "operation": "rewrite_imports",
                        "source": "backend/xyn_orchestrator/xyn_api.py",
                        "destination": "backend/xyn_orchestrator/api/solutions.py",
                    },
                ],
                "test_operations": [{"operation": "run", "target": "xyn_orchestrator.tests.test_goal_planning"}],
            }

        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
            planning_agent_invoke=_invoke,
        )
        self.assertEqual(calls["count"], 2)
        self.assertTrue(plan.get("implementation_steps"))

    def test_route_preserving_decomposition_plan_packages_successfully(self):
        request_text = "Decompose backend/xyn_orchestrator/xyn_api.py while preserving existing routes."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            analysis={
                "affected_routes": [
                    "/xyn/api/applications",
                    "/xyn/api/applications/{application_id}/change-sessions",
                ]
            },
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
        )
        package = plan.get("execution_package") or {}
        route_updates = package.get("route_operations") or []
        rendered = "\n".join(str(item) for item in route_updates)
        self.assertIn("/xyn/api/applications", rendered)
        self.assertIn("preserve_route_binding", rendered)

    def test_decomposition_packaging_contains_stage_apply_usable_file_and_test_ops(self):
        request_text = "Decompose backend/xyn_orchestrator/xyn_api.py and preserve route behavior."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={"target_source_files": ["backend/xyn_orchestrator/xyn_api.py"]},
        )
        package = plan.get("execution_package") or {}
        file_ops = package.get("file_operations") or []
        test_ops = package.get("test_operations") or []
        self.assertTrue(any(str((row or {}).get("operation") or "") == "extract_module" for row in file_ops))
        self.assertTrue(any(str((row or {}).get("operation") or "") == "rewrite_imports" for row in file_ops))
        self.assertTrue(any(str((row or {}).get("operation") or "") == "delegate_wrapper" for row in file_ops))
        self.assertTrue(all(str((row or {}).get("target") or "").strip() for row in test_ops if isinstance(row, dict)))

    def test_decomposition_mode_narrows_to_dominant_artifact(self):
        request_text = (
            "STRICT REFACTOR: split services/xyn-api/backend/xyn_orchestrator/xyn_api.py "
            "into modules and keep UI unchanged."
        )
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1", "ui-1"],
        )
        selected = plan.get("selected_artifact_ids") or []
        self.assertEqual(selected, ["api-1"])
        self.assertEqual(plan.get("scope_mode"), "minimal")

    def test_campaign_metadata_alone_forces_decomposition_mode(self):
        request_text = "Please refine this plan."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={
                "decomposition_campaign": {
                    "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    "extraction_seams": ["solution_change_session_workflow", "runtime_run_handlers"],
                    "moved_handlers_modules": [
                        "backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py",
                        "backend/xyn_orchestrator/solution_change_session/stage_apply_scoping.py",
                    ],
                    "required_test_suites": [
                        "xyn_orchestrator.tests.test_goal_planning",
                        "xyn_orchestrator.tests.test_bearer_workflow_auth",
                    ],
                }
            },
        )
        self.assertEqual(plan.get("planning_mode"), "decompose_existing_system")
        self.assertIn("backend/xyn_orchestrator/xyn_api.py", plan.get("source_files") or [])
        self.assertTrue(any("xyn_api.py" in str(item) for item in (plan.get("candidate_files") or [])))

    def test_campaign_seams_modules_and_tests_flow_to_packaged_plan(self):
        request_text = "Refine decomposition planning."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1"],
            planner_hints={
                "decomposition_session": {
                    "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    "extraction_seams": ["runtime_run_handlers", "solution_change_session_workflow"],
                    "moved_handlers_modules": [
                        "backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py",
                        "backend/xyn_orchestrator/solution_change_session/stage_apply_git.py",
                    ],
                    "required_test_suites": [
                        "xyn_orchestrator.tests.test_goal_planning",
                        "xyn_orchestrator.tests.test_solution_change_session_repo_commits",
                    ],
                }
            },
        )
        self.assertEqual(plan.get("planning_mode"), "decompose_existing_system")

        seams = {str(item) for item in (plan.get("extraction_seams") or [])}
        self.assertIn("runtime_run_handlers", seams)
        self.assertIn("solution_change_session_workflow", seams)

        ordered = "\n".join(str(item) for item in (plan.get("ordered_extraction_sequence") or []))
        self.assertIn("extract_runtime_run_handlers", ordered)
        self.assertIn("extract_solution_change_session_workflow", ordered)

        destinations = set(str(item) for item in (plan.get("destination_modules") or []))
        self.assertIn("backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py", destinations)
        self.assertIn("backend/xyn_orchestrator/solution_change_session/stage_apply_git.py", destinations)

        file_destinations = {
            str((op or {}).get("destination") or "")
            for op in (plan.get("file_operations") or [])
            if isinstance(op, dict)
        }
        self.assertIn("backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py", file_destinations)
        self.assertIn("backend/xyn_orchestrator/solution_change_session/stage_apply_git.py", file_destinations)

        affected_tests = set(str(item) for item in (plan.get("affected_tests") or []))
        self.assertIn("xyn_orchestrator.tests.test_goal_planning", affected_tests)
        self.assertIn("xyn_orchestrator.tests.test_solution_change_session_repo_commits", affected_tests)

        test_targets = {
            str((op or {}).get("target") or "")
            for op in (plan.get("test_operations") or [])
            if isinstance(op, dict)
        }
        self.assertIn("xyn_orchestrator.tests.test_goal_planning", test_targets)
        self.assertIn("xyn_orchestrator.tests.test_solution_change_session_repo_commits", test_targets)

    def test_resolves_xyn_api_without_dragging_weak_related_artifacts(self):
        request_text = "Please decompose backend/xyn_orchestrator/xyn_api.py into focused modules."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=[],
        )
        self.assertEqual(plan.get("planning_mode"), "decompose_existing_system")
        self.assertEqual((plan.get("resolved_artifact") or {}).get("slug"), "xyn-api")
        self.assertEqual(plan.get("selected_artifact_ids"), ["api-1"])
        self.assertEqual(plan.get("scope_mode"), "minimal")
        self.assertEqual(plan.get("additional_artifacts"), [])
