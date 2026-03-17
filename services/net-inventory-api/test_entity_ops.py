from __future__ import annotations

import copy
import json
import os
import unittest
import uuid
from unittest import mock

from fastapi.testclient import TestClient

from entity_ops import DEFAULT_ENTITY_CONTRACTS, GenericEntityOperationsService, compile_policy_bundle, load_entity_contracts, load_policy_bundle
from main import create_app


class InMemoryStorageAdapter:
    def __init__(self):
        self.rows: dict[str, dict[str, dict[str, object]]] = {}

    def _bucket(self, contract):
        return self.rows.setdefault(str(contract.get("key")), {})

    def list(self, contract, *, workspace_id: str):
        bucket = self._bucket(contract)
        return [copy.deepcopy(row) for row in bucket.values() if str(row.get("workspace_id") or "") == workspace_id]

    def get_by_id(self, contract, *, record_id: str, workspace_id: str | None):
        row = copy.deepcopy(self._bucket(contract).get(record_id))
        if not row:
            return None
        if workspace_id and str(row.get("workspace_id") or "") != workspace_id:
            return None
        return row

    def find_by_identity(self, contract, *, field_name: str, field_value, workspace_id: str):
        for row in self._bucket(contract).values():
            if str(row.get("workspace_id") or "") != workspace_id:
                continue
            if row.get(field_name) == field_value:
                return copy.deepcopy(row)
        return None

    def insert(self, contract, *, values):
        record = copy.deepcopy(values)
        record["id"] = str(uuid.uuid4())
        record.setdefault("created_at", "2026-03-10T00:00:00Z")
        record.setdefault("updated_at", "2026-03-10T00:00:00Z")
        self._bucket(contract)[str(record["id"])] = copy.deepcopy(record)
        return copy.deepcopy(record)

    def update(self, contract, *, record_id: str, workspace_id: str | None, values):
        existing = self.get_by_id(contract, record_id=record_id, workspace_id=workspace_id)
        if not existing:
            raise AssertionError("record missing in test adapter")
        existing.update(copy.deepcopy(values))
        existing["updated_at"] = "2026-03-10T00:00:01Z"
        self._bucket(contract)[record_id] = copy.deepcopy(existing)
        return existing

    def delete(self, contract, *, record_id: str, workspace_id: str | None):
        existing = self.get_by_id(contract, record_id=record_id, workspace_id=workspace_id)
        if not existing:
            raise AssertionError("record missing in test adapter")
        del self._bucket(contract)[record_id]
        return existing


def _contracts(*, allow_device_delete: bool = True):
    rows = copy.deepcopy(DEFAULT_ENTITY_CONTRACTS)
    if not allow_device_delete:
        for row in rows:
            if row.get("key") == "devices":
                row["operations"]["delete"]["declared"] = False
    return rows


