from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, Dict


class ArtifactActivationError(RuntimeError):
    """Raised when artifact activation cannot be safely queued."""


def _normalize_unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def _app_spec_signature(app_spec: Dict[str, Any]) -> str:
    signature_source: Dict[str, Any] = {}
    for key in (
        "app_slug",
        "entities",
        "entity_contracts",
        "reports",
        "requested_visuals",
        "requires_primitives",
        "workflow_definitions",
        "platform_primitive_composition",
        "ui_surfaces",
        "domain_model",
        "structured_plan",
    ):
        if key in app_spec:
            signature_source[key] = copy.deepcopy(app_spec.get(key))
    return hashlib.sha256(
        json.dumps(signature_source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _policy_compatibility(
    *,
    app_spec: Dict[str, Any],
    policy_bundle: Dict[str, Any] | None,
) -> tuple[str, str]:
    if not isinstance(policy_bundle, dict) or not policy_bundle:
        return "unknown", "policy_artifact_unavailable"
    derivation = policy_bundle.get("derivation") if isinstance(policy_bundle.get("derivation"), dict) else {}
    expected_signature = str(derivation.get("app_spec_signature") or "").strip()
    if not expected_signature:
        return "unknown", "missing_derivation_signature"
    app_slug = str(app_spec.get("app_slug") or "").strip()
    policy_app_slug = str(policy_bundle.get("app_slug") or derivation.get("app_slug") or "").strip()
    if app_slug and policy_app_slug and app_slug != policy_app_slug:
        return "mismatch", "app_slug_mismatch"
    actual_signature = _app_spec_signature(app_spec)
    if actual_signature != expected_signature:
        return "mismatch", "app_spec_signature_mismatch"
    return "match", ""


def build_activation_payload(
    *,
    workspace_id: str,
    workspace_slug: str,
    artifact_id: str,
    artifact_slug: str,
    artifact_title: str,
    artifact_package_version: str,
    manifest: Dict[str, Any],
    runtime_instance_id: str = "",
    policy_bundle: Dict[str, Any] | None = None,
    policy_artifact_ref: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    content = manifest.get("content") if isinstance(manifest.get("content"), dict) else {}
    app_spec = content.get("app_spec") if isinstance(content.get("app_spec"), dict) else {}
    runtime_config = content.get("runtime_config") if isinstance(content.get("runtime_config"), dict) else {}
    app_slug = str(app_spec.get("app_slug") or "").strip()
    if not app_slug and artifact_slug.startswith("app."):
        app_slug = artifact_slug[4:].strip()
    if not app_slug:
        raise ArtifactActivationError("artifact is missing app identity (app_spec.app_slug or app.* slug)")
    if not app_spec:
        raise ArtifactActivationError("artifact is missing app_spec in manifest content")

    entities = _normalize_unique_strings(
        [str(item).strip() for item in (app_spec.get("entities") if isinstance(app_spec.get("entities"), list) else []) if str(item).strip()]
    )
    visuals = _normalize_unique_strings(
        [str(item).strip() for item in (app_spec.get("requested_visuals") if isinstance(app_spec.get("requested_visuals"), list) else []) if str(item).strip()]
    )
    phase_1_scope = _normalize_unique_strings(
        [str(item).strip() for item in (app_spec.get("phase_1_scope") if isinstance(app_spec.get("phase_1_scope"), list) else []) if str(item).strip()]
    )

    revision_anchor = {
        "anchor_type": "installed_generated_artifact",
        "workspace_id": str(workspace_id),
        "workspace_slug": str(workspace_slug),
        "artifact_id": str(artifact_id),
        "artifact_slug": str(artifact_slug),
        "artifact_version": str(artifact_package_version or ""),
        "app_slug": app_slug,
        "workspace_app_instance_id": str(runtime_instance_id or ""),
    }
    current_app_summary = {
        "app_slug": app_slug,
        "title": str(app_spec.get("title") or artifact_title or app_slug).strip() or app_slug,
        "entities": entities,
        "reports": _normalize_unique_strings(
            [str(item).strip() for item in (app_spec.get("reports") if isinstance(app_spec.get("reports"), list) else []) if str(item).strip()]
        ),
        "requires_primitives": _normalize_unique_strings(
            [
                str(item).strip()
                for item in (app_spec.get("requires_primitives") if isinstance(app_spec.get("requires_primitives"), list) else [])
                if str(item).strip()
            ]
        ),
    }
    latest_appspec_ref = {
        "artifact_slug": str(artifact_slug),
        "artifact_id": str(artifact_id),
        "artifact_version": str(artifact_package_version or ""),
        "source_build_job_id": str(runtime_config.get("source_job_id") or ""),
        "app_spec_artifact_id": str(runtime_config.get("app_spec_artifact_id") or ""),
    }

    source_policy_bundle = policy_bundle if isinstance(policy_bundle, dict) else {}
    source_policy_artifact_ref = policy_artifact_ref if isinstance(policy_artifact_ref, dict) else {}
    policy_source = "artifact" if source_policy_bundle else "reconstructed"
    policy_compatibility, policy_compatibility_reason = _policy_compatibility(
        app_spec=app_spec,
        policy_bundle=source_policy_bundle if source_policy_bundle else None,
    )

    content_json: Dict[str, Any] = {
        "raw_prompt": f"Activate existing generated app artifact {artifact_slug} in sibling runtime for validation.",
        "initial_intent": {
            "app_kind": "custom_app",
            "requested_entities": entities,
            "phase_1_scope": phase_1_scope,
            "requested_visuals": visuals,
            "workspace_scoped": True,
            "evolution_mode": "modify_installed_generated_app",
        },
        "revision_anchor": revision_anchor,
        "current_app_summary": current_app_summary,
        "current_app_spec": copy.deepcopy(app_spec),
        "latest_appspec_ref": latest_appspec_ref,
    }
    if source_policy_bundle:
        content_json["policy_bundle_override"] = copy.deepcopy(source_policy_bundle)
    if source_policy_artifact_ref:
        content_json["policy_artifact_ref"] = copy.deepcopy(source_policy_artifact_ref)
    content_json["policy_source"] = policy_source
    content_json["policy_compatibility"] = policy_compatibility
    content_json["policy_compatibility_reason"] = policy_compatibility_reason

    return {
        "app_slug": app_slug,
        "policy_source": policy_source,
        "policy_compatibility": policy_compatibility,
        "policy_compatibility_reason": policy_compatibility_reason,
        "policy_artifact_ref": copy.deepcopy(source_policy_artifact_ref) if source_policy_artifact_ref else {},
        "draft_payload": {
            "type": "app_intent",
            "title": str(artifact_title or current_app_summary["title"]).strip() or current_app_summary["title"],
            "status": "ready",
            "content_json": content_json,
        },
        "revision_anchor": revision_anchor,
    }


def submit_artifact_activation(
    *,
    workspace_slug: str,
    draft_payload: Dict[str, Any],
    seed_api_request: Callable[..., Any],
) -> Dict[str, str]:
    create_response = seed_api_request(
        method="POST",
        path="/api/v1/drafts",
        workspace_slug=workspace_slug,
        payload=draft_payload,
    )
    if int(create_response.status_code or 0) >= 300:
        raise ArtifactActivationError(
            f"failed to create activation draft (status={create_response.status_code}): {str(create_response.text or '')[:400]}"
        )
    try:
        create_payload = create_response.json() if create_response.content else {}
    except ValueError as exc:
        raise ArtifactActivationError("xyn-core returned invalid JSON while creating activation draft") from exc
    draft_id = str(create_payload.get("id") or "").strip()
    if not draft_id:
        raise ArtifactActivationError("xyn-core activation draft response missing id")

    submit_response = seed_api_request(
        method="POST",
        path=f"/api/v1/drafts/{draft_id}/submit",
        workspace_slug=workspace_slug,
        payload={},
    )
    if int(submit_response.status_code or 0) >= 300:
        raise ArtifactActivationError(
            f"failed to submit activation draft (status={submit_response.status_code}): {str(submit_response.text or '')[:400]}"
        )
    try:
        submit_payload = submit_response.json() if submit_response.content else {}
    except ValueError as exc:
        raise ArtifactActivationError("xyn-core returned invalid JSON while submitting activation draft") from exc
    return {
        "draft_id": draft_id,
        "job_id": str(submit_payload.get("job_id") or "").strip(),
    }


def runtime_record_matches_revision_anchor(
    *,
    runtime_record: Dict[str, Any] | None,
    revision_anchor: Dict[str, Any] | None,
) -> tuple[bool, str]:
    if not isinstance(runtime_record, dict):
        return False, "runtime_target_missing"
    if not isinstance(revision_anchor, dict):
        return False, "revision_anchor_missing"
    runtime_target = runtime_record.get("runtime_target") if isinstance(runtime_record.get("runtime_target"), dict) else {}
    runtime_instance = runtime_record.get("instance")
    anchor_artifact_slug = str(revision_anchor.get("artifact_slug") or "").strip()
    anchor_app_slug = str(revision_anchor.get("app_slug") or "").strip()
    anchor_instance_id = str(revision_anchor.get("workspace_app_instance_id") or "").strip()
    runtime_app_slug = str(runtime_target.get("app_slug") or "").strip()
    runtime_artifact_slug = str(runtime_target.get("installed_artifact_slug") or "").strip()
    runtime_instance_id = str(getattr(runtime_instance, "id", "") or "").strip()

    if not runtime_app_slug or runtime_app_slug != anchor_app_slug:
        return False, "runtime_app_slug_mismatch"
    # Require explicit artifact binding in runtime target so immediate reuse does
    # not drift from revision-anchor artifact identity.
    if not runtime_artifact_slug or runtime_artifact_slug != anchor_artifact_slug:
        return False, "runtime_artifact_slug_mismatch"
    if anchor_instance_id and runtime_instance_id and runtime_instance_id != anchor_instance_id:
        return False, "runtime_instance_mismatch"
    return True, "reused"


def _anchor_identity(anchor: Dict[str, Any] | None) -> Dict[str, str]:
    if not isinstance(anchor, dict):
        return {"workspace_id": "", "artifact_slug": "", "app_slug": "", "workspace_app_instance_id": ""}
    return {
        "workspace_id": str(anchor.get("workspace_id") or "").strip(),
        "artifact_slug": str(anchor.get("artifact_slug") or "").strip(),
        "app_slug": str(anchor.get("app_slug") or "").strip(),
        "workspace_app_instance_id": str(anchor.get("workspace_app_instance_id") or "").strip(),
    }


def _anchors_match(expected_anchor: Dict[str, Any] | None, candidate_anchor: Dict[str, Any] | None) -> bool:
    expected = _anchor_identity(expected_anchor)
    candidate = _anchor_identity(candidate_anchor)
    if not expected["workspace_id"] or not expected["artifact_slug"] or not expected["app_slug"]:
        return False
    if expected["workspace_id"] != candidate["workspace_id"]:
        return False
    if expected["artifact_slug"] != candidate["artifact_slug"]:
        return False
    if expected["app_slug"] != candidate["app_slug"]:
        return False
    if expected["workspace_app_instance_id"] and candidate["workspace_app_instance_id"]:
        return expected["workspace_app_instance_id"] == candidate["workspace_app_instance_id"]
    return True


def _job_revision_anchor(job_row: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(job_row, dict):
        return {}
    input_json = job_row.get("input_json") if isinstance(job_row.get("input_json"), dict) else {}
    app_spec = input_json.get("app_spec") if isinstance(input_json.get("app_spec"), dict) else {}
    if isinstance(app_spec.get("revision_anchor"), dict):
        return app_spec.get("revision_anchor")  # type: ignore[return-value]
    content = input_json.get("content_json") if isinstance(input_json.get("content_json"), dict) else {}
    if isinstance(content.get("revision_anchor"), dict):
        return content.get("revision_anchor")  # type: ignore[return-value]
    return {}


def find_inflight_activation(
    *,
    workspace_slug: str,
    revision_anchor: Dict[str, Any],
    seed_api_request: Callable[..., Any],
) -> Dict[str, str] | None:
    # Keep this narrow and artifact-first: detect queued/running jobs with the
    # same revision-anchor identity across the existing generation pipeline.
    candidate_specs = [
        ("generate_app_spec", "queued"),
        ("generate_app_spec", "running"),
        ("deploy_app_local", "queued"),
        ("deploy_app_local", "running"),
        ("provision_sibling_xyn", "queued"),
        ("provision_sibling_xyn", "running"),
        ("smoke_test", "queued"),
        ("smoke_test", "running"),
    ]
    for job_type, status in candidate_specs:
        response = seed_api_request(
            method="GET",
            path="/api/v1/jobs",
            workspace_slug=workspace_slug,
            payload=None,
            timeout=20,
            query={"type": job_type, "status": status, "limit": "200"},
        )
        if int(getattr(response, "status_code", 500) or 500) >= 300:
            continue
        try:
            rows = response.json() if response.content else []
        except ValueError:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate_anchor = _job_revision_anchor(row)
            if _anchors_match(revision_anchor, candidate_anchor):
                input_json = row.get("input_json") if isinstance(row.get("input_json"), dict) else {}
                return {
                    "job_id": str(row.get("id") or "").strip(),
                    "job_type": str(row.get("type") or "").strip(),
                    "job_status": str(row.get("status") or "").strip(),
                    "draft_id": str(input_json.get("draft_id") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "updated_at": str(row.get("updated_at") or "").strip(),
                }
    return None
