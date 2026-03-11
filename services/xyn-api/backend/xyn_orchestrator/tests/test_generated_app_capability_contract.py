import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import Artifact, ArtifactType, RoleBinding, UserIdentity, Workspace, WorkspaceAppInstance, WorkspaceArtifactBinding


class _FakeResponse:
    def __init__(self, *, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else []
        self.headers = {"content-type": "application/json"}
        self.content = json.dumps(self._body).encode("utf-8")

    def json(self):
        return self._body


class GeneratedAppCapabilityContractTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="cap-admin", password="pass", is_staff=True)
        self.client.force_login(self.user)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="cap-admin",
            email="cap-admin@example.com",
        )
        RoleBinding.objects.create(user_identity=self.identity, scope_kind="platform", role="platform_admin")
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()
        self.workspace = Workspace.objects.create(slug="capability-lab", name="Capability Lab")
        self.application_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})

    def _manifest(
        self,
        *,
        include_interfaces: bool,
        stale_top_level_interfaces: bool = False,
        stale_top_level_interface_surface: bool = False,
    ) -> dict:
        suggestions = [
            {"id": "show-devices", "name": "Show Devices", "prompt": "Show devices", "visibility": ["capability", "palette"], "order": 100},
            {"id": "show-locations", "name": "Show Locations", "prompt": "Show locations", "visibility": ["capability", "palette"], "order": 110},
            {"id": "create-device", "name": "Create Device", "prompt": "Create device", "visibility": ["capability", "palette"], "order": 120},
            {"id": "update-device", "name": "Update Device", "prompt": "Update device", "visibility": ["capability", "palette"], "order": 125},
            {"id": "delete-device", "name": "Delete Device", "prompt": "Delete device", "visibility": ["capability", "palette"], "order": 127},
            {"id": "create-location", "name": "Create Location", "prompt": "Create location", "visibility": ["capability", "palette"], "order": 125},
            {"id": "update-location", "name": "Update Location", "prompt": "Update location", "visibility": ["capability", "palette"], "order": 128},
            {"id": "delete-location", "name": "Delete Location", "prompt": "Delete location", "visibility": ["capability", "palette"], "order": 129},
            {
                "id": "devices-by-status",
                "name": "Devices by Status",
                "prompt": "Show devices by status",
                "visibility": ["capability", "landing", "palette"],
                "order": 130,
            },
        ]
        commands = [
            {
                "key": "show devices",
                "prompt": "show devices",
                "name": "Show Devices",
                "group": "Devices",
                "order": 100,
                "handler": {
                    "method": "GET",
                    "path": "/devices",
                    "query_map": {"workspace_id": "$workspace_id"},
                    "response_adapter": {"kind": "table", "columns": ["id", "name", "kind", "status", "location_id"]},
                },
            },
            {
                "key": "show locations",
                "prompt": "show locations",
                "name": "Show Locations",
                "group": "Locations",
                "order": 110,
                "handler": {
                    "method": "GET",
                    "path": "/locations",
                    "query_map": {"workspace_id": "$workspace_id"},
                    "response_adapter": {"kind": "table", "columns": ["id", "name", "kind", "city", "region", "country"]},
                },
            },
            {
                "key": "create device",
                "prompt": "create device",
                "name": "Create Device",
                "group": "Devices",
                "order": 120,
                "handler": {
                    "method": "POST",
                    "path": "/devices",
                    "body_map": {"workspace_id": "$workspace_id"},
                    "response_adapter": {"kind": "table", "columns": ["id", "name", "kind", "status", "location_id"]},
                    "entity_key": "devices",
                    "entity_operation": "create",
                },
            },
            {
                "key": "update device",
                "prompt": "update device",
                "name": "Update Device",
                "group": "Devices",
                "order": 125,
                "handler": {
                    "method": "PATCH",
                    "path": "/devices/{id}",
                    "query_map": {"workspace_id": "$workspace_id"},
                    "response_adapter": {"kind": "table", "columns": ["id", "name", "kind", "status", "location_id"]},
                    "entity_key": "devices",
                    "entity_operation": "update",
                },
            },
            {
                "key": "delete device",
                "prompt": "delete device",
                "name": "Delete Device",
                "group": "Devices",
                "order": 127,
                "handler": {
                    "method": "DELETE",
                    "path": "/devices/{id}",
                    "query_map": {"workspace_id": "$workspace_id"},
                    "response_adapter": {"kind": "table", "columns": ["id", "name", "kind", "status", "location_id"]},
                    "entity_key": "devices",
                    "entity_operation": "delete",
                },
            },
            {
                "key": "create location",
                "prompt": "create location",
                "name": "Create Location",
                "group": "Locations",
                "order": 128,
                "handler": {
                    "method": "POST",
                    "path": "/locations",
                    "body_map": {"workspace_id": "$workspace_id"},
                    "response_adapter": {"kind": "table", "columns": ["id", "name", "kind", "city", "region", "country"]},
                    "entity_key": "locations",
                    "entity_operation": "create",
                },
            },
        ]
        latent = [
            {
                "key": "show interfaces",
                "prompt": "show interfaces",
                "name": "Show Interfaces",
                "group": "Interfaces",
                "order": 140,
                "handler": {
                    "method": "GET",
                    "path": "/interfaces",
                    "query_map": {"workspace_id": "$workspace_id"},
                    "response_adapter": {"kind": "table", "columns": ["id", "device_id", "name", "status", "workspace_id"]},
                },
            }
        ]
        if include_interfaces:
            suggestions.append(
                {"id": "show-interfaces", "name": "Show Interfaces", "prompt": "Show interfaces", "visibility": ["capability", "palette"], "order": 140}
            )
            suggestions.append(
                {"id": "update-interface", "name": "Update Interface", "prompt": "Update interface", "visibility": ["capability", "palette"], "order": 145}
            )
            suggestions.append(
                {"id": "delete-interface", "name": "Delete Interface", "prompt": "Delete interface", "visibility": ["capability", "palette"], "order": 147}
            )
            commands.append(latent[0])
            commands.extend(
                [
                    {
                        "key": "update interface",
                        "prompt": "update interface",
                        "name": "Update Interface",
                        "group": "Interfaces",
                        "order": 145,
                        "handler": {
                            "method": "PATCH",
                            "path": "/interfaces/{id}",
                            "query_map": {"workspace_id": "$workspace_id"},
                            "response_adapter": {"kind": "table", "columns": ["id", "device_id", "name", "status", "workspace_id"]},
                            "entity_key": "interfaces",
                            "entity_operation": "update",
                        },
                    },
                    {
                        "key": "delete interface",
                        "prompt": "delete interface",
                        "name": "Delete Interface",
                        "group": "Interfaces",
                        "order": 147,
                        "handler": {
                            "method": "DELETE",
                            "path": "/interfaces/{id}",
                            "query_map": {"workspace_id": "$workspace_id"},
                            "response_adapter": {"kind": "table", "columns": ["id", "device_id", "name", "status", "workspace_id"]},
                            "entity_key": "interfaces",
                            "entity_operation": "delete",
                        },
                    },
                ]
            )
            latent = []
        elif stale_top_level_interfaces:
            suggestions.append(
                {"id": "show-interfaces", "name": "Show Interfaces", "prompt": "Show interfaces", "visibility": ["capability", "palette"], "order": 140}
            )
        resolved = {
            "schema_version": "xyn.capability_manifest.v1",
            "app": {"app_slug": "net-inventory", "title": "Generated Net Inventory", "workspace_id": str(self.workspace.id)},
            "views": [
                {"id": "workbench-manage", "label": "Workbench", "path": "/app/workbench", "surface": "manage"},
                {"id": "workbench-docs", "label": "Workbench", "path": "/app/workbench", "surface": "docs"},
            ],
            "commands": commands,
            "routes": [{"id": "devices", "path": "/devices", "kind": "collection"}],
            "reports": [],
            "operations": [],
            "entities": [
                {
                    "key": "devices",
                    "singular_label": "device",
                    "plural_label": "devices",
                    "collection_path": "/devices",
                    "item_path_template": "/devices/{id}",
                    "operations": {
                        "list": {"declared": True, "method": "GET", "path": "/devices"},
                        "get": {"declared": True, "method": "GET", "path": "/devices/{id}"},
                        "create": {"declared": True, "method": "POST", "path": "/devices"},
                        "update": {"declared": True, "method": "PATCH", "path": "/devices/{id}"},
                        "delete": {"declared": True, "method": "DELETE", "path": "/devices/{id}"},
                    },
                    "fields": [
                        {"name": "id", "type": "uuid", "required": True, "readable": True, "writable": False, "identity": True},
                        {"name": "workspace_id", "type": "uuid", "required": True, "readable": True, "writable": True, "identity": False},
                        {"name": "name", "type": "string", "required": True, "readable": True, "writable": True, "identity": True},
                        {
                            "name": "location_id",
                            "type": "uuid|null",
                            "required": False,
                            "readable": True,
                            "writable": True,
                            "identity": True,
                            "relation": {"target_entity": "locations", "target_field": "id", "relation_kind": "belongs_to"},
                        },
                    ],
                    "presentation": {
                        "default_list_fields": ["name", "kind", "status", "location_id"],
                        "default_detail_fields": ["id", "name", "kind", "status", "location_id"],
                        "title_field": "name",
                    },
                    "validation": {
                        "required_on_create": ["workspace_id", "name"],
                        "allowed_on_update": ["name", "kind", "status", "location_id"],
                    },
                    "relationships": [
                        {
                            "field": "location_id",
                            "target_entity": "locations",
                            "target_field": "id",
                            "relation_kind": "belongs_to",
                            "required": False,
                        }
                    ],
                },
                {
                    "key": "locations",
                    "singular_label": "location",
                    "plural_label": "locations",
                    "collection_path": "/locations",
                    "item_path_template": "/locations/{id}",
                    "operations": {
                        "list": {"declared": True, "method": "GET", "path": "/locations"},
                        "get": {"declared": True, "method": "GET", "path": "/locations/{id}"},
                        "create": {"declared": True, "method": "POST", "path": "/locations"},
                        "update": {"declared": True, "method": "PATCH", "path": "/locations/{id}"},
                        "delete": {"declared": True, "method": "DELETE", "path": "/locations/{id}"},
                    },
                    "fields": [
                        {"name": "id", "type": "uuid", "required": True, "readable": True, "writable": False, "identity": True},
                        {"name": "workspace_id", "type": "uuid", "required": True, "readable": True, "writable": True, "identity": False},
                        {"name": "name", "type": "string", "required": True, "readable": True, "writable": True, "identity": True},
                        {"name": "city", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": True},
                        {"name": "country", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": True},
                    ],
                    "presentation": {
                        "default_list_fields": ["name", "kind", "city", "region", "country"],
                        "default_detail_fields": ["id", "name", "kind", "city", "region", "country"],
                        "title_field": "name",
                    },
                    "validation": {
                        "required_on_create": ["workspace_id", "name"],
                        "allowed_on_update": ["name", "kind", "city", "region", "country"],
                    },
                    "relationships": [],
                },
            ],
            "diagnostics": {"latent_commands": latent, "latent_routes": [], "latent_reports": [], "latent_operations": []},
        }
        if include_interfaces:
            resolved["entities"].append(
                {
                    "key": "interfaces",
                    "singular_label": "interface",
                    "plural_label": "interfaces",
                    "collection_path": "/interfaces",
                    "item_path_template": "/interfaces/{id}",
                    "operations": {
                        "list": {"declared": True, "method": "GET", "path": "/interfaces"},
                        "get": {"declared": True, "method": "GET", "path": "/interfaces/{id}"},
                        "create": {"declared": True, "method": "POST", "path": "/interfaces"},
                        "update": {"declared": True, "method": "PATCH", "path": "/interfaces/{id}"},
                        "delete": {"declared": True, "method": "DELETE", "path": "/interfaces/{id}"},
                    },
                    "fields": [
                        {"name": "id", "type": "uuid", "required": True, "readable": True, "writable": False, "identity": True},
                        {"name": "workspace_id", "type": "uuid", "required": True, "readable": True, "writable": True, "identity": False},
                        {
                            "name": "device_id",
                            "type": "uuid",
                            "required": True,
                            "readable": True,
                            "writable": True,
                            "identity": True,
                            "relation": {"target_entity": "devices", "target_field": "id", "relation_kind": "belongs_to"},
                        },
                        {"name": "name", "type": "string", "required": True, "readable": True, "writable": True, "identity": True},
                    ],
                    "presentation": {
                        "default_list_fields": ["name", "device_id", "status"],
                        "default_detail_fields": ["id", "name", "device_id", "status"],
                        "title_field": "name",
                    },
                    "validation": {
                        "required_on_create": ["workspace_id", "device_id", "name"],
                        "allowed_on_update": ["name", "status", "device_id"],
                    },
                    "relationships": [
                        {
                            "field": "device_id",
                            "target_entity": "devices",
                            "target_field": "id",
                            "relation_kind": "belongs_to",
                            "required": True,
                        }
                    ],
                }
            )
        surfaces = {"manage": [{"label": "Workbench", "path": "/app/workbench", "order": 100}]}
        if stale_top_level_interface_surface:
            surfaces["manage"].append({"label": "Interfaces", "path": "/app/interfaces", "order": 150})
            surfaces["docs"] = [{"label": "Interfaces Report", "path": "/app/reports/interfaces-by-status", "order": 151}]
        return {
            "artifact": {"id": "app.net-inventory", "slug": "app.net-inventory", "type": "application", "version": "0.0.1-dev"},
            "capability": {"visibility": "capabilities", "label": "Generated Net Inventory", "order": 120},
            "suggestions": suggestions,
            "surfaces": surfaces,
            "resolved_capability_manifest": resolved,
            "content": {"resolved_capability_manifest": resolved},
        }

    def _bind_generated_artifact(
        self,
        *,
        include_interfaces: bool,
        package_version: str,
        stale_top_level_interfaces: bool = False,
        stale_top_level_interface_surface: bool = False,
        omit_entity_contracts: bool = False,
    ) -> WorkspaceArtifactBinding:
        manifest = self._manifest(
            include_interfaces=include_interfaces,
            stale_top_level_interfaces=stale_top_level_interfaces,
            stale_top_level_interface_surface=stale_top_level_interface_surface,
        )
        if omit_entity_contracts:
            manifest["resolved_capability_manifest"]["entities"] = []
            manifest["content"]["resolved_capability_manifest"]["entities"] = []
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.application_type,
            title="Generated Net Inventory",
            slug="app.net-inventory",
            status="published",
            version=1,
            package_version=package_version,
            visibility="team",
            scope_json={
                "slug": "app.net-inventory",
                "imported_manifest": manifest,
            },
        )
        binding, _ = WorkspaceArtifactBinding.objects.update_or_create(
            workspace=self.workspace,
            artifact=artifact,
            defaults={"enabled": True, "installed_state": "installed"},
        )
        return binding

    def _ensure_runtime(self):
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=None,
            app_slug="net-inventory",
            fqdn="capability-lab.localhost",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://generated-runtime:8080",
                    "app_slug": "net-inventory",
                }
            },
        )

    def test_workspace_artifact_listing_hides_undeclared_suggestions_and_updates_after_evolution(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        response = self.client.get(f"/xyn/api/workspaces/{self.workspace.id}/artifacts")
        self.assertEqual(response.status_code, 200, response.content.decode())
        row = response.json()["artifacts"][0]
        prompts = {entry["prompt"] for entry in row.get("suggestions", [])}
        self.assertNotIn("show interfaces", prompts)

        Artifact.objects.all().delete()
        self._bind_generated_artifact(include_interfaces=True, package_version="0.0.2-dev")
        updated = self.client.get(f"/xyn/api/workspaces/{self.workspace.id}/artifacts")
        self.assertEqual(updated.status_code, 200, updated.content.decode())
        updated_row = updated.json()["artifacts"][0]
        updated_prompts = {entry["prompt"] for entry in updated_row.get("suggestions", [])}
        self.assertIn("show interfaces", updated_prompts)
        entity_keys = {entry["key"] for entry in updated_row.get("manifest_summary", {}).get("entities", [])}
        self.assertIn("interfaces", entity_keys)

    def test_workspace_artifact_listing_includes_entity_crud_contract_summary(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")

        response = self.client.get(f"/xyn/api/workspaces/{self.workspace.id}/artifacts")

        self.assertEqual(response.status_code, 200, response.content.decode())
        row = response.json()["artifacts"][0]
        entities = {entry["key"]: entry for entry in row.get("manifest_summary", {}).get("entities", [])}
        self.assertEqual(set(entities), {"devices", "locations"})
        devices = entities["devices"]
        self.assertEqual(devices["collection_path"], "/devices")
        self.assertEqual(devices["item_path_template"], "/devices/{id}")
        self.assertTrue(devices["operations"]["list"]["declared"])
        self.assertTrue(devices["operations"]["create"]["declared"])
        self.assertTrue(devices["operations"]["update"]["declared"])
        device_fields = {field["name"]: field for field in devices["fields"]}
        self.assertTrue(device_fields["name"]["required"])
        self.assertEqual(device_fields["location_id"]["relation"]["target_entity"], "locations")
        self.assertIn("name", devices["presentation"]["default_list_fields"])

    def test_palette_execute_accepts_workspace_slug_for_generated_runtime(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        with mock.patch(
            "xyn_orchestrator.xyn_api.requests.request",
            return_value=_FakeResponse(body={"items": [{"id": "dev-1", "name": "router-1", "kind": "router", "status": "online", "location_id": "loc-1"}]}),
        ) as runtime_request:
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_slug={self.workspace.slug}",
                data=json.dumps({"prompt": "show devices"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("kind"), "table")
        self.assertEqual(payload.get("meta", {}).get("base_url"), "http://generated-runtime:8080")
        self.assertEqual(runtime_request.call_count, 1)
        self.assertEqual(runtime_request.call_args.kwargs.get("url"), "http://generated-runtime:8080/devices")

    def test_workspace_artifact_listing_ignores_stale_top_level_generated_suggestions(self):
        self._bind_generated_artifact(
            include_interfaces=False,
            package_version="0.0.1-dev",
            stale_top_level_interfaces=True,
        )

        response = self.client.get(f"/xyn/api/workspaces/{self.workspace.id}/artifacts")

        self.assertEqual(response.status_code, 200, response.content.decode())
        row = response.json()["artifacts"][0]
        prompts = {entry["prompt"] for entry in row.get("suggestions", [])}
        self.assertNotIn("show interfaces", prompts)
        self.assertEqual(
            prompts,
            {
                "show devices",
                "show locations",
                "create device",
                "update device",
                "delete device",
                "create location",
                "update location",
                "delete location",
                "show devices by status",
            },
        )

    def test_workspace_artifact_listing_ignores_stale_top_level_generated_surfaces(self):
        self._bind_generated_artifact(
            include_interfaces=False,
            package_version="0.0.1-dev",
            stale_top_level_interface_surface=True,
        )

        response = self.client.get(f"/xyn/api/workspaces/{self.workspace.id}/artifacts")

        self.assertEqual(response.status_code, 200, response.content.decode())
        row = response.json()["artifacts"][0]
        surfaces = row.get("manifest_summary", {}).get("surfaces", {})
        manage_labels = {entry["label"] for entry in surfaces.get("manage", [])}
        docs_labels = {entry["label"] for entry in surfaces.get("docs", [])}
        self.assertEqual(manage_labels, {"Workbench"})
        self.assertEqual(docs_labels, {"Workbench"})

    def test_workspace_artifact_listing_flags_stale_generated_manifest_without_entities(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev", omit_entity_contracts=True)

        response = self.client.get(f"/xyn/api/workspaces/{self.workspace.id}/artifacts")

        self.assertEqual(response.status_code, 200, response.content.decode())
        row = response.json()["artifacts"][0]
        self.assertEqual(row.get("suggestions"), [])
        manifest_summary = row.get("manifest_summary", {})
        self.assertEqual(manifest_summary.get("entities"), [])
        self.assertEqual(
            manifest_summary.get("generated_artifact_contract_status", {}).get("reason"),
            "missing_entity_contracts",
        )

    def test_undeclared_command_is_blocked_before_runtime_request(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        with mock.patch("xyn_orchestrator.xyn_api.requests.request") as runtime_request:
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "show interfaces"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("text"), "No matching palette command found.")
        diagnostics = payload.get("meta", {}).get("capability_diagnostics", {})
        self.assertIn("show interfaces", diagnostics.get("latent_command_keys", []))
        runtime_request.assert_not_called()

    def test_declared_command_routes_via_installed_capability_manifest(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        with mock.patch(
            "xyn_orchestrator.xyn_api.requests.request",
            return_value=_FakeResponse(body=[{"id": "dev-1", "name": "edge-1", "kind": "router", "status": "online", "location_id": ""}]),
        ) as runtime_request, mock.patch("xyn_orchestrator.xyn_api._seed_context_pack_meta", return_value={}):
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "show devices"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("kind"), "table")
        self.assertEqual(len(payload.get("rows") or []), 1)
        runtime_request.assert_called_once()
        self.assertIn("/devices", runtime_request.call_args.kwargs.get("url", ""))

    def test_palette_executes_create_update_delete_aliases_via_entity_contract(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        responses = [
            _FakeResponse(status_code=201, body={"id": "dev-1", "name": "router-01", "kind": "router", "status": "online", "location_id": ""}),
            _FakeResponse(status_code=200, body={"id": "dev-1", "name": "router-01", "kind": "router", "status": "offline", "location_id": ""}),
            _FakeResponse(status_code=200, body={"deleted": True, "item": {"id": "dev-1", "name": "router-01", "kind": "router", "status": "offline", "location_id": ""}}),
        ]

        with mock.patch("xyn_orchestrator.xyn_api.requests.request", side_effect=responses) as runtime_request, mock.patch(
            "xyn_orchestrator.xyn_api._seed_context_pack_meta", return_value={}
        ):
            created = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "create device named router-01"}),
                content_type="application/json",
            )
            updated = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "update device router-01 status offline"}),
                content_type="application/json",
            )
            deleted = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "delete device router-01"}),
                content_type="application/json",
            )

        self.assertEqual(created.status_code, 200, created.content.decode())
        self.assertIn("Created 1 device", created.json().get("text", ""))
        self.assertEqual(updated.status_code, 200, updated.content.decode())
        self.assertIn("Updated 1 device", updated.json().get("text", ""))
        self.assertEqual(deleted.status_code, 200, deleted.content.decode())
        self.assertIn("Deleted 1 device", deleted.json().get("text", ""))
        self.assertEqual(runtime_request.call_count, 3)
        self.assertEqual(runtime_request.call_args_list[0].kwargs.get("method"), "POST")
        self.assertIn("/devices", runtime_request.call_args_list[0].kwargs.get("url", ""))
        self.assertEqual(runtime_request.call_args_list[1].kwargs.get("method"), "PATCH")
        self.assertIn("/devices/router-01", runtime_request.call_args_list[1].kwargs.get("url", ""))
        self.assertEqual(runtime_request.call_args_list[1].kwargs.get("json"), {"status": "offline"})
        self.assertEqual(runtime_request.call_args_list[2].kwargs.get("method"), "DELETE")
        self.assertIn("/devices/router-01", runtime_request.call_args_list[2].kwargs.get("url", ""))

    def test_palette_executes_rename_alias_via_update_operation(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        with mock.patch(
            "xyn_orchestrator.xyn_api.requests.request",
            return_value=_FakeResponse(status_code=200, body={"id": "dev-1", "name": "router-core", "kind": "router", "status": "online", "location_id": ""}),
        ) as runtime_request, mock.patch("xyn_orchestrator.xyn_api._seed_context_pack_meta", return_value={}):
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "rename device router-01 to router-core"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertIn("Updated 1 device: router-core", response.json().get("text", ""))
        runtime_request.assert_called_once()
        self.assertEqual(runtime_request.call_args.kwargs.get("method"), "PATCH")
        self.assertEqual(runtime_request.call_args.kwargs.get("json"), {"name": "router-core"})

    def test_palette_returns_structured_fallback_for_missing_crud_fields(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        with mock.patch("xyn_orchestrator.xyn_api.requests.request") as runtime_request, mock.patch(
            "xyn_orchestrator.xyn_api._seed_context_pack_meta", return_value={}
        ):
            create_response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "create device"}),
                content_type="application/json",
            )
            update_response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "update device"}),
                content_type="application/json",
            )

        self.assertEqual(create_response.status_code, 200, create_response.content.decode())
        self.assertIn("To create device, provide:", create_response.json().get("text", ""))
        self.assertIn("- name", create_response.json().get("text", ""))
        self.assertEqual(update_response.status_code, 200, update_response.content.decode())
        self.assertIn("To update device, provide:", update_response.json().get("text", ""))
        self.assertIn("- record reference", update_response.json().get("text", ""))
        runtime_request.assert_not_called()

    def test_palette_does_not_expose_alias_when_operation_not_declared(self):
        binding = self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        manifest = binding.artifact.scope_json["imported_manifest"]
        for entity in manifest["resolved_capability_manifest"]["entities"]:
            if entity["key"] == "devices":
                entity["operations"]["delete"]["declared"] = False
        binding.artifact.scope_json["imported_manifest"] = manifest
        binding.artifact.save(update_fields=["scope_json", "updated_at"])
        self._ensure_runtime()

        with mock.patch("xyn_orchestrator.xyn_api.requests.request") as runtime_request:
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "delete device router-01"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json().get("text"), "No matching palette command found.")
        runtime_request.assert_not_called()

    def test_stale_generated_artifact_is_blocked_before_palette_runtime_fallback(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev", omit_entity_contracts=True)
        self._ensure_runtime()

        with mock.patch("xyn_orchestrator.xyn_api.requests.request") as runtime_request:
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "delete device router-01"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertIn("Generated app contract is unavailable", payload.get("text", ""))
        self.assertEqual(
            payload.get("meta", {}).get("generated_artifact_contract_status", {}).get("reason"),
            "missing_entity_contracts",
        )
        runtime_request.assert_not_called()

    def test_palette_natural_language_create_resolves_relation_and_logs_trace(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        def runtime_side_effect(*args, **kwargs):
            method = kwargs.get("method")
            url = kwargs.get("url", "")
            if method == "GET" and url.endswith("/locations"):
                return _FakeResponse(body={"items": [{"id": "loc-1", "name": "St. Louis", "city": "St. Louis"}]})
            if method == "POST" and url.endswith("/devices"):
                return _FakeResponse(status_code=201, body={"id": "dev-1", "name": "router-1", "status": "online", "location_id": "loc-1"})
            if method == "GET" and url.endswith("/devices"):
                return _FakeResponse(body={"items": [{"id": "dev-1", "name": "router-1", "status": "online", "location_id": "loc-1"}]})
            raise AssertionError(f"Unexpected runtime request: {method} {url}")

        with mock.patch("xyn_orchestrator.xyn_api.requests.request", side_effect=runtime_side_effect) as runtime_request, mock.patch(
            "xyn_orchestrator.xyn_api._seed_context_pack_meta", return_value={}
        ):
            created = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "I want to create a device named router-1 in St. Louis"}),
                content_type="application/json",
            )
            shown = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "show devices"}),
                content_type="application/json",
            )

        self.assertEqual(created.status_code, 200, created.content.decode())
        self.assertIn("Created 1 device: router-1", created.json().get("text", ""))
        self.assertEqual(shown.status_code, 200, shown.content.decode())
        self.assertIn("Found 1 devices.", shown.json().get("text", ""))
        self.assertEqual(runtime_request.call_args_list[1].kwargs.get("json", {}).get("location_id"), "loc-1")

        activity = self.client.get(f"/xyn/api/ai/activity?workspace_id={self.workspace.id}")
        self.assertEqual(activity.status_code, 200, activity.content.decode())
        palette_items = [item for item in activity.json().get("items", []) if item.get("request_type") == "palette.execute"]
        traced = next(item for item in palette_items if item.get("prompt") == "I want to create a device named router-1 in St. Louis")
        self.assertEqual(traced.get("structured_operation", {}).get("entity_key"), "devices")
        steps = [step.get("step") for step in traced.get("trace", [])]
        self.assertIn("parsed_intent", steps)
        self.assertIn("entity_contract_consulted", steps)
        self.assertIn("relationship_resolution", steps)
        self.assertIn("runtime_execution", steps)

    def test_palette_relation_resolution_prefers_title_field_over_secondary_identity_fields(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        def runtime_side_effect(*args, **kwargs):
            method = kwargs.get("method")
            url = kwargs.get("url", "")
            if method == "GET" and url.endswith("/locations"):
                return _FakeResponse(
                    body={
                        "items": [
                            {"id": "loc-1", "name": "St. Louis", "city": None},
                            {"id": "loc-2", "name": "St. Louis Device", "city": "St. Louis"},
                        ]
                    }
                )
            if method == "POST" and url.endswith("/devices"):
                return _FakeResponse(status_code=201, body={"id": "dev-1", "name": "router-1", "status": "online", "location_id": "loc-1"})
            raise AssertionError(f"Unexpected runtime request: {method} {url}")

        with mock.patch("xyn_orchestrator.xyn_api.requests.request", side_effect=runtime_side_effect) as runtime_request, mock.patch(
            "xyn_orchestrator.xyn_api._seed_context_pack_meta", return_value={}
        ):
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "create device named router-1 in St. Louis"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertIn("Created 1 device: router-1", response.json().get("text", ""))
        self.assertEqual(runtime_request.call_args_list[1].kwargs.get("json", {}).get("location_id"), "loc-1")

    @mock.patch("xyn_orchestrator.xyn_api._intent_engine_enabled", return_value=True)
    def test_intent_resolve_rejects_stale_generated_artifact_contract(self, _intent_enabled):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev", omit_entity_contracts=True)
        self._ensure_runtime()

        response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps(
                {
                    "message": "Add a device called router-2 at St. Louis",
                    "context": {"workspace_id": str(self.workspace.id)},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("status"), "ValidationError")
        self.assertIn("contract is unavailable", payload.get("summary", "").lower())

    @mock.patch("xyn_orchestrator.xyn_api._intent_engine_enabled", return_value=True)
    def test_delete_restriction_does_not_rebind_to_other_entity(self, _intent_enabled):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()
        binding = WorkspaceArtifactBinding.objects.select_related("artifact").get(workspace=self.workspace, artifact__slug="app.net-inventory")
        scope = dict(binding.artifact.scope_json or {})
        manifest = dict((scope.get("imported_manifest") if isinstance(scope.get("imported_manifest"), dict) else {}) or {})

        def mutate(resolved: dict) -> dict:
            payload = dict((resolved if isinstance(resolved, dict) else {}) or {})
            payload["commands"] = [row for row in (payload.get("commands") or []) if str((row or {}).get("key") or "") != "delete device"]
            entities = []
            for row in payload.get("entities") or []:
                entity = dict(row or {})
                if str(entity.get("key") or "") == "devices":
                    operations = dict((entity.get("operations") if isinstance(entity.get("operations"), dict) else {}) or {})
                    delete_spec = dict((operations.get("delete") if isinstance(operations.get("delete"), dict) else {}) or {})
                    delete_spec["declared"] = False
                    operations["delete"] = delete_spec
                    entity["operations"] = operations
                entities.append(entity)
            payload["entities"] = entities
            return payload

        manifest["resolved_capability_manifest"] = mutate(manifest.get("resolved_capability_manifest"))
        content = dict((manifest.get("content") if isinstance(manifest.get("content"), dict) else {}) or {})
        content["resolved_capability_manifest"] = mutate(content.get("resolved_capability_manifest"))
        manifest["content"] = content
        scope["imported_manifest"] = manifest
        artifact = binding.artifact
        artifact.scope_json = scope
        artifact.save(update_fields=["scope_json", "updated_at"])

        palette = self.client.post(
            f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
            data=json.dumps({"prompt": "delete device router-01"}),
            content_type="application/json",
        )
        self.assertEqual(palette.status_code, 200, palette.content.decode())
        self.assertIn("No matching palette command found.", palette.json().get("text", ""))

        resolved = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": "Remove router-01", "context": {"workspace_id": str(self.workspace.id)}}),
            content_type="application/json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.content.decode())
        self.assertEqual(resolved.json().get("status"), "UnsupportedIntent")

    @mock.patch("xyn_orchestrator.xyn_api._intent_engine_enabled", return_value=True)
    def test_intent_generated_crud_natural_language_flow_and_observability(self, _intent_enabled):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        resolve_response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps(
                {
                    "message": "I need to add a device called router-2 at St. Louis",
                    "context": {"workspace_id": str(self.workspace.id)},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(resolve_response.status_code, 200, resolve_response.content.decode())
        resolve_payload = resolve_response.json()
        self.assertEqual(resolve_payload.get("draft_payload", {}).get("__operation"), "execute_generated_app_crud")
        self.assertEqual(resolve_payload.get("draft_payload", {}).get("structured_operation", {}).get("operation"), "create")
        self.assertEqual(resolve_payload.get("draft_payload", {}).get("structured_operation", {}).get("entity_key"), "devices")

        def runtime_side_effect(*args, **kwargs):
            method = kwargs.get("method")
            url = kwargs.get("url", "")
            if method == "GET" and url.endswith("/locations"):
                return _FakeResponse(body={"items": [{"id": "loc-1", "name": "St. Louis", "city": "St. Louis"}]})
            if method == "POST" and url.endswith("/devices"):
                return _FakeResponse(status_code=201, body={"id": "dev-2", "name": "router-2", "status": "online", "location_id": "loc-1"})
            raise AssertionError(f"Unexpected runtime request: {method} {url}")

        with mock.patch("xyn_orchestrator.xyn_api.requests.request", side_effect=runtime_side_effect):
            apply_response = self.client.post(
                "/xyn/api/xyn/intent/apply",
                data=json.dumps(
                    {
                        "action_type": "CreateDraft",
                        "artifact_type": "Workspace",
                        "payload": resolve_payload.get("draft_payload", {}),
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(apply_response.status_code, 200, apply_response.content.decode())
        apply_payload = apply_response.json()
        self.assertIn("Created 1 device: router-2", apply_payload.get("summary", ""))
        self.assertTrue(apply_payload.get("operation_result"))
        self.assertEqual(apply_payload.get("artifact_id"), None)
        self.assertEqual(apply_payload.get("structured_operation", {}).get("entity_key"), "devices")
        self.assertEqual(apply_payload.get("result", {}).get("rows", [{}])[0].get("location_id"), "loc-1")

        activity = self.client.get(f"/xyn/api/ai/activity?workspace_id={self.workspace.id}")
        self.assertEqual(activity.status_code, 200, activity.content.decode())
        apply_item = next(
            item
            for item in activity.json().get("items", [])
            if item.get("request_type") == "intent.apply" and item.get("prompt") == "I need to add a device called router-2 at St. Louis"
        )
        self.assertEqual(apply_item.get("structured_operation", {}).get("entity_key"), "devices")
        self.assertIn("runtime_execution", [step.get("step") for step in apply_item.get("trace", [])])

    def test_palette_disambiguates_partial_delete_reference(self):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        with mock.patch(
            "xyn_orchestrator.xyn_api.requests.request",
            return_value=_FakeResponse(body={"items": [{"id": "dev-1", "name": "router-01"}, {"id": "dev-2", "name": "router-02"}]}),
        ) as runtime_request, mock.patch("xyn_orchestrator.xyn_api._seed_context_pack_meta", return_value={}):
            response = self.client.post(
                f"/xyn/api/palette/execute?workspace_id={self.workspace.id}",
                data=json.dumps({"prompt": "delete device router"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertIn("Multiple matches found for device", response.json().get("text", ""))
        self.assertEqual(runtime_request.call_count, 1)
        self.assertEqual(runtime_request.call_args.kwargs.get("method"), "GET")

    @mock.patch("xyn_orchestrator.xyn_api._intent_engine_enabled", return_value=True)
    def test_intent_generated_crud_supports_bare_change_rename_and_remove(self, _intent_enabled):
        self._bind_generated_artifact(include_interfaces=False, package_version="0.0.1-dev")
        self._ensure_runtime()

        state = {"name": "router-2", "status": "online"}

        def runtime_side_effect(*args, **kwargs):
            method = kwargs.get("method")
            url = kwargs.get("url", "")
            if method == "GET" and url.endswith("/devices"):
                return _FakeResponse(body={"items": [{"id": "dev-2", "name": state["name"], "status": state["status"]}]})
            if method == "PATCH" and url.endswith("/devices/dev-2"):
                body = kwargs.get("json") or {}
                state["name"] = body.get("name", state["name"])
                state["status"] = body.get("status", state["status"])
                return _FakeResponse(status_code=200, body={"id": "dev-2", "name": state["name"], "status": state["status"]})
            if method == "DELETE" and url.endswith("/devices/dev-2"):
                return _FakeResponse(status_code=200, body={"deleted": True, "item": {"id": "dev-2", "name": state["name"], "status": state["status"]}})
            raise AssertionError(f"Unexpected runtime request: {method} {url}")

        prompts = [
            "Change router-2 to offline",
            "Rename router-2 to router-edge",
            "Remove router-edge",
        ]
        expected = ["Updated 1 device: router-2", "Updated 1 device: router-edge", "Deleted 1 device: router-edge"]

        with mock.patch("xyn_orchestrator.xyn_api.requests.request", side_effect=runtime_side_effect):
            for prompt, summary in zip(prompts, expected):
                resolved = self.client.post(
                    "/xyn/api/xyn/intent/resolve",
                    data=json.dumps({"message": prompt, "context": {"workspace_id": str(self.workspace.id)}}),
                    content_type="application/json",
                )
                self.assertEqual(resolved.status_code, 200, resolved.content.decode())
                applied = self.client.post(
                    "/xyn/api/xyn/intent/apply",
                    data=json.dumps(
                        {
                            "action_type": "CreateDraft",
                            "artifact_type": "Workspace",
                            "payload": resolved.json().get("draft_payload", {}),
                        }
                    ),
                    content_type="application/json",
                )
                self.assertEqual(applied.status_code, 200, applied.content.decode())
                self.assertIn(summary, applied.json().get("summary", ""))