def _lunch_poll_contracts():
    return [
        {
            "key": "polls",
            "singular_label": "poll",
            "plural_label": "polls",
            "collection_path": "/polls",
            "item_path_template": "/polls/{id}",
            "operations": {
                "list": {"declared": True, "method": "GET", "path": "/polls"},
                "get": {"declared": True, "method": "GET", "path": "/polls/{id}"},
                "create": {"declared": True, "method": "POST", "path": "/polls"},
                "update": {"declared": True, "method": "PATCH", "path": "/polls/{id}"},
                "delete": {"declared": True, "method": "DELETE", "path": "/polls/{id}"},
            },
            "fields": [
                {"name": "id", "type": "uuid", "required": True, "readable": True, "writable": False, "identity": True},
                {"name": "workspace_id", "type": "uuid", "required": True, "readable": True, "writable": True, "identity": False},
                {"name": "title", "type": "string", "required": True, "readable": True, "writable": True, "identity": True},
                {"name": "poll_date", "type": "string", "required": True, "readable": True, "writable": True, "identity": False},
                {"name": "status", "type": "string", "required": True, "readable": True, "writable": True, "identity": False, "options": ["draft", "open", "closed", "selected"]},
                {"name": "created_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
                {"name": "updated_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
            ],
            "presentation": {"default_list_fields": ["title", "poll_date", "status"], "default_detail_fields": ["id", "title", "poll_date", "status"], "title_field": "title"},
            "validation": {"required_on_create": ["workspace_id", "title", "poll_date", "status"], "allowed_on_update": ["title", "poll_date", "status"]},
            "relationships": [],
        },
        {
            "key": "lunch_options",
            "singular_label": "lunch option",
            "plural_label": "lunch options",
            "collection_path": "/lunch_options",
            "item_path_template": "/lunch_options/{id}",
            "operations": {
                "list": {"declared": True, "method": "GET", "path": "/lunch_options"},
                "get": {"declared": True, "method": "GET", "path": "/lunch_options/{id}"},
                "create": {"declared": True, "method": "POST", "path": "/lunch_options"},
                "update": {"declared": True, "method": "PATCH", "path": "/lunch_options/{id}"},
                "delete": {"declared": True, "method": "DELETE", "path": "/lunch_options/{id}"},
            },
            "fields": [
                {"name": "id", "type": "uuid", "required": True, "readable": True, "writable": False, "identity": True},
                {"name": "workspace_id", "type": "uuid", "required": True, "readable": True, "writable": True, "identity": False},
                {
                    "name": "poll_id",
                    "type": "uuid",
                    "required": True,
                    "readable": True,
                    "writable": True,
                    "identity": False,
                    "relation": {"target_entity": "polls", "target_field": "id", "relation_kind": "belongs_to"},
                },
                {"name": "name", "type": "string", "required": True, "readable": True, "writable": True, "identity": True},
                {"name": "restaurant", "type": "string", "required": True, "readable": True, "writable": True, "identity": False},
                {"name": "notes", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": False},
                {"name": "active", "type": "string", "required": True, "readable": True, "writable": True, "identity": False, "options": ["yes", "no"]},
                {"name": "selected", "type": "string", "required": False, "readable": True, "writable": True, "identity": False, "options": ["yes", "no"]},
                {"name": "created_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
                {"name": "updated_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
            ],
            "presentation": {"default_list_fields": ["name", "restaurant", "active", "selected"], "default_detail_fields": ["id", "poll_id", "name", "restaurant", "active", "selected"], "title_field": "name"},
            "validation": {"required_on_create": ["workspace_id", "poll_id", "name", "restaurant", "active"], "allowed_on_update": ["poll_id", "name", "restaurant", "notes", "active", "selected"]},
            "relationships": [{"field": "poll_id", "target_entity": "polls", "target_field": "id", "relation_kind": "belongs_to", "required": True}],
        },
        {
            "key": "votes",
            "singular_label": "vote",
            "plural_label": "votes",
            "collection_path": "/votes",
            "item_path_template": "/votes/{id}",
            "operations": {
                "list": {"declared": True, "method": "GET", "path": "/votes"},
                "get": {"declared": True, "method": "GET", "path": "/votes/{id}"},
                "create": {"declared": True, "method": "POST", "path": "/votes"},
                "update": {"declared": True, "method": "PATCH", "path": "/votes/{id}"},
                "delete": {"declared": True, "method": "DELETE", "path": "/votes/{id}"},
            },
            "fields": [
                {"name": "id", "type": "uuid", "required": True, "readable": True, "writable": False, "identity": True},
                {"name": "workspace_id", "type": "uuid", "required": True, "readable": True, "writable": True, "identity": False},
                {
                    "name": "poll_id",
                    "type": "uuid",
                    "required": True,
                    "readable": True,
                    "writable": True,
                    "identity": False,
                    "relation": {"target_entity": "polls", "target_field": "id", "relation_kind": "belongs_to"},
                },
                {
                    "name": "lunch_option_id",
                    "type": "uuid",
                    "required": True,
                    "readable": True,
                    "writable": True,
                    "identity": False,
                    "relation": {"target_entity": "lunch_options", "target_field": "id", "relation_kind": "belongs_to"},
                },
                {"name": "voter_name", "type": "string", "required": True, "readable": True, "writable": True, "identity": True},
                {"name": "created_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
                {"name": "updated_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
            ],
            "presentation": {"default_list_fields": ["poll_id", "lunch_option_id", "voter_name"], "default_detail_fields": ["id", "poll_id", "lunch_option_id", "voter_name"], "title_field": "voter_name"},
            "validation": {"required_on_create": ["workspace_id", "poll_id", "lunch_option_id", "voter_name"], "allowed_on_update": ["poll_id", "lunch_option_id", "voter_name"]},
            "relationships": [
                {"field": "poll_id", "target_entity": "polls", "target_field": "id", "relation_kind": "belongs_to", "required": True},
                {"field": "lunch_option_id", "target_entity": "lunch_options", "target_field": "id", "relation_kind": "belongs_to", "required": True},
            ],
        },
    ]


def _lunch_poll_policy_bundle():
    return {
        "schema_version": "xyn.policy_bundle.v0",
        "bundle_id": "policy.team-lunch-poll",
        "app_slug": "team-lunch-poll",
        "workspace_id": str(uuid.uuid4()),
        "title": "Team Lunch Poll Policy Bundle",
        "scope": {"artifact_slug": "app.team-lunch-poll", "applies_to": ["generated_runtime"]},
        "ownership": {"owner_kind": "generated_application", "editable": True, "source": "generated_from_prompt"},
        "policy_families": ["validation_policies", "relation_constraints", "transition_policies", "invariant_policies", "derived_policies", "trigger_policies"],
        "policies": {
            "validation_policies": [
                {
                    "id": "team-lunch-poll-201",
                    "description": "Prevent voting on polls that are not open.",
                    "explanation": {"user_summary": "Votes are allowed only when the parent poll is open."},
                    "parameters": {
                        "runtime_rule": "parent_status_gate",
                        "entity_key": "votes",
                        "parent_entity": "polls",
                        "parent_relation_field": "poll_id",
                        "parent_status_field": "status",
                        "allowed_parent_statuses": ["open"],
                        "on_operations": ["create", "update"],
                    },
                }
            ],
            "relation_constraints": [
                {
                    "id": "team-lunch-poll-202",
                    "description": "Vote lunch option must belong to the same poll.",
                    "explanation": {"user_summary": "A vote must reference a lunch option from the same poll."},
                    "parameters": {
                        "runtime_rule": "match_related_field",
                        "entity_key": "votes",
                        "source_field": "lunch_option_id",
                        "related_entity": "lunch_options",
                        "related_lookup_field": "id",
                        "related_match_field": "poll_id",
                        "comparison_field": "poll_id",
                    },
                }
            ],
            "transition_policies": [
                {
                    "id": "team-lunch-poll-203",
                    "description": "Poll status moves through ordered workflow states.",
                    "explanation": {"user_summary": "Poll status changes follow the declared workflow order."},
                    "parameters": {
                        "runtime_rule": "field_transition_guard",
                        "entity_key": "polls",
                        "field_name": "status",
                        "allowed_transitions": {
                            "draft": ["draft", "open"],
                            "open": ["open", "closed"],
                            "closed": ["closed", "selected"],
                            "selected": ["selected"],
                        },
                    },
                }
            ],
            "invariant_policies": [
                {
                    "id": "team-lunch-poll-206",
                    "description": "At most one selected lunch option per poll.",
                    "explanation": {"user_summary": "Only one lunch option can be selected for each poll."},
                    "parameters": {
                        "runtime_rule": "at_most_one_matching_child_per_parent",
                        "entity_key": "lunch_options",
                        "parent_entity": "polls",
                        "parent_relation_field": "poll_id",
                        "match_field": "selected",
                        "match_value": "yes",
                        "on_operations": ["create", "update"],
                    },
                },
                {
                    "id": "team-lunch-poll-207",
                    "description": "A poll in selected status must have exactly one selected lunch option.",
                    "explanation": {"user_summary": "A poll in selected status must have exactly one selected Lunch Option."},
                    "parameters": {
                        "runtime_rule": "at_least_one_matching_child_per_parent",
                        "entity_key": "lunch_options",
                        "parent_entity": "polls",
                        "parent_relation_field": "poll_id",
                        "match_field": "selected",
                        "match_value": "yes",
                        "parent_state_field": "status",
                        "parent_state_value": "selected",
                        "on_parent_operations": ["create", "update"],
                        "on_child_operations": ["create", "update", "delete"],
                    },
                },
                {"id": "unsupported-invariant", "parameters": {"runtime_rule": "conditional_exactly_one"}},
            ],
            "derived_policies": [
                {
                    "id": "team-lunch-poll-204",
                    "description": "Expose vote counts per lunch option.",
                    "explanation": {"user_summary": "Vote counts are available on each lunch option."},
                    "parameters": {
                        "runtime_rule": "related_count",
                        "entity_key": "lunch_options",
                        "child_entity": "votes",
                        "child_relation_field": "lunch_option_id",
                        "output_field": "votes_count",
                        "surfaces": ["list", "detail"],
                    },
                },
                {"id": "unsupported-derived", "parameters": {"runtime_rule": "count_rollup"}},
            ],
            "trigger_policies": [
                {
                    "id": "team-lunch-poll-205",
                    "description": "Selecting an option updates the parent poll status.",
                    "explanation": {"user_summary": "When an option is selected, the related poll becomes selected."},
                    "parameters": {
                        "runtime_rule": "post_write_related_update",
                        "source_entity": "lunch_options",
                        "on_operations": ["create", "update"],
                        "condition_field": "selected",
                        "condition_equals": "yes",
                        "target_entity": "polls",
                        "target_relation_field": "poll_id",
                        "target_lookup_field": "id",
                        "target_update_field": "status",
                        "target_update_value": "selected",
                    },
                },
                {"id": "unsupported-trigger", "parameters": {"runtime_rule": "multi_step_chain"}},
            ],
        },
        "configurable_parameters": [],
        "explanation": {"summary": "test", "coverage": {}, "future_capabilities": []},
    }


def _lunch_poll_policy_bundle_without_triggers():
    bundle = copy.deepcopy(_lunch_poll_policy_bundle())
    policies = bundle.get("policies") if isinstance(bundle.get("policies"), dict) else {}
    policies["trigger_policies"] = []
    return bundle


class NetInventoryCrudTests(unittest.TestCase):
    def setUp(self):
        self.workspace_id = str(uuid.uuid4())
        self.storage = InMemoryStorageAdapter()
        self.service = GenericEntityOperationsService(entity_contracts=_contracts(), storage_adapter=self.storage)
        self.client = TestClient(create_app(entity_service=self.service, initialize_schema=False))

    def test_create_and_list_locations(self):
        create_response = self.client.post(
            "/locations",
            json={"workspace_id": self.workspace_id, "name": "St. Louis", "kind": "site", "city": "St. Louis", "region": "MO", "country": "USA"},
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        created = create_response.json()
        self.assertEqual(created["name"], "St. Louis")

        list_response = self.client.get("/locations", params={"workspace_id": self.workspace_id})
        self.assertEqual(list_response.status_code, 200, list_response.text)
        rows = list_response.json()["items"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["city"], "St. Louis")

    def test_create_get_update_delete_device(self):
        created = self.client.post(
            "/devices",
            json={"workspace_id": self.workspace_id, "name": "test-1", "kind": "router", "status": "online"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        device = created.json()

        fetched = self.client.get(f"/devices/{device['id']}", params={"workspace_id": self.workspace_id})
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["name"], "test-1")

        updated = self.client.patch(
            f"/devices/{device['id']}",
            params={"workspace_id": self.workspace_id},
            json={"status": "offline"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "offline")

        deleted = self.client.delete(f"/devices/{device['id']}", params={"workspace_id": self.workspace_id})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["deleted"])

        missing = self.client.get(f"/devices/{device['id']}", params={"workspace_id": self.workspace_id})
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_device_create_resolves_location_relation_by_identity(self):
        location = self.client.post(
            "/locations",
            json={"workspace_id": self.workspace_id, "name": "Austin", "kind": "site", "city": "Austin", "region": "TX", "country": "USA"},
        ).json()

        device = self.client.post(
            "/devices",
            json={"workspace_id": self.workspace_id, "name": "edge-1", "kind": "router", "status": "online", "location_id": "Austin"},
        )

        self.assertEqual(device.status_code, 201, device.text)
        self.assertEqual(device.json()["location_id"], location["id"])

    def test_get_record_supports_exact_identity_lookup(self):
        created = self.client.post(
            "/devices",
            json={"workspace_id": self.workspace_id, "name": "lookup-device", "kind": "router", "status": "online"},
        ).json()

        fetched = self.client.get("/devices/lookup-device", params={"workspace_id": self.workspace_id})

        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["id"], created["id"])

    def test_operations_rejected_when_not_declared_in_contract(self):
        service = GenericEntityOperationsService(entity_contracts=_contracts(allow_device_delete=False), storage_adapter=InMemoryStorageAdapter())
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        created = client.post(
            "/devices",
            json={"workspace_id": self.workspace_id, "name": "blocked-delete", "kind": "router", "status": "online"},
        ).json()

        deleted = client.delete(f"/devices/{created['id']}", params={"workspace_id": self.workspace_id})

        self.assertEqual(deleted.status_code, 405, deleted.text)

    def test_runtime_contract_loader_requires_manifest_contract_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GENERATED_ENTITY_CONTRACTS_JSON is required"):
                load_entity_contracts()

    def test_runtime_routes_follow_env_declared_operations(self):
        contracts = _contracts(allow_device_delete=False)
        with mock.patch.dict(
            os.environ,
            {
                "GENERATED_ENTITY_CONTRACTS_JSON": json.dumps(contracts),
                "GENERATED_ENTITY_CONTRACTS_ALLOW_DEFAULTS": "0",
            },
            clear=False,
        ):
            service = GenericEntityOperationsService(entity_contracts=load_entity_contracts(), storage_adapter=InMemoryStorageAdapter())
            client = TestClient(create_app(entity_service=service, initialize_schema=False))
            created = client.post(
                "/devices",
                json={"workspace_id": self.workspace_id, "name": "env-device", "kind": "router", "status": "online"},
            ).json()
            deleted = client.delete(f"/devices/{created['id']}", params={"workspace_id": self.workspace_id})

        self.assertEqual(deleted.status_code, 405, deleted.text)

    def test_runtime_can_serve_non_inventory_entity_contracts(self):
        workspace_id = str(uuid.uuid4())
        service = GenericEntityOperationsService(entity_contracts=_lunch_poll_contracts()[:1], storage_adapter=InMemoryStorageAdapter())
        client = TestClient(create_app(entity_service=service, initialize_schema=False))

        created = client.post(
            "/polls",
            json={"workspace_id": workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "draft"},
        )
        self.assertEqual(created.status_code, 201, created.text)

        listed = client.get("/polls", params={"workspace_id": workspace_id})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["title"], "Friday Lunch")

    def test_policy_loader_accepts_empty_and_invalid_payloads_truthfully(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_policy_bundle(), {})
        with mock.patch.dict(os.environ, {"GENERATED_POLICY_BUNDLE_JSON": "not-json"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                load_policy_bundle()

    def test_policy_compiler_retains_unsupported_families_without_claiming_enforcement(self):
        compiled = compile_policy_bundle(policy_bundle=_lunch_poll_policy_bundle(), entity_contracts=_lunch_poll_contracts())
        self.assertIn("votes", compiled["status_write_policies"])
        self.assertIn("votes", compiled["relation_constraints"])
        self.assertIn("polls", compiled["transition_guards"])
        self.assertIn("lunch_options", compiled["selection_invariants"])
        self.assertIn("lunch_options", compiled["required_selection_invariants"])
        self.assertIn("lunch_options", compiled["derived_policies"])
        self.assertIn("lunch_options", compiled["trigger_policies"])
        self.assertEqual(len(compiled["unsupported"]["validation_policies"]) if "validation_policies" in compiled["unsupported"] else 0, 0)
        self.assertEqual(len(compiled["unsupported"]["relation_constraints"]) if "relation_constraints" in compiled["unsupported"] else 0, 0)
        self.assertEqual(len(compiled["unsupported"]["transition_policies"]) if "transition_policies" in compiled["unsupported"] else 0, 0)
        self.assertEqual(len(compiled["unsupported"]["invariant_policies"]) if "invariant_policies" in compiled["unsupported"] else 0, 1)
        self.assertEqual(len(compiled["unsupported"]["derived_policies"]) if "derived_policies" in compiled["unsupported"] else 0, 1)
        self.assertEqual(len(compiled["unsupported"]["trigger_policies"]) if "trigger_policies" in compiled["unsupported"] else 0, 1)

    def test_vote_creation_is_blocked_when_parent_poll_is_not_open(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "draft"}).json()
        lunch_option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes"},
        ).json()

        vote = client.post(
            "/votes",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "lunch_option_id": lunch_option["id"], "voter_name": "Avery"},
        )

        self.assertEqual(vote.status_code, 400, vote.text)
        self.assertIn("only when the parent poll is open", vote.text)

    def test_vote_creation_succeeds_when_parent_poll_is_open(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        lunch_option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes"},
        ).json()

        vote = client.post(
            "/votes",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "lunch_option_id": lunch_option["id"], "voter_name": "Avery"},
        )

        self.assertEqual(vote.status_code, 201, vote.text)
        self.assertEqual(vote.json()["poll_id"], poll["id"])

    def test_vote_creation_rejects_cross_poll_lunch_option_reference(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll_a = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        poll_b = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Monday Lunch", "poll_date": "2026-03-18", "status": "open"}).json()
        lunch_option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll_a["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes"},
        ).json()

        vote = client.post(
            "/votes",
            json={"workspace_id": self.workspace_id, "poll_id": poll_b["id"], "lunch_option_id": lunch_option["id"], "voter_name": "Avery"},
        )

        self.assertEqual(vote.status_code, 400, vote.text)
        self.assertIn("same poll", vote.text)

    def test_transition_policy_rejects_invalid_direct_status_jump(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "draft"}).json()

        updated = client.patch(
            f"/polls/{poll['id']}",
            params={"workspace_id": self.workspace_id},
            json={"status": "selected"},
        )

        self.assertEqual(updated.status_code, 400, updated.text)
        self.assertIn("workflow order", updated.text)

    def test_related_count_policy_exposes_vote_counts_on_lunch_options(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        option_a = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "no"},
        ).json()
        option_b = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Sushi", "restaurant": "Uchi", "active": "yes", "selected": "no"},
        ).json()
        client.post(
            "/votes",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "lunch_option_id": option_a["id"], "voter_name": "Avery"},
        )
        client.post(
            "/votes",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "lunch_option_id": option_a["id"], "voter_name": "Jordan"},
        )

        listed = client.get("/lunch_options", params={"workspace_id": self.workspace_id})
        self.assertEqual(listed.status_code, 200, listed.text)
        counts = {row["id"]: row.get("_derived", {}).get("votes_count") for row in listed.json()["items"]}
        self.assertEqual(counts[option_a["id"]], 2)
        self.assertEqual(counts[option_b["id"]], 0)

        detailed = client.get(f"/lunch_options/{option_a['id']}", params={"workspace_id": self.workspace_id})
        self.assertEqual(detailed.status_code, 200, detailed.text)
        self.assertEqual(detailed.json()["_derived"]["votes_count"], 2)

    def test_trigger_policy_updates_parent_poll_status_when_option_selected(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "closed"}).json()
        option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "no"},
        ).json()

        updated = client.patch(
            f"/lunch_options/{option['id']}",
            params={"workspace_id": self.workspace_id},
            json={"selected": "yes"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        poll_detail = client.get(f"/polls/{poll['id']}", params={"workspace_id": self.workspace_id})
        self.assertEqual(poll_detail.status_code, 200, poll_detail.text)
        self.assertEqual(poll_detail.json()["status"], "selected")

    def test_trigger_policy_does_not_fire_for_non_matching_write(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "closed"}).json()
        option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "no"},
        ).json()

        updated = client.patch(
            f"/lunch_options/{option['id']}",
            params={"workspace_id": self.workspace_id},
            json={"notes": "Keep as backup"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        poll_detail = client.get(f"/polls/{poll['id']}", params={"workspace_id": self.workspace_id})
        self.assertEqual(poll_detail.status_code, 200, poll_detail.text)
        self.assertEqual(poll_detail.json()["status"], "closed")

    def test_invariant_allows_first_selected_option_per_poll(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()

        selected = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        )

        self.assertEqual(selected.status_code, 201, selected.text)
        self.assertEqual(selected.json()["selected"], "yes")

    def test_invariant_rejects_second_selected_option_for_same_poll(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        first = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        )
        self.assertEqual(first.status_code, 201, first.text)

        second = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Sushi", "restaurant": "Uchi", "active": "yes", "selected": "yes"},
        )

        self.assertEqual(second.status_code, 400, second.text)
        self.assertIn("Only one lunch option can be selected", second.text)

    def test_invariant_allows_selected_option_for_different_poll(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll_a = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        poll_b = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Monday Lunch", "poll_date": "2026-03-18", "status": "open"}).json()
        first = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll_a["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        )
        self.assertEqual(first.status_code, 201, first.text)

        second = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll_b["id"], "name": "Sushi", "restaurant": "Uchi", "active": "yes", "selected": "yes"},
        )

        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["poll_id"], poll_b["id"])

    def test_invariant_rejects_update_that_creates_duplicate_selection(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        option_a = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        ).json()
        option_b = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Sushi", "restaurant": "Uchi", "active": "yes", "selected": "no"},
        ).json()

        rejected = client.patch(
            f"/lunch_options/{option_b['id']}",
            params={"workspace_id": self.workspace_id},
            json={"selected": "yes"},
        )

        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertIn("Only one lunch option can be selected", rejected.text)

    def test_invariant_does_not_self_conflict_on_selected_record_update(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        ).json()

        updated = client.patch(
            f"/lunch_options/{option['id']}",
            params={"workspace_id": self.workspace_id},
            json={"notes": "still selected"},
        )

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["selected"], "yes")

    def test_required_selection_invariant_rejects_parent_selected_state_with_zero_selected_children(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "closed"}).json()

        updated = client.patch(
            f"/polls/{poll['id']}",
            params={"workspace_id": self.workspace_id},
            json={"status": "selected"},
        )

        self.assertEqual(updated.status_code, 400, updated.text)
        self.assertIn("must have exactly one selected", updated.text)

    def test_required_selection_invariant_allows_parent_selected_state_with_one_selected_child(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "closed"}).json()
        client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        )

        updated = client.patch(
            f"/polls/{poll['id']}",
            params={"workspace_id": self.workspace_id},
            json={"status": "selected"},
        )

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "selected")

    def test_required_selection_invariant_blocks_unselecting_last_selected_child_when_parent_is_selected(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "closed"}).json()
        option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        ).json()
        promote = client.patch(
            f"/polls/{poll['id']}",
            params={"workspace_id": self.workspace_id},
            json={"status": "selected"},
        )
        self.assertEqual(promote.status_code, 200, promote.text)

        rejected = client.patch(
            f"/lunch_options/{option['id']}",
            params={"workspace_id": self.workspace_id},
            json={"selected": "no"},
        )

        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertIn("must have exactly one selected", rejected.text)

    def test_required_selection_invariant_allows_unselecting_when_parent_not_in_gated_state(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        ).json()

        updated = client.patch(
            f"/lunch_options/{option['id']}",
            params={"workspace_id": self.workspace_id},
            json={"selected": "no"},
        )

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["selected"], "no")

    def test_required_selection_invariant_prevents_deleting_last_selected_child_when_parent_is_selected(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "closed"}).json()
        option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        ).json()
        promote = client.patch(
            f"/polls/{poll['id']}",
            params={"workspace_id": self.workspace_id},
            json={"status": "selected"},
        )
        self.assertEqual(promote.status_code, 200, promote.text)

        deleted = client.delete(
            f"/lunch_options/{option['id']}",
            params={"workspace_id": self.workspace_id},
        )

        self.assertEqual(deleted.status_code, 400, deleted.text)
        self.assertIn("must have exactly one selected", deleted.text)

    def test_trigger_driven_parent_selected_update_respects_required_selection_invariant(self):
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=_lunch_poll_policy_bundle(),
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "closed"}).json()
        option = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "no"},
        ).json()

        updated = client.patch(
            f"/lunch_options/{option['id']}",
            params={"workspace_id": self.workspace_id},
            json={"selected": "yes"},
        )

        self.assertEqual(updated.status_code, 200, updated.text)
        poll_detail = client.get(f"/polls/{poll['id']}", params={"workspace_id": self.workspace_id})
        self.assertEqual(poll_detail.status_code, 200, poll_detail.text)
        self.assertEqual(poll_detail.json()["status"], "selected")

    def test_writes_work_without_invariant_policy(self):
        bundle = _lunch_poll_policy_bundle_without_triggers()
        policies = bundle.get("policies") if isinstance(bundle.get("policies"), dict) else {}
        policies["invariant_policies"] = []
        service = GenericEntityOperationsService(
            entity_contracts=_lunch_poll_contracts(),
            policy_bundle=bundle,
            storage_adapter=InMemoryStorageAdapter(),
        )
        client = TestClient(create_app(entity_service=service, initialize_schema=False))
        poll = client.post("/polls", json={"workspace_id": self.workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "open"}).json()
        first = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Tacos", "restaurant": "La Tejana", "active": "yes", "selected": "yes"},
        )
        second = client.post(
            "/lunch_options",
            json={"workspace_id": self.workspace_id, "poll_id": poll["id"], "name": "Sushi", "restaurant": "Uchi", "active": "yes", "selected": "yes"},
        )

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)


if __name__ == "__main__":
    unittest.main()
