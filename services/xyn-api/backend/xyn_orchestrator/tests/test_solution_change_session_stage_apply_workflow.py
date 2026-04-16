from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from xyn_orchestrator.api.runtime import intent_resolution
from xyn_orchestrator.api.solutions import (
    solution_change_plan_generation,
    solution_change_preview_validation,
    solution_change_session_workflow,
)
from xyn_orchestrator.solution_change_session import stage_apply_workflow
from xyn_orchestrator.solution_change_session.stage_apply_dispatch import stage_solution_change_dispatch_dev_tasks
from xyn_orchestrator.solution_change_session.stage_apply_scoping import (
    resolve_stage_apply_target_branch,
    solution_change_stage_artifact_plan_steps,
    solution_change_stage_repo_work_item_seed,
    solution_change_stage_work_item_seed,
)


class SolutionChangeSessionStageApplyWorkflowTests(SimpleTestCase):
    def test_scoping_seed_functions_produce_stable_suffix(self):
        session = SimpleNamespace(id="1e489d87-909f-4b22-ab8b-9f6bbcf35ffd")
        artifact = SimpleNamespace(id="66f2908d-cbf8-48ad-9a50-c7eb741f7549", slug="xyn-api")

        seed = solution_change_stage_work_item_seed(session=session, artifact=artifact, sequence=3)
        repo_seed = solution_change_stage_repo_work_item_seed(session=session, repo_slug="xyn-platform", sequence=2)

        self.assertTrue(seed.endswith("-3"))
        self.assertIn("solution", seed)
        self.assertTrue(repo_seed.endswith("-2"))
        self.assertIn("xyn-platform", repo_seed)

    def test_scoping_plan_steps_fallbacks(self):
        session = SimpleNamespace(request_text="Refactor seam extraction")
        self.assertEqual(
            solution_change_stage_artifact_plan_steps(
                artifact_id="a1",
                session=session,
                plan={},
                planned_work_by_artifact={"a1": ["step 1", "step 2"]},
            ),
            ["step 1", "step 2"],
        )
        self.assertEqual(
            solution_change_stage_artifact_plan_steps(
                artifact_id="a1",
                session=session,
                plan={"proposed_work": ["proposed"]},
                planned_work_by_artifact={},
            ),
            ["proposed"],
        )
        self.assertEqual(
            solution_change_stage_artifact_plan_steps(
                artifact_id="a1",
                session=session,
                plan={},
                planned_work_by_artifact={},
            ),
            ["Implement requested change: Refactor seam extraction"],
        )

    def test_dispatch_contract_returns_empty_without_dispatch_user(self):
        payload = stage_solution_change_dispatch_dev_tasks(
            session=SimpleNamespace(),
            selected_members=[],
            staged_artifacts=[],
            planned_work_by_artifact={},
            plan={},
            dispatch_user=None,
            resolve_artifact_ownership=lambda artifact: {},
            artifact_slug=lambda artifact: "",
            solution_change_stage_artifact_plan_steps=lambda **kwargs: [],
            resolve_stage_apply_target_branch=lambda **kwargs: ("", "", ""),
            resolve_local_repo_root=lambda repo_slug: None,
            git_repo_dirty_files=lambda repo_root: ([], ""),
            solution_change_stage_repo_work_item_seed=lambda **kwargs: "",
            submit_dev_task_runtime_run=lambda *args, **kwargs: {},
        )
        self.assertEqual(payload, {"execution_runs": [], "per_repo_results": []})

    def test_workflow_module_re_exports_extracted_seams(self):
        self.assertIs(stage_apply_workflow.solution_change_stage_work_item_seed, solution_change_stage_work_item_seed)
        self.assertIs(stage_apply_workflow.stage_solution_change_dispatch_dev_tasks, stage_solution_change_dispatch_dev_tasks)

    def test_solution_api_adapters_normalize_contracts(self):
        plan = solution_change_plan_generation(
            session=SimpleNamespace(),
            memberships=[],
            force_code_aware_planning=False,
            generate_fn=lambda **kwargs: {},
        )
        self.assertEqual(plan.get("proposed_work"), [])
        self.assertEqual(plan.get("implementation_steps"), [])

        preview = solution_change_preview_validation(
            session=SimpleNamespace(),
            mode="prepare_preview",
            prepare_fn=lambda **kwargs: {"status": "ready"},
            validate_fn=lambda **kwargs: {},
        )
        self.assertEqual(preview.get("status"), "ready")

        with self.assertRaises(ValueError):
            solution_change_preview_validation(
                session=SimpleNamespace(),
                mode="invalid",
                prepare_fn=lambda **kwargs: {},
                validate_fn=lambda **kwargs: {},
            )

        staged = solution_change_session_workflow(
            session=SimpleNamespace(),
            memberships=[],
            dispatch_runtime=False,
            dispatch_user=None,
            stage_apply_fn=lambda **kwargs: {},
        )
        self.assertEqual(staged.get("artifact_states"), [])
        self.assertEqual(staged.get("overall_state"), "staged")

    def test_runtime_intent_resolution_adapter_normalizes_payload(self):
        resolved = intent_resolution(request=mock.Mock(), resolve_fn=lambda request: {})
        self.assertEqual(resolved.get("status"), "ok")
        self.assertEqual(resolved.get("intent"), {})

    def test_resolve_stage_apply_target_branch_allocates_session_isolated_branch(self):
        repo_root = "/tmp/xyn-platform"
        session = SimpleNamespace(id="61028b19-34df-4fe6-b082-fac6f22e05d6")
        run_results = [
            mock.Mock(returncode=0, stdout="develop\n", stderr=""),
            mock.Mock(returncode=1, stdout="", stderr=""),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ]

        with mock.patch("xyn_orchestrator.solution_change_session.stage_apply_scoping.subprocess.run", side_effect=run_results) as run_mock:
            branch, source, error = resolve_stage_apply_target_branch(
                repo_slug="xyn-platform",
                fallback_branch="develop",
                resolve_local_repo_root=lambda _repo_slug: repo_root,
                session=session,
            )

        self.assertEqual(source, "session_isolated_branch")
        self.assertEqual(error, "")
        self.assertTrue(branch.startswith("xyn/session/xyn-platform-61028b1934df"))
        create_call = run_mock.call_args_list[2][0][0]
        self.assertEqual(create_call[-3], "branch")
        self.assertEqual(create_call[-2], branch)
        self.assertEqual(create_call[-1], "develop")

    def test_resolve_stage_apply_target_branch_reuses_existing_session_branch(self):
        repo_root = "/tmp/xyn-platform"
        session = SimpleNamespace(id="61028b19-34df-4fe6-b082-fac6f22e05d6")
        run_results = [
            mock.Mock(returncode=0, stdout="develop\n", stderr=""),
            mock.Mock(returncode=0, stdout="xyn/session/xyn-platform-61028b1934df\n", stderr=""),
        ]

        with mock.patch("xyn_orchestrator.solution_change_session.stage_apply_scoping.subprocess.run", side_effect=run_results) as run_mock:
            branch, source, error = resolve_stage_apply_target_branch(
                repo_slug="xyn-platform",
                fallback_branch="develop",
                resolve_local_repo_root=lambda _repo_slug: repo_root,
                session=session,
            )

        self.assertEqual(source, "session_isolated_branch")
        self.assertEqual(error, "")
        self.assertTrue(branch.startswith("xyn/session/xyn-platform-61028b1934df"))
        self.assertEqual(run_mock.call_count, 2)
