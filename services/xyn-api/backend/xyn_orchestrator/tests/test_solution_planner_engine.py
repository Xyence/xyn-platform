from django.test import SimpleTestCase

from xyn_orchestrator.solution_change_session.planner_engine import (
    PlannerArtifactInput,
    build_solution_change_execution_plan,
)


class SolutionPlannerEngineTests(SimpleTestCase):
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
        request_text = "Update API payload and matching UI form rendering for the same workflow."
        plan = build_solution_change_execution_plan(
            request_text=request_text,
            base_plan={},
            artifacts=self._artifacts(),
            selected_artifact_ids=["api-1", "ui-1"],
        )
        self.assertEqual(plan.get("planning_mode"), "cross_artifact_change")
        self.assertGreaterEqual(len(plan.get("selected_artifact_ids") or []), 2)

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
