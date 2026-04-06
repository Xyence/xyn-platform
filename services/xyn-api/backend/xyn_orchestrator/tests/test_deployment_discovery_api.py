from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import ArtifactType, Blueprint, Module, ProvisionedInstance, ReleaseTarget, Workspace


class DeploymentDiscoveryApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(username="discovery-staff", password="pass", is_staff=True)
        self.client.force_login(self.staff)
        self.workspace, _ = Workspace.objects.get_or_create(slug="platform-builder", defaults={"name": "Platform Builder"})
        self.artifact_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})

    def test_release_target_discovery_empty_returns_list(self):
        response = self.client.get("/xyn/api/release-targets")
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("release_targets"), [])

    def test_artifact_discovery_empty_returns_list(self):
        response = self.client.get("/xyn/api/artifacts", {"limit": 10, "offset": 0, "query": "no-such-artifact-slug-xyz"})
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("artifacts"), [])
        self.assertEqual(payload.get("count"), 0)

    def test_release_target_and_artifact_discovery_non_empty(self):
        blueprint = Blueprint.objects.create(name="Deal Finder", namespace="real-estate")
        target = ReleaseTarget.objects.create(
            blueprint=blueprint,
            name="Deal Finder Dev",
            fqdn="deal.xyence.io",
            runtime_json={"transport": "ssm", "type": "docker-compose"},
            dns_json={"provider": "route53"},
        )
        rt_response = self.client.get("/xyn/api/release-targets")
        self.assertEqual(rt_response.status_code, 200, rt_response.content.decode())
        rt_payload = rt_response.json().get("release_targets") or []
        self.assertEqual(len(rt_payload), 1)
        self.assertEqual(rt_payload[0].get("name"), target.name)
        self.assertEqual((rt_payload[0].get("runtime") or {}).get("transport"), "ssm")
        self.assertEqual((rt_payload[0].get("dns") or {}).get("provider"), "route53")

        artifact_response = self.client.get("/xyn/api/artifacts")
        self.assertEqual(artifact_response.status_code, 200, artifact_response.content.decode())
        artifacts = artifact_response.json().get("artifacts") or []
        self.assertGreaterEqual(len(artifacts), 1)
        self.assertTrue(all(isinstance(row, dict) for row in artifacts))

    def test_release_target_discovery_id_is_addressable_for_detail_and_plan(self):
        blueprint = Blueprint.objects.create(name="Xyn Runtime", namespace="xyn")
        target = ReleaseTarget.objects.create(
            blueprint=blueprint,
            name="Xyn Sibling Target",
            fqdn="deal.xyence.io",
            environment="dev",
            target_instance_ref="d8d51bd3-4b13-4c3b-9a2d-f1b723f68862",
            runtime_json={"transport": "ssm", "type": "docker-compose"},
            dns_json={"provider": "route53", "zone_name": "xyence.io"},
            config_json={
                "id": "11111111-2222-3333-4444-555555555555",
                "name": "stale-config-id",
                "runtime": {"transport": "ssm", "type": "docker-compose"},
                "dns": {"provider": "route53"},
                "topology": {"kind": "sibling"},
            },
        )

        listing = self.client.get("/xyn/api/release-targets")
        self.assertEqual(listing.status_code, 200, listing.content.decode())
        rows = listing.json().get("release_targets") or []
        self.assertEqual(len(rows), 1)
        listed_id = rows[0].get("id")
        self.assertEqual(listed_id, str(target.id))

        detail = self.client.get(f"/xyn/api/release-targets/{listed_id}")
        self.assertEqual(detail.status_code, 200, detail.content.decode())
        self.assertEqual(detail.json().get("id"), str(target.id))

        plan = self.client.get(f"/xyn/api/release-targets/{listed_id}/deployment_plan")
        self.assertEqual(plan.status_code, 200, plan.content.decode())
        self.assertEqual(plan.json().get("release_target_id"), str(target.id))

    def test_release_target_deployment_preparation_evidence_create_and_read(self):
        blueprint = Blueprint.objects.create(name="Xyn Runtime", namespace="xyn")
        target = ReleaseTarget.objects.create(
            blueprint=blueprint,
            name="Xyn Sibling Target",
            fqdn="deal.xyence.io",
            environment="dev",
            target_instance_ref="d8d51bd3-4b13-4c3b-9a2d-f1b723f68862",
            runtime_json={"transport": "ssm", "type": "docker-compose"},
            dns_json={"provider": "route53", "zone_name": "xyence.io"},
            config_json={},
        )
        target_id = str(target.id)

        create = self.client.post(
            f"/xyn/api/release-targets/{target_id}/deployment_preparation_evidence",
            data={},
            content_type="application/json",
        )
        self.assertEqual(create.status_code, 200, create.content.decode())
        created = create.json().get("evidence") or {}
        self.assertEqual(created.get("release_target_id"), target_id)
        self.assertEqual(created.get("status"), "ready")
        self.assertFalse(created.get("mutation_performed", True))

        read = self.client.get(
            f"/xyn/api/release-targets/{target_id}/deployment_preparation_evidence",
            {"limit": 10},
        )
        self.assertEqual(read.status_code, 200, read.content.decode())
        evidence_rows = read.json().get("evidence") or []
        self.assertEqual(len(evidence_rows), 1)
        self.assertEqual((evidence_rows[0] or {}).get("evidence_id"), created.get("evidence_id"))

    def test_release_target_execution_handoff_consume_and_step_flow(self):
        blueprint = Blueprint.objects.create(name="Xyn Runtime", namespace="xyn")
        instance = ProvisionedInstance.objects.create(
            name="xyn-sibling-1",
            aws_region="us-east-1",
            instance_id="i-1234567890abcdef0",
            instance_type="t3.small",
            ami_id="ami-test",
            runtime_substrate="aws-ec2",
            status="running",
            created_by=self.staff,
            updated_by=self.staff,
        )
        target = ReleaseTarget.objects.create(
            blueprint=blueprint,
            name="Xyn Sibling Target",
            fqdn="deal.xyence.io",
            environment="dev",
            target_instance=instance,
            target_instance_ref=str(instance.id),
            runtime_json={
                "transport": "ssm",
                "type": "docker-compose",
                "remote_root": "/var/lib/xyn/ems",
                "compose_file_path": "docker-compose.yml",
            },
            dns_json={"provider": "route53", "zone_name": "xyence.io"},
            config_json={
                "id": "11111111-2222-3333-4444-555555555556",
                "blueprint_id": str(blueprint.id),
                "name": "Xyn Sibling Target",
                "environment": "dev",
                "target_instance_id": str(instance.id),
                "fqdn": "deal.xyence.io",
                "runtime": {
                    "transport": "ssm",
                    "type": "docker-compose",
                    "remote_root": "/var/lib/xyn/ems",
                    "compose_file_path": "docker-compose.yml",
                },
                "dns": {"provider": "route53", "zone_name": "xyence.io"},
                "topology": {"kind": "sibling"},
                "provider_binding": {
                    "provider_key": "deploy-ssm-compose",
                    "module_fqn": "core.deploy-ssm-compose",
                },
            },
        )
        Module.objects.create(
            namespace="core",
            name="deploy-ssm-compose",
            fqn="core.deploy-ssm-compose",
            type="lib",
            current_version="0.1.0",
            capabilities_provided_json=["deploy.ssm.run_shell", "runtime.compose.apply_remote"],
            interfaces_json={"operations": {"ensure_remote_runtime": "desc"}},
            latest_module_spec_json={
                "description": "Remote docker-compose deployment via AWS SSM RunCommand.",
                "metadata": {"labels": {"topology": "sibling"}},
                "module": {"capabilitiesProvided": ["deploy.ssm.run_shell", "runtime.compose.apply_remote"]},
            },
        )
        target_id = str(target.id)

        create_prep = self.client.post(
            f"/xyn/api/release-targets/{target_id}/deployment_preparation_evidence",
            data={},
            content_type="application/json",
        )
        self.assertEqual(create_prep.status_code, 200, create_prep.content.decode())
        prep_evidence_id = ((create_prep.json().get("evidence") or {}).get("evidence_id"))
        self.assertTrue(prep_evidence_id)

        create_handoff = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_preparation_handoff",
            data={"evidence_id": prep_evidence_id},
            content_type="application/json",
        )
        self.assertEqual(create_handoff.status_code, 200, create_handoff.content.decode())
        handoff = create_handoff.json().get("handoff") or {}
        self.assertEqual(handoff.get("status"), "ready")
        handoff_id = handoff.get("handoff_id")
        self.assertTrue(handoff_id)

        read_handoffs = self.client.get(f"/xyn/api/release-targets/{target_id}/execution_preparation_handoff", {"limit": 10})
        self.assertEqual(read_handoffs.status_code, 200, read_handoffs.content.decode())
        rows = read_handoffs.json().get("handoffs") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0] or {}).get("handoff_id"), handoff_id)

        consume_blocked = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_preparation_consume",
            data={"handoff_id": handoff_id},
            content_type="application/json",
        )
        self.assertEqual(consume_blocked.status_code, 409, consume_blocked.content.decode())
        consume_blocked_payload = consume_blocked.json()
        self.assertEqual(consume_blocked_payload.get("blocked_reason"), "approval_required")
        self.assertIn("approve_release_target_execution_preparation", consume_blocked_payload.get("next_allowed_actions") or [])

        approve = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_preparation_approval",
            data={"handoff_id": handoff_id, "approved_by": "test-suite"},
            content_type="application/json",
        )
        self.assertEqual(approve.status_code, 200, approve.content.decode())
        approval_payload = approve.json().get("approval") or {}
        self.assertEqual(approval_payload.get("source_handoff_ref"), handoff_id)
        self.assertTrue(approval_payload.get("approved"))

        consume = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_preparation_consume",
            data={"handoff_id": handoff_id},
            content_type="application/json",
        )
        self.assertEqual(consume.status_code, 200, consume.content.decode())
        consume_evidence = consume.json().get("evidence") or {}
        self.assertEqual(consume_evidence.get("status"), "prepared")
        self.assertEqual(consume_evidence.get("approval_source"), "recorded_approval")
        prepared_actions = consume_evidence.get("prepared_execution_actions") or []
        self.assertIn("runtime_marker_probe", prepared_actions)
        self.assertIn("runtime.compose.apply_remote", prepared_actions)
        readiness = (consume_evidence.get("execution_action_readiness") or {}).get("runtime.compose.apply_remote") or {}
        self.assertTrue(readiness.get("can_apply_remote"))
        self.assertEqual(readiness.get("blocked_reason"), "")
        checked = readiness.get("checked_preconditions") or []
        self.assertTrue(any((item or {}).get("name") == "provider_capability.runtime.compose.apply_remote" for item in checked))
        prep_exec_id = consume_evidence.get("preparation_evidence_id")
        self.assertTrue(prep_exec_id)

        step_blocked = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_step",
            data={
                "preparation_evidence_id": prep_exec_id,
                "action_key": "runtime_marker_probe",
            },
            content_type="application/json",
        )
        self.assertEqual(step_blocked.status_code, 409, step_blocked.content.decode())
        blocked_payload = step_blocked.json()
        self.assertEqual(blocked_payload.get("blocked_reason"), "approval_required")
        self.assertIn("approve_release_target_execution_step", blocked_payload.get("next_allowed_actions") or [])

        approve_step = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_step_approval",
            data={
                "preparation_evidence_id": prep_exec_id,
                "action_key": "runtime_marker_probe",
                "reason": "explicit_operator_approval",
            },
            content_type="application/json",
        )
        self.assertEqual(approve_step.status_code, 200, approve_step.content.decode())
        approval_payload = approve_step.json().get("approval") or {}
        self.assertEqual(approval_payload.get("action_key"), "runtime_marker_probe")
        self.assertTrue(approval_payload.get("approved"))

        step = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_step",
            data={
                "preparation_evidence_id": prep_exec_id,
                "action_key": "runtime_marker_probe",
            },
            content_type="application/json",
        )
        self.assertEqual(step.status_code, 200, step.content.decode())
        step_payload = step.json().get("step") or {}
        self.assertEqual(step_payload.get("status"), "succeeded")
        self.assertEqual(step_payload.get("action_key"), "runtime_marker_probe")
        self.assertEqual(step_payload.get("approval_source"), "recorded_approval")
        self.assertFalse(step_payload.get("mutation_performed", True))

        approve_apply = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_step_approval",
            data={
                "preparation_evidence_id": prep_exec_id,
                "action_key": "runtime.compose.apply_remote",
                "reason": "explicit_operator_approval",
            },
            content_type="application/json",
        )
        self.assertEqual(approve_apply.status_code, 200, approve_apply.content.decode())
        self.assertTrue((approve_apply.json().get("approval") or {}).get("approved"))

        with mock.patch("xyn_orchestrator.xyn_api._run_ssm_commands") as run_ssm:
            run_ssm.return_value = {
                "ssm_command_id": "cmd-apply-1",
                "invocation_status": "Success",
                "response_code": 0,
                "stdout": "apply complete",
                "stderr": "",
            }
            run_apply = self.client.post(
                f"/xyn/api/release-targets/{target_id}/execution_step",
                data={
                    "preparation_evidence_id": prep_exec_id,
                    "action_key": "runtime.compose.apply_remote",
                },
                content_type="application/json",
            )
        self.assertEqual(run_apply.status_code, 200, run_apply.content.decode())
        run_apply_step = run_apply.json().get("step") or {}
        self.assertEqual(run_apply_step.get("status"), "succeeded")
        self.assertEqual(run_apply_step.get("action_key"), "runtime.compose.apply_remote")
        self.assertEqual(run_apply_step.get("approval_source"), "recorded_approval")
        self.assertTrue(run_apply_step.get("mutation_performed"))
        self.assertEqual(((run_apply_step.get("result") or {}).get("ssm_command_id")), "cmd-apply-1")

        step_history = self.client.get(f"/xyn/api/release-targets/{target_id}/execution_step", {"limit": 10})
        self.assertEqual(step_history.status_code, 200, step_history.content.decode())
        step_rows = step_history.json().get("steps") or []
        self.assertGreaterEqual(len(step_rows), 2)
        action_keys = [str((item or {}).get("action_key") or "") for item in step_rows]
        self.assertIn("runtime_marker_probe", action_keys)
        self.assertIn("runtime.compose.apply_remote", action_keys)

    def test_runtime_compose_apply_remote_step_blocks_on_preflight_probe_failure(self):
        blueprint = Blueprint.objects.create(name="Xyn Runtime", namespace="xyn")
        instance = ProvisionedInstance.objects.create(
            name="xyn-sibling-preflight",
            aws_region="us-east-1",
            instance_id="i-preflight",
            instance_type="t3.small",
            ami_id="ami-test",
            runtime_substrate="aws-ec2",
            status="running",
            created_by=self.staff,
            updated_by=self.staff,
        )
        target = ReleaseTarget.objects.create(
            blueprint=blueprint,
            name="Xyn Sibling Target",
            fqdn="deal.xyence.io",
            environment="dev",
            target_instance=instance,
            target_instance_ref=str(instance.id),
            runtime_json={
                "transport": "ssm",
                "type": "docker-compose",
                "remote_root": "/var/lib/xyn/ems",
                "compose_file_path": "docker-compose.yml",
            },
            dns_json={"provider": "route53", "zone_name": "xyence.io"},
            config_json={
                "id": "11111111-2222-3333-4444-555555555557",
                "blueprint_id": str(blueprint.id),
                "name": "Xyn Sibling Target",
                "environment": "dev",
                "target_instance_id": str(instance.id),
                "fqdn": "deal.xyence.io",
                "runtime": {
                    "transport": "ssm",
                    "type": "docker-compose",
                    "remote_root": "/var/lib/xyn/ems",
                    "compose_file_path": "docker-compose.yml",
                },
                "dns": {"provider": "route53", "zone_name": "xyence.io"},
                "topology": {"kind": "sibling"},
                "provider_binding": {
                    "provider_key": "deploy-ssm-compose",
                    "module_fqn": "core.deploy-ssm-compose",
                },
            },
        )
        Module.objects.create(
            namespace="core",
            name="deploy-ssm-compose",
            fqn="core.deploy-ssm-compose",
            type="lib",
            current_version="0.1.0",
            capabilities_provided_json=["deploy.ssm.run_shell", "runtime.compose.apply_remote"],
            interfaces_json={"operations": {"ensure_remote_runtime": "desc"}},
            latest_module_spec_json={
                "description": "Remote docker-compose deployment via AWS SSM RunCommand.",
                "metadata": {"labels": {"topology": "sibling"}},
                "module": {"capabilitiesProvided": ["deploy.ssm.run_shell", "runtime.compose.apply_remote"]},
            },
        )
        target_id = str(target.id)

        prep = self.client.post(
            f"/xyn/api/release-targets/{target_id}/deployment_preparation_evidence",
            data={},
            content_type="application/json",
        ).json()
        evidence_id = ((prep.get("evidence") or {}).get("evidence_id"))
        handoff = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_preparation_handoff",
            data={"evidence_id": evidence_id},
            content_type="application/json",
        ).json()
        handoff_id = ((handoff.get("handoff") or {}).get("handoff_id"))
        self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_preparation_approval",
            data={"handoff_id": handoff_id},
            content_type="application/json",
        )
        consume = self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_preparation_consume",
            data={"handoff_id": handoff_id},
            content_type="application/json",
        ).json()
        prep_exec_id = ((consume.get("evidence") or {}).get("preparation_evidence_id"))
        self.client.post(
            f"/xyn/api/release-targets/{target_id}/execution_step_approval",
            data={"preparation_evidence_id": prep_exec_id, "action_key": "runtime.compose.apply_remote"},
            content_type="application/json",
        )

        with mock.patch("xyn_orchestrator.xyn_api._run_ssm_commands", side_effect=RuntimeError("ssm probe failed")):
            run_apply = self.client.post(
                f"/xyn/api/release-targets/{target_id}/execution_step",
                data={"preparation_evidence_id": prep_exec_id, "action_key": "runtime.compose.apply_remote"},
                content_type="application/json",
            )
        self.assertEqual(run_apply.status_code, 409, run_apply.content.decode())
        step = run_apply.json().get("step") or {}
        self.assertEqual(step.get("status"), "blocked")
        self.assertFalse(step.get("mutation_performed", True))
        result = step.get("result") or {}
        self.assertEqual(result.get("blocked_reason"), "apply_remote_preflight_error")
        self.assertTrue(((result.get("readiness") or {}).get("checked_preconditions") or []))

    @mock.patch("xyn_orchestrator.xyn_api.maybe_sync_modules_from_registry")
    def test_deployment_provider_discovery_empty_and_non_empty(self, sync_mock: mock.Mock):
        sync_mock.return_value = 0
        Module.objects.all().delete()

        empty_response = self.client.get("/xyn/api/deployment-providers")
        self.assertEqual(empty_response.status_code, 200, empty_response.content.decode())
        self.assertEqual(empty_response.json().get("providers"), [])
        self.assertEqual(empty_response.json().get("count"), 0)

        module = Module.objects.create(
            namespace="core",
            name="deploy-ssm-compose",
            fqn="core.deploy-ssm-compose",
            type="lib",
            current_version="0.1.0",
            capabilities_provided_json=["deploy.ssm.run_shell", "runtime.compose.apply_remote"],
            interfaces_json={"operations": {"ensure_remote_runtime": "desc"}},
            latest_module_spec_json={
                "description": "Remote docker-compose deployment via AWS SSM RunCommand.",
                "metadata": {"labels": {"topology": "sibling"}},
                "module": {"capabilitiesProvided": ["deploy.ssm.run_shell", "runtime.compose.apply_remote"]},
            },
        )

        response = self.client.get("/xyn/api/deployment-providers")
        self.assertEqual(response.status_code, 200, response.content.decode())
        providers = response.json().get("providers") or []
        self.assertEqual(len(providers), 1)
        provider = providers[0]
        self.assertEqual(provider.get("provider_key"), module.name)
        self.assertIn("plan", provider.get("supported_operations") or [])
        self.assertIn("execute", provider.get("supported_operations") or [])
        self.assertIn("runtime.compose.apply_remote", provider.get("known_capabilities") or [])
        self.assertEqual(provider.get("supported_topologies"), ["sibling"])

        detail = self.client.get(f"/xyn/api/deployment-providers/{module.name}")
        self.assertEqual(detail.status_code, 200, detail.content.decode())
        detail_provider = (detail.json().get("provider") or {})
        self.assertEqual(detail_provider.get("provider_key"), module.name)
        self.assertEqual(detail_provider.get("module_fqn"), module.fqn)
