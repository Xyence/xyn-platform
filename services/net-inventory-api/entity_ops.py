from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from psycopg2 import sql


def _deepcopy(value: Any) -> Any:
    return json.loads(json.dumps(value))


DEFAULT_ENTITY_CONTRACTS: list[dict[str, Any]] = [
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
                "name": "kind",
                "type": "string",
                "required": True,
                "readable": True,
                "writable": True,
                "identity": False,
                "options": ["device", "router", "switch"],
            },
            {
                "name": "status",
                "type": "string",
                "required": True,
                "readable": True,
                "writable": True,
                "identity": False,
                "options": ["unknown", "online", "offline"],
            },
            {
                "name": "location_id",
                "type": "uuid|null",
                "required": False,
                "readable": True,
                "writable": True,
                "identity": True,
                "relation": {
                    "target_entity": "locations",
                    "target_field": "id",
                    "relation_kind": "belongs_to",
                },
            },
            {"name": "created_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
            {"name": "updated_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
        ],
        "presentation": {
            "default_list_fields": ["name", "kind", "status", "location_id"],
            "default_detail_fields": ["id", "name", "kind", "status", "location_id", "workspace_id", "created_at", "updated_at"],
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
            {"name": "kind", "type": "string", "required": True, "readable": True, "writable": True, "identity": False},
            {"name": "parent_location_id", "type": "uuid|null", "required": False, "readable": True, "writable": True, "identity": False},
            {"name": "address_line1", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": False},
            {"name": "address_line2", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": False},
            {"name": "city", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": True},
            {"name": "region", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": True},
            {"name": "postal_code", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": False},
            {"name": "country", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": True},
            {"name": "notes", "type": "string|null", "required": False, "readable": True, "writable": True, "identity": False},
            {"name": "tags_json", "type": "json|null", "required": False, "readable": True, "writable": True, "identity": False},
            {"name": "created_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
            {"name": "updated_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
        ],
        "presentation": {
            "default_list_fields": ["name", "kind", "city", "region", "country"],
            "default_detail_fields": ["id", "name", "kind", "city", "region", "country", "workspace_id", "created_at", "updated_at"],
            "title_field": "name",
        },
        "validation": {
            "required_on_create": ["workspace_id", "name"],
            "allowed_on_update": [
                "name",
                "kind",
                "parent_location_id",
                "address_line1",
                "address_line2",
                "city",
                "region",
                "postal_code",
                "country",
                "notes",
                "tags_json",
            ],
        },
        "relationships": [
            {
                "field": "parent_location_id",
                "target_entity": "locations",
                "target_field": "id",
                "relation_kind": "belongs_to",
                "required": False,
            }
        ],
    },
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
                "relation": {
                    "target_entity": "devices",
                    "target_field": "id",
                    "relation_kind": "belongs_to",
                },
            },
            {"name": "name", "type": "string", "required": True, "readable": True, "writable": True, "identity": True},
            {
                "name": "status",
                "type": "string",
                "required": True,
                "readable": True,
                "writable": True,
                "identity": False,
                "options": ["unknown", "up", "down"],
            },
            {"name": "created_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
            {"name": "updated_at", "type": "datetime", "required": True, "readable": True, "writable": False, "identity": False},
        ],
        "presentation": {
            "default_list_fields": ["name", "device_id", "status"],
            "default_detail_fields": ["id", "name", "device_id", "status", "workspace_id", "created_at", "updated_at"],
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
    },
]


def _allow_default_contracts() -> bool:
    return str(os.getenv("GENERATED_ENTITY_CONTRACTS_ALLOW_DEFAULTS", "") or "").strip().lower() in {"1", "true", "yes", "on"}


def load_entity_contracts() -> list[dict[str, Any]]:
    raw = str(os.getenv("GENERATED_ENTITY_CONTRACTS_JSON", "") or "").strip()
    if not raw:
        if _allow_default_contracts():
            return _deepcopy(DEFAULT_ENTITY_CONTRACTS)
        raise RuntimeError("GENERATED_ENTITY_CONTRACTS_JSON is required for generated runtime")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        if _allow_default_contracts():
            return _deepcopy(DEFAULT_ENTITY_CONTRACTS)
        raise RuntimeError("GENERATED_ENTITY_CONTRACTS_JSON is invalid JSON") from exc
    if isinstance(payload, dict) and isinstance(payload.get("entities"), list):
        payload = payload.get("entities")
    if not isinstance(payload, list):
        if _allow_default_contracts():
            return _deepcopy(DEFAULT_ENTITY_CONTRACTS)
        raise RuntimeError("GENERATED_ENTITY_CONTRACTS_JSON must decode to a list of entities")
    rows = [row for row in payload if isinstance(row, dict)]
    if rows:
        return _deepcopy(rows)
    if _allow_default_contracts():
        return _deepcopy(DEFAULT_ENTITY_CONTRACTS)
    raise RuntimeError("GENERATED_ENTITY_CONTRACTS_JSON did not include any entity contracts")


class EntityOperationError(Exception):
    def __init__(self, status_code: int, detail: str, *, meta: Optional[Dict[str, Any]] = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.meta = meta or {}


def _parse_uuid(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except (ValueError, TypeError, AttributeError):
        return None


def _strip_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _field_map(contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = contract.get("fields") if isinstance(contract.get("fields"), list) else []
    return {str(row.get("name") or "").strip(): row for row in rows if isinstance(row, dict) and str(row.get("name") or "").strip()}


def _readable_fields(contract: Dict[str, Any]) -> list[str]:
    return [name for name, field in _field_map(contract).items() if bool(field.get("readable", True))]


def _writable_fields(contract: Dict[str, Any]) -> set[str]:
    return {name for name, field in _field_map(contract).items() if bool(field.get("writable", False))}


def _identity_fields(contract: Dict[str, Any]) -> list[str]:
    field_map = _field_map(contract)
    title_field = str(((contract.get("presentation") or {}).get("title_field")) or "").strip()
    ordered: list[str] = []
    if title_field and title_field in field_map and bool(field_map[title_field].get("identity")):
        ordered.append(title_field)
    for name, field in field_map.items():
        if not bool(field.get("identity")) or name in ordered:
            continue
        ordered.append(name)
    return ordered


def _validate_field_value(field: Dict[str, Any], value: Any) -> Any:
    field_type = str(field.get("type") or "string").strip().lower()
    if value is None:
        if "|null" in field_type or field_type.endswith("null") or not bool(field.get("required")):
            return None
        raise EntityOperationError(400, f"Field '{field.get('name')}' is required")
    if "uuid" in field_type:
        parsed = _parse_uuid(value)
        if not parsed:
            raise EntityOperationError(400, f"Field '{field.get('name')}' must be a UUID")
        return parsed
    if field_type.startswith("string"):
        text = _strip_text(value)
        if bool(field.get("required")) and not text:
            raise EntityOperationError(400, f"Field '{field.get('name')}' is required")
        options = field.get("options") if isinstance(field.get("options"), list) else []
        if options and text not in {str(option) for option in options}:
            raise EntityOperationError(400, f"Field '{field.get('name')}' must be one of: {', '.join(str(option) for option in options)}")
        return text
    if field_type.startswith("json"):
        return value
    return value


@dataclass
class RecordContext:
    workspace_id: Optional[str] = None


class PostgresEntityStorageAdapter:
    def __init__(self, *, get_conn):
        self._get_conn = get_conn

    def _table(self, contract: Dict[str, Any]) -> sql.Identifier:
        return sql.Identifier(str(contract.get("key") or ""))

    def list(self, contract: Dict[str, Any], *, workspace_id: str) -> list[Dict[str, Any]]:
        fields = [sql.Identifier(name) for name in _readable_fields(contract)]
        query = sql.SQL("SELECT {fields} FROM {table} WHERE workspace_id = %s ORDER BY created_at DESC").format(
            fields=sql.SQL(", ").join(fields),
            table=self._table(contract),
        )
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (workspace_id,))
                return list(cur.fetchall() or [])

    def get_by_id(self, contract: Dict[str, Any], *, record_id: str, workspace_id: Optional[str]) -> Optional[Dict[str, Any]]:
        fields = [sql.Identifier(name) for name in _readable_fields(contract)]
        params: list[Any] = [record_id]
        query = sql.SQL("SELECT {fields} FROM {table} WHERE id = %s").format(
            fields=sql.SQL(", ").join(fields),
            table=self._table(contract),
        )
        if workspace_id and "workspace_id" in _field_map(contract):
            query += sql.SQL(" AND workspace_id = %s")
            params.append(workspace_id)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                return cur.fetchone()

    def find_by_identity(self, contract: Dict[str, Any], *, field_name: str, field_value: Any, workspace_id: str) -> Optional[Dict[str, Any]]:
        fields = [sql.Identifier(name) for name in _readable_fields(contract)]
        query = sql.SQL(
            "SELECT {fields} FROM {table} WHERE {field_name} = %s AND workspace_id = %s ORDER BY created_at DESC LIMIT 1"
        ).format(
            fields=sql.SQL(", ").join(fields),
            table=self._table(contract),
            field_name=sql.Identifier(field_name),
        )
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (field_value, workspace_id))
                return cur.fetchone()

    def insert(self, contract: Dict[str, Any], *, values: Dict[str, Any]) -> Dict[str, Any]:
        row_id = str(uuid.uuid4())
        payload = dict(values)
        payload["id"] = row_id
        field_names = list(payload.keys())
        insert_query = sql.SQL(
            "INSERT INTO {table} ({fields}, created_at, updated_at) VALUES ({values}, NOW(), NOW())"
        ).format(
            table=self._table(contract),
            fields=sql.SQL(", ").join(sql.Identifier(name) for name in field_names),
            values=sql.SQL(", ").join(sql.Placeholder() for _ in field_names),
        )
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(insert_query, tuple(payload[name] for name in field_names))
                conn.commit()
        row = self.get_by_id(contract, record_id=row_id, workspace_id=str(values.get("workspace_id") or "") or None)
        if not row:
            raise EntityOperationError(500, f"Created {contract.get('singular_label') or contract.get('key')} could not be reloaded")
        return row

    def update(self, contract: Dict[str, Any], *, record_id: str, workspace_id: Optional[str], values: Dict[str, Any]) -> Dict[str, Any]:
        assignments = [sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder()) for name in values.keys()]
        assignments.append(sql.SQL("updated_at = NOW()"))
        params: list[Any] = [values[name] for name in values.keys()]
        params.append(record_id)
        query = sql.SQL("UPDATE {table} SET {assignments} WHERE id = %s").format(
            table=self._table(contract),
            assignments=sql.SQL(", ").join(assignments),
        )
        if workspace_id and "workspace_id" in _field_map(contract):
            query += sql.SQL(" AND workspace_id = %s")
            params.append(workspace_id)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                if cur.rowcount < 1:
                    raise EntityOperationError(404, f"{contract.get('singular_label') or contract.get('key')} not found")
                conn.commit()
        row = self.get_by_id(contract, record_id=record_id, workspace_id=workspace_id)
        if not row:
            raise EntityOperationError(404, f"{contract.get('singular_label') or contract.get('key')} not found")
        return row

    def delete(self, contract: Dict[str, Any], *, record_id: str, workspace_id: Optional[str]) -> Dict[str, Any]:
        existing = self.get_by_id(contract, record_id=record_id, workspace_id=workspace_id)
        if not existing:
            raise EntityOperationError(404, f"{contract.get('singular_label') or contract.get('key')} not found")
        params: list[Any] = [record_id]
        query = sql.SQL("DELETE FROM {table} WHERE id = %s").format(table=self._table(contract))
        if workspace_id and "workspace_id" in _field_map(contract):
            query += sql.SQL(" AND workspace_id = %s")
            params.append(workspace_id)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                conn.commit()
        return existing


class GenericEntityOperationsService:
    def __init__(self, *, entity_contracts: Iterable[Dict[str, Any]], storage_adapter: Any):
        contracts = [copy.deepcopy(item) for item in entity_contracts if isinstance(item, dict)]
        self._contracts = {str(item.get("key") or "").strip(): item for item in contracts if str(item.get("key") or "").strip()}
        self._storage = storage_adapter

    @property
    def contracts(self) -> Dict[str, Dict[str, Any]]:
        return self._contracts

    def entity_contract(self, entity_key: str) -> Dict[str, Any]:
        contract = self._contracts.get(str(entity_key or "").strip())
        if not contract:
            raise EntityOperationError(404, f"Unknown entity '{entity_key}'")
        return contract

    def _operation_contract(self, entity_key: str, operation: str) -> Dict[str, Any]:
        contract = self.entity_contract(entity_key)
        operations = contract.get("operations") if isinstance(contract.get("operations"), dict) else {}
        spec = operations.get(operation) if isinstance(operations.get(operation), dict) else None
        if not spec or not bool(spec.get("declared")):
            raise EntityOperationError(405, f"Operation '{operation}' is not declared for entity '{entity_key}'")
        return contract

    def _normalize_payload(self, contract: Dict[str, Any], payload: Dict[str, Any], *, mode: str, workspace_id: Optional[str]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise EntityOperationError(400, "JSON object payload required")
        field_map = _field_map(contract)
        writable_fields = _writable_fields(contract)
        normalized: Dict[str, Any] = {}
        allowed_update = set((contract.get("validation") or {}).get("allowed_on_update") or [])
        for key, value in payload.items():
            field = field_map.get(str(key))
            if not field:
                raise EntityOperationError(400, f"Unknown field '{key}'")
            if key not in writable_fields:
                raise EntityOperationError(400, f"Field '{key}' is not writable")
            if mode == "update" and key not in allowed_update:
                raise EntityOperationError(400, f"Field '{key}' is not allowed on update")
            relation = field.get("relation") if isinstance(field.get("relation"), dict) else None
            if relation and value not in (None, ""):
                value = self._resolve_relation_value(
                    relation=relation,
                    raw_value=value,
                    workspace_id=workspace_id or str(payload.get("workspace_id") or "").strip() or None,
                )
            normalized[key] = _validate_field_value(field, value)
        if mode == "create":
            required_fields = list((contract.get("validation") or {}).get("required_on_create") or [])
            missing = [name for name in required_fields if normalized.get(name) in (None, "")]
            if missing:
                raise EntityOperationError(400, f"Missing required fields: {', '.join(missing)}", meta={"missing_fields": missing})
        if mode == "update" and not normalized:
            raise EntityOperationError(400, "At least one updatable field is required")
        return normalized

    def _resolve_record_reference(self, entity_key: str, reference: str, *, workspace_id: Optional[str]) -> Dict[str, Any]:
        contract = self.entity_contract(entity_key)
        record_id = _parse_uuid(reference)
        if record_id:
            row = self._storage.get_by_id(contract, record_id=record_id, workspace_id=workspace_id)
            if row:
                return row
        if not workspace_id:
            raise EntityOperationError(400, "workspace_id is required when resolving by non-id identity")
        for field_name in _identity_fields(contract):
            if field_name == "id":
                continue
            row = self._storage.find_by_identity(contract, field_name=field_name, field_value=reference, workspace_id=workspace_id)
            if row:
                return row
        raise EntityOperationError(404, f"{contract.get('singular_label') or entity_key} not found")

    def _resolve_relation_value(self, *, relation: Dict[str, Any], raw_value: Any, workspace_id: Optional[str]) -> Optional[str]:
        direct_id = _parse_uuid(raw_value)
        if direct_id:
            return direct_id
        if not workspace_id:
            raise EntityOperationError(400, "workspace_id is required to resolve relationship values")
        target_entity = str(relation.get("target_entity") or "").strip()
        target = self._resolve_record_reference(target_entity, str(raw_value), workspace_id=workspace_id)
        return str(target.get(relation.get("target_field") or "id") or "")

    def list_records(self, entity_key: str, *, context: RecordContext) -> list[Dict[str, Any]]:
        contract = self._operation_contract(entity_key, "list")
        if not context.workspace_id:
            raise EntityOperationError(400, "workspace_id is required")
        return self._storage.list(contract, workspace_id=context.workspace_id)

    def get_record(self, entity_key: str, id_or_reference: str, *, context: RecordContext) -> Dict[str, Any]:
        self._operation_contract(entity_key, "get")
        return self._resolve_record_reference(entity_key, id_or_reference, workspace_id=context.workspace_id)

    def create_record(self, entity_key: str, fields: Dict[str, Any], *, context: RecordContext) -> Dict[str, Any]:
        contract = self._operation_contract(entity_key, "create")
        workspace_id = context.workspace_id or str(fields.get("workspace_id") or "").strip() or None
        normalized = self._normalize_payload(contract, fields, mode="create", workspace_id=workspace_id)
        return self._storage.insert(contract, values=normalized)

    def update_record(self, entity_key: str, id_or_reference: str, fields: Dict[str, Any], *, context: RecordContext) -> Dict[str, Any]:
        contract = self._operation_contract(entity_key, "update")
        existing = self._resolve_record_reference(entity_key, id_or_reference, workspace_id=context.workspace_id)
        workspace_id = str(existing.get("workspace_id") or context.workspace_id or "").strip() or None
        normalized = self._normalize_payload(contract, fields, mode="update", workspace_id=workspace_id)
        return self._storage.update(contract, record_id=str(existing.get("id")), workspace_id=workspace_id, values=normalized)

    def delete_record(self, entity_key: str, id_or_reference: str, *, context: RecordContext) -> Dict[str, Any]:
        contract = self._operation_contract(entity_key, "delete")
        existing = self._resolve_record_reference(entity_key, id_or_reference, workspace_id=context.workspace_id)
        workspace_id = str(existing.get("workspace_id") or context.workspace_id or "").strip() or None
        return self._storage.delete(contract, record_id=str(existing.get("id")), workspace_id=workspace_id)
