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


def load_policy_bundle() -> dict[str, Any]:
    raw = str(os.getenv("GENERATED_POLICY_BUNDLE_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GENERATED_POLICY_BUNDLE_JSON is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GENERATED_POLICY_BUNDLE_JSON must decode to an object")
    return _deepcopy(payload)


def _compiled_policy_map() -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {
        "relation_constraints": {},
        "status_write_policies": {},
        "transition_guards": {},
        "selection_invariants": {},
        "required_selection_invariants": {},
        "derived_policies": {},
        "trigger_policies": {},
        "unsupported": {},
    }


def _policy_entries(policy_bundle: dict[str, Any], family: str) -> list[dict[str, Any]]:
    policies = policy_bundle.get("policies") if isinstance(policy_bundle.get("policies"), dict) else {}
    rows = policies.get(family) if isinstance(policies.get(family), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _require_policy_parameters(policy: dict[str, Any], required: Iterable[str]) -> dict[str, Any]:
    params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else None
    if not params:
        raise RuntimeError(f"Policy '{policy.get('id') or policy.get('name') or 'unknown'}' is missing parameters")
    missing = [key for key in required if params.get(key) in (None, "", [])]
    if missing:
        raise RuntimeError(
            f"Policy '{policy.get('id') or policy.get('name') or 'unknown'}' is missing required parameters: {', '.join(missing)}"
        )
    return params


def compile_policy_bundle(*, policy_bundle: dict[str, Any], entity_contracts: Iterable[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    compiled = _compiled_policy_map()
    contracts = {
        str(contract.get("key") or "").strip(): copy.deepcopy(contract)
        for contract in entity_contracts
        if isinstance(contract, dict) and str(contract.get("key") or "").strip()
    }
    if not policy_bundle:
        return compiled

    for policy in _policy_entries(policy_bundle, "relation_constraints"):
        params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else {}
        if str(params.get("runtime_rule") or "").strip() != "match_related_field":
            compiled["unsupported"].setdefault("relation_constraints", []).append(copy.deepcopy(policy))
            continue
        params = _require_policy_parameters(
            policy,
            ["entity_key", "source_field", "related_entity", "related_match_field", "comparison_field"],
        )
        entity_key = str(params["entity_key"]).strip()
        if entity_key not in contracts:
            raise RuntimeError(f"Policy '{policy.get('id')}' references unknown entity '{entity_key}'")
        compiled["relation_constraints"].setdefault(entity_key, []).append(
            {
                "policy_id": str(policy.get("id") or policy.get("name") or "relation-constraint").strip(),
                "source_field": str(params["source_field"]).strip(),
                "related_entity": str(params["related_entity"]).strip(),
                "related_lookup_field": str(params.get("related_lookup_field") or "id").strip() or "id",
                "related_match_field": str(params["related_match_field"]).strip(),
                "comparison_field": str(params["comparison_field"]).strip(),
                "message": str((policy.get("explanation") or {}).get("user_summary") or policy.get("description") or "Related records must stay aligned.").strip(),
            }
        )

    for policy in _policy_entries(policy_bundle, "validation_policies"):
        params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else {}
        runtime_rule = str(params.get("runtime_rule") or "").strip()
        if runtime_rule not in {"parent_status_gate", "record_status_gate"}:
            compiled["unsupported"].setdefault("validation_policies", []).append(copy.deepcopy(policy))
            continue
        required = ["entity_key", "status_field", "on_operations"] if runtime_rule == "record_status_gate" else [
            "entity_key",
            "parent_entity",
            "parent_relation_field",
            "parent_status_field",
            "on_operations",
        ]
        params = _require_policy_parameters(policy, required)
        entity_key = str(params["entity_key"]).strip()
        if entity_key not in contracts:
            raise RuntimeError(f"Policy '{policy.get('id')}' references unknown entity '{entity_key}'")
        compiled["status_write_policies"].setdefault(entity_key, []).append(
            {
                "policy_id": str(policy.get("id") or policy.get("name") or "status-write-policy").strip(),
                "runtime_rule": runtime_rule,
                "parent_entity": str(params.get("parent_entity") or "").strip(),
                "parent_relation_field": str(params.get("parent_relation_field") or "").strip(),
                "status_field": str(params.get("status_field") or params.get("parent_status_field") or "").strip(),
                "allowed_statuses": [str(value).strip() for value in params.get("allowed_parent_statuses") or params.get("allowed_statuses") or [] if str(value).strip()],
                "blocked_statuses": [str(value).strip() for value in params.get("blocked_parent_statuses") or params.get("blocked_statuses") or [] if str(value).strip()],
                "on_operations": [str(value).strip() for value in params.get("on_operations") or [] if str(value).strip()],
                "message": str((policy.get("explanation") or {}).get("user_summary") or policy.get("description") or "Writes are blocked by policy.").strip(),
            }
        )

    for policy in _policy_entries(policy_bundle, "transition_policies"):
        params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else {}
        if str(params.get("runtime_rule") or "").strip() != "field_transition_guard":
            compiled["unsupported"].setdefault("transition_policies", []).append(copy.deepcopy(policy))
            continue
        params = _require_policy_parameters(policy, ["entity_key", "field_name", "allowed_transitions"])
        entity_key = str(params["entity_key"]).strip()
        if entity_key not in contracts:
            raise RuntimeError(f"Policy '{policy.get('id')}' references unknown entity '{entity_key}'")
        allowed_transitions = {
            str(source).strip(): [str(target).strip() for target in targets if str(target).strip()]
            for source, targets in (params.get("allowed_transitions") or {}).items()
            if str(source).strip() and isinstance(targets, list)
        }
        if not allowed_transitions:
            raise RuntimeError(f"Policy '{policy.get('id')}' did not include any allowed transitions")
        compiled["transition_guards"].setdefault(entity_key, []).append(
            {
                "policy_id": str(policy.get("id") or policy.get("name") or "transition-guard").strip(),
                "field_name": str(params["field_name"]).strip(),
                "allowed_transitions": allowed_transitions,
                "message": str((policy.get("explanation") or {}).get("user_summary") or policy.get("description") or "Transition not allowed.").strip(),
            }
        )

    for policy in _policy_entries(policy_bundle, "invariant_policies"):
        params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else {}
        runtime_rule = str(params.get("runtime_rule") or "").strip()
        if runtime_rule == "at_most_one_matching_child_per_parent":
            params = _require_policy_parameters(
                policy,
                ["entity_key", "parent_relation_field", "match_field", "match_value"],
            )
            entity_key = str(params["entity_key"]).strip()
            if entity_key not in contracts:
                raise RuntimeError(f"Policy '{policy.get('id')}' references unknown entity '{entity_key}'")
            compiled["selection_invariants"].setdefault(entity_key, []).append(
                {
                    "policy_id": str(policy.get("id") or policy.get("name") or "selection-invariant").strip(),
                    "runtime_rule": "at_most_one_matching_child_per_parent",
                    "parent_entity": str(params.get("parent_entity") or "").strip(),
                    "parent_relation_field": str(params["parent_relation_field"]).strip(),
                    "match_field": str(params["match_field"]).strip(),
                    "match_value": params["match_value"],
                    "on_operations": [str(value).strip() for value in params.get("on_operations") or [] if str(value).strip()] or ["create", "update"],
                    "message": str((policy.get("explanation") or {}).get("user_summary") or policy.get("description") or "Only one matching child record is allowed per parent.").strip(),
                }
            )
            continue
        if runtime_rule == "at_least_one_matching_child_per_parent":
            params = _require_policy_parameters(
                policy,
                ["entity_key", "parent_entity", "parent_relation_field", "match_field", "match_value"],
            )
            entity_key = str(params["entity_key"]).strip()
            parent_entity = str(params["parent_entity"]).strip()
            if entity_key not in contracts:
                raise RuntimeError(f"Policy '{policy.get('id')}' references unknown child entity '{entity_key}'")
            if parent_entity not in contracts:
                raise RuntimeError(f"Policy '{policy.get('id')}' references unknown parent entity '{parent_entity}'")
            compiled["required_selection_invariants"].setdefault(entity_key, []).append(
                {
                    "policy_id": str(policy.get("id") or policy.get("name") or "required-selection-invariant").strip(),
                    "runtime_rule": "at_least_one_matching_child_per_parent",
                    "entity_key": entity_key,
                    "parent_entity": parent_entity,
                    "parent_relation_field": str(params["parent_relation_field"]).strip(),
                    "match_field": str(params["match_field"]).strip(),
                    "match_value": params["match_value"],
                    "parent_state_field": str(params.get("parent_state_field") or "").strip(),
                    "parent_state_value": params.get("parent_state_value"),
                    "on_parent_operations": [str(value).strip() for value in params.get("on_parent_operations") or [] if str(value).strip()] or ["create", "update"],
                    "on_child_operations": [str(value).strip() for value in params.get("on_child_operations") or [] if str(value).strip()] or ["create", "update", "delete"],
                    "message": str((policy.get("explanation") or {}).get("user_summary") or policy.get("description") or "At least one matching child record is required for this parent state.").strip(),
                }
            )
            continue
        if runtime_rule:
            compiled["unsupported"].setdefault("invariant_policies", []).append(copy.deepcopy(policy))
            continue
        compiled["unsupported"].setdefault("invariant_policies", []).append(copy.deepcopy(policy))

    for policy in _policy_entries(policy_bundle, "derived_policies"):
        params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else {}
        if str(params.get("runtime_rule") or "").strip() != "related_count":
            compiled["unsupported"].setdefault("derived_policies", []).append(copy.deepcopy(policy))
            continue
        params = _require_policy_parameters(policy, ["entity_key", "child_entity", "child_relation_field", "output_field"])
        entity_key = str(params["entity_key"]).strip()
        child_entity = str(params["child_entity"]).strip()
        if entity_key not in contracts or child_entity not in contracts:
            raise RuntimeError(f"Policy '{policy.get('id')}' references unknown entity")
        compiled["derived_policies"].setdefault(entity_key, []).append(
            {
                "policy_id": str(policy.get("id") or policy.get("name") or "derived-policy").strip(),
                "runtime_rule": "related_count",
                "child_entity": child_entity,
                "child_relation_field": str(params["child_relation_field"]).strip(),
                "output_field": str(params["output_field"]).strip(),
                "surfaces": [str(value).strip() for value in params.get("surfaces") or [] if str(value).strip()],
                "message": str((policy.get("explanation") or {}).get("user_summary") or policy.get("description") or "Derived values are available.").strip(),
            }
        )

    for policy in _policy_entries(policy_bundle, "trigger_policies"):
        params = policy.get("parameters") if isinstance(policy.get("parameters"), dict) else {}
        if str(params.get("runtime_rule") or "").strip() != "post_write_related_update":
            compiled["unsupported"].setdefault("trigger_policies", []).append(copy.deepcopy(policy))
            continue
        params = _require_policy_parameters(
            policy,
            [
                "source_entity",
                "on_operations",
                "condition_field",
                "target_entity",
                "target_relation_field",
                "target_update_field",
                "target_update_value",
            ],
        )
        source_entity = str(params["source_entity"]).strip()
        target_entity = str(params["target_entity"]).strip()
        if source_entity not in contracts or target_entity not in contracts:
            raise RuntimeError(f"Policy '{policy.get('id')}' references unknown entity")
        compiled["trigger_policies"].setdefault(source_entity, []).append(
            {
                "policy_id": str(policy.get("id") or policy.get("name") or "trigger-policy").strip(),
                "runtime_rule": "post_write_related_update",
                "on_operations": [str(value).strip() for value in params.get("on_operations") or [] if str(value).strip()],
                "condition_field": str(params["condition_field"]).strip(),
                "condition_equals": params.get("condition_equals"),
                "target_entity": target_entity,
                "target_relation_field": str(params["target_relation_field"]).strip(),
                "target_lookup_field": str(params.get("target_lookup_field") or "id").strip() or "id",
                "target_update_field": str(params["target_update_field"]).strip(),
                "target_update_value": params["target_update_value"],
                "message": str((policy.get("explanation") or {}).get("user_summary") or policy.get("description") or "Related record updated by policy.").strip(),
            }
        )

    return compiled


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
    def __init__(self, *, entity_contracts: Iterable[Dict[str, Any]], storage_adapter: Any, policy_bundle: Optional[Dict[str, Any]] = None):
        contracts = [copy.deepcopy(item) for item in entity_contracts if isinstance(item, dict)]
        self._contracts = {str(item.get("key") or "").strip(): item for item in contracts if str(item.get("key") or "").strip()}
        self._storage = storage_adapter
        self._compiled_policies = compile_policy_bundle(policy_bundle=policy_bundle or {}, entity_contracts=contracts)

    @property
    def contracts(self) -> Dict[str, Dict[str, Any]]:
        return self._contracts

    @property
    def compiled_policies(self) -> Dict[str, Dict[str, list[dict[str, Any]]]]:
        return self._compiled_policies

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

    def _record_for_policy(self, contract: Dict[str, Any], *, record_id: Optional[str], workspace_id: Optional[str]) -> Optional[Dict[str, Any]]:
        normalized_id = _parse_uuid(record_id)
        if not normalized_id:
            return None
        return self._storage.get_by_id(contract, record_id=normalized_id, workspace_id=workspace_id)

    def _augment_with_derived_fields(self, entity_key: str, *, row: Dict[str, Any], workspace_id: Optional[str], surface: str) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return row
        derived_values: Dict[str, Any] = {}
        row_id = _parse_uuid(row.get("id"))
        if not row_id or not workspace_id:
            return row
        for policy in self._compiled_policies.get("derived_policies", {}).get(entity_key, []):
            surfaces = set(policy.get("surfaces") or [])
            if surfaces and surface not in surfaces:
                continue
            if policy.get("runtime_rule") == "related_count":
                child_contract = self.entity_contract(str(policy.get("child_entity") or "").strip())
                child_rows = self._storage.list(child_contract, workspace_id=workspace_id)
                derived_values[str(policy.get("output_field") or "").strip()] = sum(
                    1
                    for child in child_rows
                    if str(child.get(str(policy.get("child_relation_field") or "").strip()) or "") == row_id
                )
        if not derived_values:
            return row
        enriched = copy.deepcopy(row)
        enriched["_derived"] = derived_values
        return enriched

    def _apply_post_write_triggers(
        self,
        entity_key: str,
        *,
        operation: str,
        row: Dict[str, Any],
        workspace_id: Optional[str],
    ) -> None:
        for policy in self._compiled_policies.get("trigger_policies", {}).get(entity_key, []):
            if operation not in set(policy.get("on_operations") or []):
                continue
            condition_field = str(policy.get("condition_field") or "").strip()
            if not condition_field:
                continue
            actual_value = row.get(condition_field)
            expected_value = policy.get("condition_equals")
            if str(actual_value) != str(expected_value):
                continue
            target_contract = self.entity_contract(str(policy.get("target_entity") or "").strip())
            target_record_id = _parse_uuid(row.get(str(policy.get("target_relation_field") or "").strip()))
            if not target_record_id:
                continue
            target_row = self._record_for_policy(target_contract, record_id=target_record_id, workspace_id=workspace_id)
            if not target_row:
                raise EntityOperationError(404, f"{str(policy.get('target_entity') or '').rstrip('s').replace('_', ' ')} not found")
            target_workspace_id = str(target_row.get("workspace_id") or workspace_id or "").strip() or None
            normalized_update = self._normalize_payload(
                target_contract,
                {
                    str(policy.get("target_update_field") or "").strip(): policy.get("target_update_value"),
                },
                mode="update",
                workspace_id=target_workspace_id,
            )
            candidate = dict(target_row)
            candidate.update(normalized_update)
            self._enforce_status_write_policies(
                str(policy.get("target_entity") or "").strip(),
                operation="update",
                candidate=candidate,
                existing=target_row,
                workspace_id=target_workspace_id,
            )
            self._enforce_relation_constraints(
                str(policy.get("target_entity") or "").strip(),
                candidate=candidate,
                workspace_id=target_workspace_id,
            )
            self._enforce_transition_guards(
                str(policy.get("target_entity") or "").strip(),
                existing=target_row,
                candidate=candidate,
            )
            self._enforce_selection_invariants(
                str(policy.get("target_entity") or "").strip(),
                operation="update",
                candidate=candidate,
                existing=target_row,
                workspace_id=target_workspace_id,
            )
            self._enforce_required_selection_invariants_for_parent(
                str(policy.get("target_entity") or "").strip(),
                operation="update",
                candidate=candidate,
                existing=target_row,
                workspace_id=target_workspace_id,
            )
            self._enforce_required_selection_invariants_for_child(
                str(policy.get("target_entity") or "").strip(),
                operation="update",
                candidate=candidate,
                existing=target_row,
                workspace_id=target_workspace_id,
            )
            self._storage.update(
                target_contract,
                record_id=str(target_row.get("id")),
                workspace_id=target_workspace_id,
                values=normalized_update,
            )

    def _enforce_relation_constraints(
        self,
        entity_key: str,
        *,
        candidate: Dict[str, Any],
        workspace_id: Optional[str],
    ) -> None:
        for policy in self._compiled_policies.get("relation_constraints", {}).get(entity_key, []):
            source_id = _parse_uuid(candidate.get(policy["source_field"]))
            comparison_value = candidate.get(policy["comparison_field"])
            if not source_id or comparison_value in (None, ""):
                continue
            related_contract = self.entity_contract(policy["related_entity"])
            related_row = self._record_for_policy(related_contract, record_id=source_id, workspace_id=workspace_id)
            if not related_row:
                raise EntityOperationError(404, f"{policy['related_entity'].rstrip('s').replace('_', ' ')} not found")
            if str(related_row.get(policy["related_match_field"]) or "") != str(comparison_value):
                raise EntityOperationError(
                    400,
                    policy["message"],
                    meta={
                        "policy_id": policy["policy_id"],
                        "source_field": policy["source_field"],
                        "comparison_field": policy["comparison_field"],
                    },
                )

    def _enforce_status_write_policies(
        self,
        entity_key: str,
        *,
        operation: str,
        candidate: Dict[str, Any],
        existing: Optional[Dict[str, Any]],
        workspace_id: Optional[str],
    ) -> None:
        for policy in self._compiled_policies.get("status_write_policies", {}).get(entity_key, []):
            if operation not in set(policy.get("on_operations") or []):
                continue
            if policy.get("runtime_rule") == "parent_status_gate":
                relation_field = str(policy.get("parent_relation_field") or "").strip()
                parent_record_id = _parse_uuid(candidate.get(relation_field) or (existing or {}).get(relation_field))
                if not parent_record_id:
                    continue
                parent_contract = self.entity_contract(str(policy.get("parent_entity") or "").strip())
                parent_row = self._record_for_policy(parent_contract, record_id=parent_record_id, workspace_id=workspace_id)
                if not parent_row:
                    raise EntityOperationError(404, f"{str(policy.get('parent_entity') or '').rstrip('s').replace('_', ' ')} not found")
                status_value = str(parent_row.get(policy["status_field"]) or "").strip()
            else:
                status_value = str(candidate.get(policy["status_field"]) or (existing or {}).get(policy["status_field"]) or "").strip()
                if not status_value:
                    continue
            allowed_statuses = set(policy.get("allowed_statuses") or [])
            blocked_statuses = set(policy.get("blocked_statuses") or [])
            if allowed_statuses and status_value not in allowed_statuses:
                raise EntityOperationError(400, policy["message"], meta={"policy_id": policy["policy_id"], "status_value": status_value})
            if blocked_statuses and status_value in blocked_statuses:
                raise EntityOperationError(400, policy["message"], meta={"policy_id": policy["policy_id"], "status_value": status_value})

    def _enforce_transition_guards(self, entity_key: str, *, existing: Dict[str, Any], candidate: Dict[str, Any]) -> None:
        for policy in self._compiled_policies.get("transition_guards", {}).get(entity_key, []):
            field_name = str(policy.get("field_name") or "").strip()
            if field_name not in candidate:
                continue
            previous = str(existing.get(field_name) or "").strip()
            current = str(candidate.get(field_name) or "").strip()
            if not previous or not current or previous == current:
                continue
            allowed = set((policy.get("allowed_transitions") or {}).get(previous) or [])
            if current not in allowed:
                raise EntityOperationError(
                    400,
                    policy["message"],
                    meta={"policy_id": policy["policy_id"], "from": previous, "to": current, "field_name": field_name},
                )

    def _enforce_selection_invariants(
        self,
        entity_key: str,
        *,
        operation: str,
        candidate: Dict[str, Any],
        existing: Optional[Dict[str, Any]],
        workspace_id: Optional[str],
    ) -> None:
        if not workspace_id:
            return
        contract = self.entity_contract(entity_key)
        current_record_id = _parse_uuid((existing or {}).get("id") or candidate.get("id"))
        for policy in self._compiled_policies.get("selection_invariants", {}).get(entity_key, []):
            if operation not in set(policy.get("on_operations") or []):
                continue
            match_field = str(policy.get("match_field") or "").strip()
            parent_field = str(policy.get("parent_relation_field") or "").strip()
            if not match_field or not parent_field:
                continue
            match_value = policy.get("match_value")
            current_value = candidate.get(match_field) if match_field in candidate else (existing or {}).get(match_field)
            if str(current_value) != str(match_value):
                continue
            parent_id = _parse_uuid(candidate.get(parent_field) or (existing or {}).get(parent_field))
            if not parent_id:
                continue
            rows = self._storage.list(contract, workspace_id=workspace_id)
            for row in rows:
                row_id = _parse_uuid(row.get("id"))
                if current_record_id and row_id and row_id == current_record_id:
                    continue
                if _parse_uuid(row.get(parent_field)) != parent_id:
                    continue
                if str(row.get(match_field)) != str(match_value):
                    continue
                raise EntityOperationError(
                    400,
                    policy["message"],
                    meta={
                        "policy_id": policy["policy_id"],
                        "parent_relation_field": parent_field,
                        "match_field": match_field,
                        "match_value": match_value,
                    },
                )

    def _matching_child_count(
        self,
        *,
        child_contract: Dict[str, Any],
        parent_field: str,
        parent_id: str,
        match_field: str,
        match_value: Any,
        workspace_id: Optional[str],
        exclude_record_id: Optional[str] = None,
        include_row: Optional[Dict[str, Any]] = None,
    ) -> int:
        if not workspace_id:
            return 0
        count = 0
        rows = self._storage.list(child_contract, workspace_id=workspace_id)
        excluded_id = _parse_uuid(exclude_record_id) if exclude_record_id else None
        normalized_parent_id = _parse_uuid(parent_id)
        for row in rows:
            row_id = _parse_uuid(row.get("id"))
            if excluded_id and row_id and row_id == excluded_id:
                continue
            if _parse_uuid(row.get(parent_field)) != normalized_parent_id:
                continue
            if str(row.get(match_field)) != str(match_value):
                continue
            count += 1
        if include_row is not None:
            if _parse_uuid(include_row.get(parent_field)) == normalized_parent_id and str(include_row.get(match_field)) == str(match_value):
                count += 1
        return count

    def _parent_state_gate_applies(
        self,
        *,
        policy: Dict[str, Any],
        parent_row: Optional[Dict[str, Any]],
        parent_candidate: Optional[Dict[str, Any]] = None,
    ) -> bool:
        parent_state_field = str(policy.get("parent_state_field") or "").strip()
        if not parent_state_field:
            return True
        required_value = policy.get("parent_state_value")
        if parent_candidate is not None and parent_state_field in parent_candidate:
            current_value = parent_candidate.get(parent_state_field)
        elif parent_row is not None:
            current_value = parent_row.get(parent_state_field)
        else:
            return False
        return str(current_value) == str(required_value)

    def _enforce_required_selection_invariants_for_parent(
        self,
        entity_key: str,
        *,
        operation: str,
        candidate: Dict[str, Any],
        existing: Optional[Dict[str, Any]],
        workspace_id: Optional[str],
    ) -> None:
        if not workspace_id:
            return
        parent_record_id = _parse_uuid((existing or {}).get("id") or candidate.get("id"))
        for child_entity, policies in self._compiled_policies.get("required_selection_invariants", {}).items():
            for policy in policies:
                if str(policy.get("parent_entity") or "").strip() != entity_key:
                    continue
                if operation not in set(policy.get("on_parent_operations") or []):
                    continue
                if not self._parent_state_gate_applies(policy=policy, parent_row=existing, parent_candidate=candidate):
                    continue
                child_contract = self.entity_contract(child_entity)
                parent_field = str(policy.get("parent_relation_field") or "").strip()
                match_field = str(policy.get("match_field") or "").strip()
                match_value = policy.get("match_value")
                matching_count = 0
                if parent_record_id:
                    matching_count = self._matching_child_count(
                        child_contract=child_contract,
                        parent_field=parent_field,
                        parent_id=parent_record_id,
                        match_field=match_field,
                        match_value=match_value,
                        workspace_id=workspace_id,
                    )
                if matching_count < 1:
                    raise EntityOperationError(
                        400,
                        policy["message"],
                        meta={
                            "policy_id": policy["policy_id"],
                            "parent_entity": entity_key,
                            "child_entity": child_entity,
                            "required_count": 1,
                            "matching_count": matching_count,
                        },
                    )

    def _enforce_required_selection_invariants_for_child(
        self,
        entity_key: str,
        *,
        operation: str,
        candidate: Optional[Dict[str, Any]],
        existing: Optional[Dict[str, Any]],
        workspace_id: Optional[str],
    ) -> None:
        if not workspace_id:
            return
        child_contract = self.entity_contract(entity_key)
        for policy in self._compiled_policies.get("required_selection_invariants", {}).get(entity_key, []):
            if operation not in set(policy.get("on_child_operations") or []):
                continue
            parent_field = str(policy.get("parent_relation_field") or "").strip()
            match_field = str(policy.get("match_field") or "").strip()
            match_value = policy.get("match_value")
            impacted_parents: set[str] = set()
            old_parent_id = _parse_uuid((existing or {}).get(parent_field))
            new_parent_id = _parse_uuid((candidate or {}).get(parent_field))
            if old_parent_id:
                impacted_parents.add(old_parent_id)
            if new_parent_id:
                impacted_parents.add(new_parent_id)
            for parent_id in impacted_parents:
                parent_contract = self.entity_contract(str(policy.get("parent_entity") or "").strip())
                parent_row = self._record_for_policy(parent_contract, record_id=parent_id, workspace_id=workspace_id)
                if not parent_row:
                    continue
                if not self._parent_state_gate_applies(policy=policy, parent_row=parent_row):
                    continue
                include_row = None
                exclude_record_id = None
                if operation == "create":
                    include_row = candidate
                elif operation == "update":
                    exclude_record_id = str((existing or {}).get("id") or "")
                    include_row = candidate
                elif operation == "delete":
                    exclude_record_id = str((existing or {}).get("id") or "")
                matching_count = self._matching_child_count(
                    child_contract=child_contract,
                    parent_field=parent_field,
                    parent_id=parent_id,
                    match_field=match_field,
                    match_value=match_value,
                    workspace_id=workspace_id,
                    exclude_record_id=exclude_record_id,
                    include_row=include_row,
                )
                if matching_count < 1:
                    raise EntityOperationError(
                        400,
                        policy["message"],
                        meta={
                            "policy_id": policy["policy_id"],
                            "parent_entity": policy.get("parent_entity"),
                            "child_entity": entity_key,
                            "required_count": 1,
                            "matching_count": matching_count,
                        },
                    )

    def list_records(self, entity_key: str, *, context: RecordContext) -> list[Dict[str, Any]]:
        contract = self._operation_contract(entity_key, "list")
        if not context.workspace_id:
            raise EntityOperationError(400, "workspace_id is required")
        rows = self._storage.list(contract, workspace_id=context.workspace_id)
        return [self._augment_with_derived_fields(entity_key, row=row, workspace_id=context.workspace_id, surface="list") for row in rows]

    def get_record(self, entity_key: str, id_or_reference: str, *, context: RecordContext) -> Dict[str, Any]:
        self._operation_contract(entity_key, "get")
        row = self._resolve_record_reference(entity_key, id_or_reference, workspace_id=context.workspace_id)
        workspace_id = str(row.get("workspace_id") or context.workspace_id or "").strip() or None
        return self._augment_with_derived_fields(entity_key, row=row, workspace_id=workspace_id, surface="detail")

    def create_record(self, entity_key: str, fields: Dict[str, Any], *, context: RecordContext) -> Dict[str, Any]:
        contract = self._operation_contract(entity_key, "create")
        workspace_id = context.workspace_id or str(fields.get("workspace_id") or "").strip() or None
        normalized = self._normalize_payload(contract, fields, mode="create", workspace_id=workspace_id)
        self._enforce_status_write_policies(entity_key, operation="create", candidate=normalized, existing=None, workspace_id=workspace_id)
        self._enforce_relation_constraints(entity_key, candidate=normalized, workspace_id=workspace_id)
        self._enforce_selection_invariants(entity_key, operation="create", candidate=normalized, existing=None, workspace_id=workspace_id)
        self._enforce_required_selection_invariants_for_parent(
            entity_key,
            operation="create",
            candidate=normalized,
            existing=None,
            workspace_id=workspace_id,
        )
        self._enforce_required_selection_invariants_for_child(
            entity_key,
            operation="create",
            candidate=normalized,
            existing=None,
            workspace_id=workspace_id,
        )
        row = self._storage.insert(contract, values=normalized)
        self._apply_post_write_triggers(entity_key, operation="create", row=row, workspace_id=workspace_id)
        return self._augment_with_derived_fields(entity_key, row=row, workspace_id=workspace_id, surface="detail")

    def update_record(self, entity_key: str, id_or_reference: str, fields: Dict[str, Any], *, context: RecordContext) -> Dict[str, Any]:
        contract = self._operation_contract(entity_key, "update")
        existing = self._resolve_record_reference(entity_key, id_or_reference, workspace_id=context.workspace_id)
        workspace_id = str(existing.get("workspace_id") or context.workspace_id or "").strip() or None
        normalized = self._normalize_payload(contract, fields, mode="update", workspace_id=workspace_id)
        candidate = dict(existing)
        candidate.update(normalized)
        self._enforce_status_write_policies(entity_key, operation="update", candidate=candidate, existing=existing, workspace_id=workspace_id)
        self._enforce_relation_constraints(entity_key, candidate=candidate, workspace_id=workspace_id)
        self._enforce_transition_guards(entity_key, existing=existing, candidate=candidate)
        self._enforce_selection_invariants(entity_key, operation="update", candidate=candidate, existing=existing, workspace_id=workspace_id)
        self._enforce_required_selection_invariants_for_parent(
            entity_key,
            operation="update",
            candidate=candidate,
            existing=existing,
            workspace_id=workspace_id,
        )
        self._enforce_required_selection_invariants_for_child(
            entity_key,
            operation="update",
            candidate=candidate,
            existing=existing,
            workspace_id=workspace_id,
        )
        row = self._storage.update(contract, record_id=str(existing.get("id")), workspace_id=workspace_id, values=normalized)
        self._apply_post_write_triggers(entity_key, operation="update", row=row, workspace_id=workspace_id)
        return self._augment_with_derived_fields(entity_key, row=row, workspace_id=workspace_id, surface="detail")

    def delete_record(self, entity_key: str, id_or_reference: str, *, context: RecordContext) -> Dict[str, Any]:
        contract = self._operation_contract(entity_key, "delete")
        existing = self._resolve_record_reference(entity_key, id_or_reference, workspace_id=context.workspace_id)
        workspace_id = str(existing.get("workspace_id") or context.workspace_id or "").strip() or None
        self._enforce_required_selection_invariants_for_child(
            entity_key,
            operation="delete",
            candidate=None,
            existing=existing,
            workspace_id=workspace_id,
        )
        return self._storage.delete(contract, record_id=str(existing.get("id")), workspace_id=workspace_id)
