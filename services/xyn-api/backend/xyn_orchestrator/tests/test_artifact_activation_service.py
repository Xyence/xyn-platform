from __future__ import annotations

from unittest import TestCase, mock

from xyn_orchestrator.artifact_activation import (
    _app_spec_signature,
    ArtifactActivationError,
    build_activation_payload,
    find_inflight_activation,
    runtime_record_matches_revision_anchor,
    submit_artifact_activation,
)


class ArtifactActivationServiceTests(TestCase):
    def test_build_activation_payload_uses_appspec_identity_and_revision_anchor(self) -> None:
        manifest = {
            "artifact": {"id": "app.real-estate-deal-finder"},
            "content": {
                "app_spec": {
                    "app_slug": "real-estate-deal-finder",
                    "title": "Real Estate Deal Finder",
                    "entities": ["deals", "properties", "deals"],
                    "requested_visuals": ["deal_board"],
                },
                "runtime_config": {
                    "source_job_id": "job-123",
                    "app_spec_artifact_id": "appspec-123",
                },
            },
        }
        payload = build_activation_payload(
            workspace_id="ws-1",
            workspace_slug="development",
            artifact_id="art-1",
            artifact_slug="app.real-estate-deal-finder",
            artifact_title="Real Estate Deal Finder",
            artifact_package_version="0.0.1-dev",
            manifest=manifest,
        )
        self.assertEqual(payload["app_slug"], "real-estate-deal-finder")
        revision_anchor = payload["revision_anchor"]
        self.assertEqual(revision_anchor["workspace_id"], "ws-1")
        self.assertEqual(revision_anchor["artifact_slug"], "app.real-estate-deal-finder")
        self.assertEqual(revision_anchor["app_slug"], "real-estate-deal-finder")
        self.assertEqual(payload.get("policy_source"), "reconstructed")

    def test_build_activation_payload_includes_policy_override_when_provided(self) -> None:
        manifest = {
            "artifact": {"id": "app.real-estate-deal-finder"},
            "content": {
                "app_spec": {
                    "app_slug": "real-estate-deal-finder",
                    "title": "Real Estate Deal Finder",
                    "entities": ["deals"],
                    "requested_visuals": [],
                },
                "runtime_config": {},
            },
        }
        policy_bundle = {
            "schema_version": "xyn.policy_bundle.v0",
            "bundle_id": "policy.real-estate-deal-finder",
            "app_slug": "real-estate-deal-finder",
            "workspace_id": "ws-1",
            "title": "Deal Finder Policy Bundle",
            "policies": {},
        }
        payload = build_activation_payload(
            workspace_id="ws-1",
            workspace_slug="development",
            artifact_id="art-1",
            artifact_slug="app.real-estate-deal-finder",
            artifact_title="Real Estate Deal Finder",
            artifact_package_version="0.0.1-dev",
            manifest=manifest,
            policy_bundle=policy_bundle,
            policy_artifact_ref={"artifact_id": "policy-art", "artifact_slug": "policy.real-estate-deal-finder"},
        )
        content = payload.get("draft_payload", {}).get("content_json", {})
        self.assertEqual(payload.get("policy_source"), "artifact")
        self.assertEqual(content.get("policy_source"), "artifact")
        self.assertEqual(content.get("policy_bundle_override"), policy_bundle)
        self.assertEqual(content.get("policy_artifact_ref", {}).get("artifact_slug"), "policy.real-estate-deal-finder")

    def test_policy_compatibility_match_when_derivation_signature_matches(self) -> None:
        app_spec = {
            "app_slug": "real-estate-deal-finder",
            "title": "Real Estate Deal Finder",
            "entities": ["deals"],
            "entity_contracts": [],
            "requested_visuals": [],
        }
        manifest = {
            "artifact": {"id": "app.real-estate-deal-finder"},
            "content": {"app_spec": app_spec, "runtime_config": {}},
        }
        policy_bundle = {
            "schema_version": "xyn.policy_bundle.v0",
            "bundle_id": "policy.real-estate-deal-finder",
            "app_slug": "real-estate-deal-finder",
            "workspace_id": "ws-1",
            "title": "Deal Finder Policy Bundle",
            "policies": {},
            "derivation": {"app_spec_signature": _app_spec_signature(app_spec)},
        }
        payload = build_activation_payload(
            workspace_id="ws-1",
            workspace_slug="development",
            artifact_id="art-1",
            artifact_slug="app.real-estate-deal-finder",
            artifact_title="Real Estate Deal Finder",
            artifact_package_version="0.0.1-dev",
            manifest=manifest,
            policy_bundle=policy_bundle,
        )
        self.assertEqual(payload.get("policy_compatibility"), "match")
        self.assertEqual(payload.get("policy_compatibility_reason"), "")

    def test_policy_compatibility_mismatch_when_derivation_signature_differs(self) -> None:
        app_spec = {
            "app_slug": "real-estate-deal-finder",
            "title": "Real Estate Deal Finder",
            "entities": ["deals", "properties"],
            "entity_contracts": [],
            "requested_visuals": [],
        }
        manifest = {
            "artifact": {"id": "app.real-estate-deal-finder"},
            "content": {"app_spec": app_spec, "runtime_config": {}},
        }
        policy_bundle = {
            "schema_version": "xyn.policy_bundle.v0",
            "bundle_id": "policy.real-estate-deal-finder",
            "app_slug": "real-estate-deal-finder",
            "workspace_id": "ws-1",
            "title": "Deal Finder Policy Bundle",
            "policies": {},
            "derivation": {"app_spec_signature": "deadbeef"},
        }
        payload = build_activation_payload(
            workspace_id="ws-1",
            workspace_slug="development",
            artifact_id="art-1",
            artifact_slug="app.real-estate-deal-finder",
            artifact_title="Real Estate Deal Finder",
            artifact_package_version="0.0.1-dev",
            manifest=manifest,
            policy_bundle=policy_bundle,
        )
        self.assertEqual(payload.get("policy_compatibility"), "mismatch")
        self.assertEqual(payload.get("policy_compatibility_reason"), "app_spec_signature_mismatch")

    def test_policy_compatibility_unknown_when_derivation_missing(self) -> None:
        app_spec = {
            "app_slug": "real-estate-deal-finder",
            "title": "Real Estate Deal Finder",
            "entities": ["deals"],
            "entity_contracts": [],
            "requested_visuals": [],
        }
        manifest = {
            "artifact": {"id": "app.real-estate-deal-finder"},
            "content": {"app_spec": app_spec, "runtime_config": {}},
        }
        policy_bundle = {
            "schema_version": "xyn.policy_bundle.v0",
            "bundle_id": "policy.real-estate-deal-finder",
            "app_slug": "real-estate-deal-finder",
            "workspace_id": "ws-1",
            "title": "Deal Finder Policy Bundle",
            "policies": {},
        }
        payload = build_activation_payload(
            workspace_id="ws-1",
            workspace_slug="development",
            artifact_id="art-1",
            artifact_slug="app.real-estate-deal-finder",
            artifact_title="Real Estate Deal Finder",
            artifact_package_version="0.0.1-dev",
            manifest=manifest,
            policy_bundle=policy_bundle,
        )
        self.assertEqual(payload.get("policy_compatibility"), "unknown")
        self.assertEqual(payload.get("policy_compatibility_reason"), "missing_derivation_signature")

    def test_build_activation_payload_rejects_missing_app_spec(self) -> None:
        with self.assertRaises(ArtifactActivationError):
            build_activation_payload(
                workspace_id="ws-1",
                workspace_slug="development",
                artifact_id="art-1",
                artifact_slug="app.real-estate-deal-finder",
                artifact_title="Real Estate Deal Finder",
                artifact_package_version="0.0.1-dev",
                manifest={"content": {}},
            )

    def test_submit_artifact_activation_posts_create_then_submit(self) -> None:
        create_response = mock.Mock(status_code=201, content=b'{"id":"draft-1"}', text='{"id":"draft-1"}')
        create_response.json.return_value = {"id": "draft-1"}
        submit_response = mock.Mock(status_code=200, content=b'{"job_id":"job-1"}', text='{"job_id":"job-1"}')
        submit_response.json.return_value = {"job_id": "job-1"}
        seed_api = mock.Mock(side_effect=[create_response, submit_response])
        result = submit_artifact_activation(
            workspace_slug="development",
            draft_payload={"type": "app_intent", "status": "ready", "content_json": {}},
            seed_api_request=seed_api,
        )
        self.assertEqual(result["draft_id"], "draft-1")
        self.assertEqual(result["job_id"], "job-1")
        self.assertEqual(seed_api.call_count, 2)

    def test_runtime_record_match_requires_artifact_slug_alignment(self) -> None:
        runtime_record = {
            "instance": mock.Mock(id="inst-1"),
            "runtime_target": {
                "app_slug": "real-estate-deal-finder",
                "installed_artifact_slug": "app.real-estate-deal-finder",
            },
        }
        revision_anchor = {
            "app_slug": "real-estate-deal-finder",
            "artifact_slug": "app.real-estate-deal-finder",
            "workspace_app_instance_id": "",
        }
        ok, reason = runtime_record_matches_revision_anchor(
            runtime_record=runtime_record,
            revision_anchor=revision_anchor,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "reused")

    def test_runtime_record_match_rejects_mismatched_artifact_slug(self) -> None:
        runtime_record = {
            "instance": mock.Mock(id="inst-1"),
            "runtime_target": {
                "app_slug": "real-estate-deal-finder",
                "installed_artifact_slug": "app.other-artifact",
            },
        }
        revision_anchor = {
            "app_slug": "real-estate-deal-finder",
            "artifact_slug": "app.real-estate-deal-finder",
            "workspace_app_instance_id": "",
        }
        ok, reason = runtime_record_matches_revision_anchor(
            runtime_record=runtime_record,
            revision_anchor=revision_anchor,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "runtime_artifact_slug_mismatch")

    def test_find_inflight_activation_matches_same_anchor(self) -> None:
        expected_anchor = {
            "workspace_id": "ws-1",
            "artifact_slug": "app.real-estate-deal-finder",
            "app_slug": "real-estate-deal-finder",
            "workspace_app_instance_id": "",
        }
        jobs_response = mock.Mock(
            status_code=200,
            content=b"[]",
            text="[]",
        )
        jobs_response.json.return_value = [
            {
                "id": "job-1",
                "type": "generate_app_spec",
                "status": "queued",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
                "input_json": {
                    "draft_id": "draft-1",
                    "content_json": {
                        "revision_anchor": {
                            "workspace_id": "ws-1",
                            "artifact_slug": "app.real-estate-deal-finder",
                            "app_slug": "real-estate-deal-finder",
                        }
                    },
                },
            }
        ]
        seed_api = mock.Mock(return_value=jobs_response)
        inflight = find_inflight_activation(
            workspace_slug="development",
            revision_anchor=expected_anchor,
            seed_api_request=seed_api,
        )
        self.assertIsNotNone(inflight)
        self.assertEqual(inflight["job_id"], "job-1")
        self.assertEqual(inflight["draft_id"], "draft-1")

    def test_find_inflight_activation_does_not_match_different_artifact(self) -> None:
        expected_anchor = {
            "workspace_id": "ws-1",
            "artifact_slug": "app.real-estate-deal-finder",
            "app_slug": "real-estate-deal-finder",
            "workspace_app_instance_id": "",
        }
        jobs_response = mock.Mock(
            status_code=200,
            content=b"[]",
            text="[]",
        )
        jobs_response.json.return_value = [
            {
                "id": "job-1",
                "type": "generate_app_spec",
                "status": "queued",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
                "input_json": {
                    "draft_id": "draft-1",
                    "content_json": {
                        "revision_anchor": {
                            "workspace_id": "ws-1",
                            "artifact_slug": "app.other-artifact",
                            "app_slug": "real-estate-deal-finder",
                        }
                    },
                },
            }
        ]
        seed_api = mock.Mock(return_value=jobs_response)
        inflight = find_inflight_activation(
            workspace_slug="development",
            revision_anchor=expected_anchor,
            seed_api_request=seed_api,
        )
        self.assertIsNone(inflight)
