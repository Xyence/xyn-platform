from __future__ import annotations

import copy
import json
import os
import unittest
import uuid
from unittest import mock

from fastapi.testclient import TestClient

from entity_ops import DEFAULT_ENTITY_CONTRACTS, GenericEntityOperationsService, load_entity_contracts
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
        lunch_poll_contracts = [
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
            }
        ]
        service = GenericEntityOperationsService(entity_contracts=lunch_poll_contracts, storage_adapter=InMemoryStorageAdapter())
        client = TestClient(create_app(entity_service=service, initialize_schema=False))

        created = client.post(
            "/polls",
            json={"workspace_id": workspace_id, "title": "Friday Lunch", "poll_date": "2026-03-17", "status": "draft"},
        )
        self.assertEqual(created.status_code, 201, created.text)

        listed = client.get("/polls", params={"workspace_id": workspace_id})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["title"], "Friday Lunch")


if __name__ == "__main__":
    unittest.main()
