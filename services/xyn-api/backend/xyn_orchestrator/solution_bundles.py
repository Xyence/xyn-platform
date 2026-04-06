from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from django.db import transaction

from .artifact_packages import import_package_blob_idempotent, install_package
from .models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    ArtifactInstallReceipt,
    ArtifactPackage,
    Workspace,
    WorkspaceArtifactBinding,
)

SOLUTION_BUNDLE_SCHEMA = "xyn.solution_bundle.v1"
ROLE_CHOICES = {choice[0] for choice in ApplicationArtifactMembership.ROLE_CHOICES}
logger = logging.getLogger(__name__)


class SolutionBundleError(RuntimeError):
    pass


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _bundle_error(message: str) -> SolutionBundleError:
    return SolutionBundleError(message)


def _normalize_artifact_entry(
    raw: Dict[str, Any],
    *,
    default_role: str,
    default_optional: bool,
    kind: str,
    require_version: bool = False,
) -> Dict[str, Any]:
    entry = _as_dict(raw)
    artifact_type = str(entry.get("type") or "").strip()
    slug = str(entry.get("slug") or "").strip()
    version = str(entry.get("version") or "").strip()
    if not artifact_type:
        raise _bundle_error(f"{kind}.type is required")
    if not slug:
        raise _bundle_error(f"{kind}.slug is required")
    if require_version and not version:
        raise _bundle_error(f"{kind}.version is required")
    role = str(entry.get("role") or default_role).strip() or default_role
    if role not in ROLE_CHOICES:
        raise _bundle_error(f"{kind}.role is invalid")
    return {
        "type": artifact_type,
        "slug": slug,
        "version": version,
        "role": role,
        "optional": bool(entry.get("optional", default_optional)),
        "package_source": str(entry.get("package_source") or "").strip(),
        "package_ref": str(entry.get("package_ref") or "").strip(),
        "responsibility_summary": str(entry.get("responsibility_summary") or "").strip(),
    }


def normalize_solution_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    payload = _as_dict(bundle)
    schema_version = str(payload.get("schema_version") or "").strip()
    if schema_version != SOLUTION_BUNDLE_SCHEMA:
        raise _bundle_error(f"schema_version must be {SOLUTION_BUNDLE_SCHEMA}")
    solution = _as_dict(payload.get("solution"))
    solution_slug = str(solution.get("slug") or "").strip().lower()
    solution_name = str(solution.get("name") or "").strip()
    if not solution_slug:
        raise _bundle_error("solution.slug is required")
    if not solution_name:
        raise _bundle_error("solution.name is required")

    artifacts = _as_dict(payload.get("artifacts"))
    primary_app = _normalize_artifact_entry(
        _as_dict(artifacts.get("primary_app")),
        default_role="primary_ui",
        default_optional=False,
        kind="artifacts.primary_app",
        require_version=True,
    )
    if primary_app["type"] != "application":
        raise _bundle_error("artifacts.primary_app.type must be application")
    policy = _as_dict(artifacts.get("policy"))
    policy_entry: Optional[Dict[str, Any]] = None
    if policy:
        policy_entry = _normalize_artifact_entry(
            policy,
            default_role="supporting",
            default_optional=True,
            kind="artifacts.policy",
            require_version=True,
        )
        if policy_entry["type"] != "policy_bundle":
            raise _bundle_error("artifacts.policy.type must be policy_bundle")

    supporting_rows: List[Dict[str, Any]] = []
    for idx, row in enumerate(_as_list(artifacts.get("supporting"))):
        supporting_rows.append(
            _normalize_artifact_entry(
                _as_dict(row),
                default_role="supporting",
                default_optional=True,
                kind=f"artifacts.supporting[{idx}]",
            )
        )

    bootstrap = _as_dict(payload.get("bootstrap"))
    return {
        "schema_version": SOLUTION_BUNDLE_SCHEMA,
        "solution": {
            "slug": solution_slug,
            "name": solution_name,
            "description": str(solution.get("description") or "").strip(),
        },
        "artifacts": {
            "primary_app": primary_app,
            "policy": policy_entry,
            "supporting": supporting_rows,
        },
        "bootstrap": {
            "bind_workspace_artifacts": bool(bootstrap.get("bind_workspace_artifacts", True)),
            "enable_bindings": bool(bootstrap.get("enable_bindings", True)),
            "application_status": str(bootstrap.get("application_status") or "active").strip() or "active",
            "source_factory_key": str(bootstrap.get("source_factory_key") or "solution_bundle_install").strip()
            or "solution_bundle_install",
            "metadata": _as_dict(bootstrap.get("metadata")),
        },
    }


def _is_uri(token: str) -> bool:
    return "://" in str(token or "")


def _parse_s3_source(source: str) -> Tuple[str, str]:
    parsed = urlparse(source)
    bucket = str(parsed.netloc or "").strip()
    key = str(parsed.path or "").lstrip("/")
    if not bucket:
        raise _bundle_error("missing S3 bucket in source")
    if not key:
        raise _bundle_error("missing S3 key in source")
    return bucket, key


def _s3_read_bytes(*, bucket: str, key: str) -> bytes:
    try:
        client = boto3.client("s3")
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str((exc.response or {}).get("Error", {}).get("Code") or "").strip()
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise _bundle_error(f"s3 key not found: s3://{bucket}/{key}") from exc
        if code in {"NoSuchBucket"}:
            raise _bundle_error(f"s3 bucket not found: {bucket}") from exc
        raise _bundle_error(f"failed to fetch s3 object: s3://{bucket}/{key}") from exc
    body = response.get("Body")
    return body.read() if body is not None else b""


def _read_s3_json(source: str) -> Dict[str, Any]:
    bucket, key = _parse_s3_source(source)
    blob = _s3_read_bytes(bucket=bucket, key=key)
    try:
        return _as_dict(json.loads(blob.decode("utf-8")))
    except Exception as exc:
        raise _bundle_error(f"malformed bundle manifest JSON: s3://{bucket}/{key}") from exc


def _read_file_json(source: str) -> Dict[str, Any]:
    token = str(source or "").strip()
    if token.startswith("file://"):
        token = token[7:]
    path = Path(token)
    if not path.exists():
        raise _bundle_error(f"bundle file not found: {path}")
    try:
        return _as_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise _bundle_error(f"malformed bundle manifest JSON: {path}") from exc


def _derived_bundle_from_package_manifest(package: ArtifactPackage) -> Dict[str, Any]:
    manifest = package.manifest if isinstance(package.manifest, dict) else {}
    solution_bundle = _as_dict(manifest.get("solution_bundle"))
    if solution_bundle:
        return solution_bundle
    artifacts = _as_list(manifest.get("artifacts"))
    app_row = next(
        (
            row
            for row in artifacts
            if isinstance(row, dict)
            and str(row.get("type") or "").strip() == "application"
            and str(row.get("slug") or "").strip().startswith("app.")
        ),
        None,
    )
    if not isinstance(app_row, dict):
        raise _bundle_error("package manifest does not include solution_bundle and no app.* application artifact exists")
    app_slug = str(app_row.get("slug") or "").strip()
    solution_key = app_slug[4:] if app_slug.startswith("app.") else app_slug
    policy_row = next(
        (
            row
            for row in artifacts
            if isinstance(row, dict)
            and str(row.get("type") or "").strip() == "policy_bundle"
            and str(row.get("slug") or "").strip() == f"policy.{solution_key}"
        ),
        None,
    )
    words = [chunk for chunk in solution_key.replace("-", " ").replace("_", " ").split(" ") if chunk]
    title = " ".join(word[:1].upper() + word[1:] for word in words) or solution_key
    bundle: Dict[str, Any] = {
        "schema_version": SOLUTION_BUNDLE_SCHEMA,
        "solution": {
            "slug": solution_key,
            "name": title,
            "description": "",
        },
        "artifacts": {
            "primary_app": {
                "type": "application",
                "slug": app_slug,
                "version": str(app_row.get("version") or "").strip(),
                "role": "primary_ui",
                "package_source": f"package://{package.id}",
            },
            "supporting": [],
        },
        "bootstrap": {},
    }
    if isinstance(policy_row, dict):
        bundle["artifacts"]["policy"] = {
            "type": "policy_bundle",
            "slug": str(policy_row.get("slug") or "").strip(),
            "version": str(policy_row.get("version") or "").strip(),
            "role": "supporting",
            "optional": True,
            "package_source": f"package://{package.id}",
        }
    return bundle


def _resolve_bundle_source_with_candidates(source: str) -> str:
    token = str(source or "").strip()
    if not token:
        raise _bundle_error("bundle source is required")
    lowered = token.lower()
    if lowered.startswith("s3://"):
        bucket, key = _parse_s3_source(token)
        if key.endswith(".json"):
            _s3_read_bytes(bucket=bucket, key=key)
            return token
        candidates = [f"{key.rstrip('/')}/manifest.json", f"{key.rstrip('/')}.json"]
        for candidate in candidates:
            try:
                _s3_read_bytes(bucket=bucket, key=candidate)
                return f"s3://{bucket}/{candidate}"
            except SolutionBundleError:
                continue
        raise _bundle_error(f"s3 bundle manifest not found under source: s3://{bucket}/{key}")
    if lowered.startswith("file://"):
        token = token[7:]
    path = Path(token)
    if path.is_file():
        return f"file://{path}"
    if path.is_dir():
        candidates = [path / "manifest.json", path.with_suffix(".json")]
        for candidate in candidates:
            if candidate.exists():
                return f"file://{candidate}"
        raise _bundle_error(f"bundle manifest not found under directory: {path}")
    if path.with_suffix(".json").exists():
        return f"file://{path.with_suffix('.json')}"
    raise _bundle_error(f"bundle source path not found: {path}")


def _resolve_relative_source(base_source: str, relative: str) -> str:
    rel = str(relative or "").strip()
    if not rel:
        return ""
    if _is_uri(rel) or rel.startswith("/") or rel.startswith("."):
        return rel
    base = str(base_source or "").strip()
    if base.lower().startswith("s3://"):
        bucket, key = _parse_s3_source(base)
        prefix = "/".join(key.split("/")[:-1]).strip("/")
        if prefix:
            return f"s3://{bucket}/{prefix}/{rel.lstrip('/')}"
        return f"s3://{bucket}/{rel.lstrip('/')}"
    if base.lower().startswith("file://"):
        base = base[7:]
    parent = Path(base).parent
    return str(parent / rel)


def _apply_bundle_package_sources(raw_bundle: Dict[str, Any], *, base_source: str) -> Dict[str, Any]:
    payload = _as_dict(raw_bundle)
    mapping = _as_dict(payload.get("package_payloads"))
    artifacts = _as_dict(payload.get("artifacts"))

    def _entry_with_resolved_source(entry: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(_as_dict(entry))
        package_source = str(row.get("package_source") or "").strip()
        if not package_source:
            package_ref = str(row.get("package_ref") or "").strip()
            if package_ref:
                package_source = str(mapping.get(package_ref) or "").strip()
        if package_source:
            row["package_source"] = _resolve_relative_source(base_source, package_source)
        return row

    if isinstance(artifacts.get("primary_app"), dict):
        artifacts["primary_app"] = _entry_with_resolved_source(_as_dict(artifacts.get("primary_app")))
    if isinstance(artifacts.get("policy"), dict):
        artifacts["policy"] = _entry_with_resolved_source(_as_dict(artifacts.get("policy")))
    supporting = []
    for row in _as_list(artifacts.get("supporting")):
        supporting.append(_entry_with_resolved_source(_as_dict(row)))
    artifacts["supporting"] = supporting
    payload["artifacts"] = artifacts
    return payload


def load_solution_bundle_from_source(source: str) -> Dict[str, Any]:
    token = str(source or "").strip()
    if not token:
        raise _bundle_error("bundle source is required")
    lowered = token.lower()
    if lowered.startswith("package://") or lowered.startswith("package:"):
        package_id = token.split("://", 1)[1] if "://" in token else token.split(":", 1)[1]
        package = ArtifactPackage.objects.filter(id=package_id.strip()).first()
        if package is None:
            raise _bundle_error(f"artifact package not found: {package_id}")
        return normalize_solution_bundle(_derived_bundle_from_package_manifest(package))
    resolved = _resolve_bundle_source_with_candidates(token)
    if resolved.lower().startswith("s3://"):
        raw_bundle = _read_s3_json(resolved)
    else:
        raw_bundle = _read_file_json(resolved)
    return normalize_solution_bundle(_apply_bundle_package_sources(raw_bundle, base_source=resolved))


def _load_package_from_source(source: str) -> ArtifactPackage:
    token = str(source or "").strip()
    lowered = token.lower()
    if lowered.startswith("package://") or lowered.startswith("package:"):
        package_id = token.split("://", 1)[1] if "://" in token else token.split(":", 1)[1]
        package = ArtifactPackage.objects.filter(id=package_id.strip()).first()
        if package is None:
            raise _bundle_error(f"artifact package not found: {package_id}")
        return package
    if lowered.startswith("s3://"):
        bucket, key = _parse_s3_source(token)
        blob = _s3_read_bytes(bucket=bucket, key=key)
        package, _created = import_package_blob_idempotent(blob=blob, created_by=None)
        return package
    token_path = token[7:] if lowered.startswith("file://") else token
    path = Path(token_path)
    if not path.exists():
        raise _bundle_error(f"artifact package file not found: {path}")
    package, _created = import_package_blob_idempotent(blob=path.read_bytes(), created_by=None)
    return package


def _artifact_for_ref(workspace: Workspace, ref: Dict[str, Any]) -> Optional[Artifact]:
    qs = Artifact.objects.filter(
        workspace=workspace,
        type__slug=str(ref.get("type") or "").strip(),
        slug=str(ref.get("slug") or "").strip(),
    ).select_related("type")
    version = str(ref.get("version") or "").strip()
    if version:
        qs = qs.filter(package_version=version)
    return qs.order_by("-updated_at", "-created_at").first()


def _ensure_artifact_available(
    *,
    workspace: Workspace,
    ref: Dict[str, Any],
    installed_by: Any = None,
) -> Tuple[Optional[Artifact], Optional[ArtifactInstallReceipt]]:
    artifact = _artifact_for_ref(workspace, ref)
    if artifact is not None:
        return artifact, None
    package_source = str(ref.get("package_source") or "").strip()
    if not package_source:
        return None, None
    package = _load_package_from_source(package_source)
    receipt = install_package(
        package,
        binding_overrides={},
        installed_by=installed_by,
        target_workspace=workspace,
    )
    if receipt.status != "success":
        raise _bundle_error(f"package install failed for {ref.get('type')}:{ref.get('slug')}: {receipt.error_summary}")
    return _artifact_for_ref(workspace, ref), receipt


def _application_for_bundle(
    workspace: Workspace,
    bundle: Dict[str, Any],
    *,
    install_source: str = "",
) -> Tuple[Application, bool]:
    solution = _as_dict(bundle.get("solution"))
    solution_slug = str(solution.get("slug") or "").strip().lower()
    app = (
        Application.objects.filter(workspace=workspace, metadata_json__solution_bundle_slug=solution_slug)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if app is None:
        app = (
            Application.objects.filter(workspace=workspace, metadata_json__generated_artifact_key=solution_slug)
            .order_by("-updated_at", "-created_at")
            .first()
        )
    bootstrap = _as_dict(bundle.get("bootstrap"))
    created = False
    if app is None:
        created = True
        app = Application.objects.create(
            workspace=workspace,
            name=str(solution.get("name") or solution_slug),
            summary=str(solution.get("description") or ""),
            source_factory_key=str(bootstrap.get("source_factory_key") or "solution_bundle_install"),
            source_conversation_id="",
            status=str(bootstrap.get("application_status") or "active"),
            request_objective="",
            metadata_json={},
        )
    metadata = _as_dict(app.metadata_json)
    metadata.update(
        {
            "solution_bundle_slug": solution_slug,
            "solution_bundle_name": str(solution.get("name") or ""),
            "solution_bundle_schema": SOLUTION_BUNDLE_SCHEMA,
        }
    )
    normalized_install_source = str(install_source or "").strip()
    if normalized_install_source:
        metadata["solution_bundle_install_source"] = normalized_install_source
    extra = _as_dict(bootstrap.get("metadata"))
    if extra:
        metadata["solution_bundle_bootstrap"] = extra
    update_fields: List[str] = []
    desired_name = str(solution.get("name") or "").strip()
    if desired_name and app.name != desired_name:
        app.name = desired_name
        update_fields.append("name")
    desired_summary = str(solution.get("description") or "").strip()
    if app.summary != desired_summary:
        app.summary = desired_summary
        update_fields.append("summary")
    desired_status = str(bootstrap.get("application_status") or "active").strip() or "active"
    if app.status != desired_status:
        app.status = desired_status
        update_fields.append("status")
    app.metadata_json = metadata
    update_fields.extend(["metadata_json", "updated_at"])
    app.save(update_fields=list(dict.fromkeys(update_fields)))
    return app, created


def install_solution_bundle(
    *,
    workspace: Workspace,
    bundle: Dict[str, Any],
    install_source: str = "",
    installed_by: Any = None,
) -> Dict[str, Any]:
    normalized = normalize_solution_bundle(bundle)
    with transaction.atomic():
        normalized_install_source = str(install_source or "").strip()
        application, application_created = _application_for_bundle(
            workspace,
            normalized,
            install_source=normalized_install_source,
        )
        artifact_entries: List[Tuple[str, Dict[str, Any], int]] = []
        artifacts = _as_dict(normalized.get("artifacts"))
        primary_ref = _as_dict(artifacts.get("primary_app"))
        artifact_entries.append(("primary_app", primary_ref, 10))
        policy_ref = artifacts.get("policy")
        if isinstance(policy_ref, dict):
            artifact_entries.append(("policy", policy_ref, 20))
        for idx, row in enumerate(_as_list(artifacts.get("supporting"))):
            artifact_entries.append((f"supporting[{idx}]", _as_dict(row), 30 + idx))

        warnings: List[str] = []
        policy_source = "reconstructed"
        membership_rows: List[ApplicationArtifactMembership] = []
        binding_rows: List[WorkspaceArtifactBinding] = []
        receipts: List[ArtifactInstallReceipt] = []
        bootstrap = _as_dict(normalized.get("bootstrap"))
        bind_workspace_artifacts = bool(bootstrap.get("bind_workspace_artifacts", True))
        enable_bindings = bool(bootstrap.get("enable_bindings", True))

        for kind, ref, sort_order in artifact_entries:
            artifact, receipt = _ensure_artifact_available(
                workspace=workspace,
                ref=ref,
                installed_by=installed_by,
            )
            if receipt is not None:
                receipts.append(receipt)
            if artifact is None:
                if bool(ref.get("optional")):
                    warnings.append(f"{kind} artifact not available; continuing with compatibility fallback")
                    continue
                raise _bundle_error(f"{kind} artifact missing and no install source available: {ref.get('type')}:{ref.get('slug')}")
            if kind == "policy":
                policy_source = "artifact"
            default_summary = str(ref.get("responsibility_summary") or "").strip()
            if not default_summary:
                if kind == "primary_app":
                    default_summary = "Primary application artifact from solution bundle."
                elif kind == "policy":
                    default_summary = "Policy artifact pinned by solution bundle."
                else:
                    default_summary = "Supporting artifact from solution bundle."
            membership, _created = ApplicationArtifactMembership.objects.update_or_create(
                application=application,
                artifact=artifact,
                defaults={
                    "workspace": workspace,
                    "role": str(ref.get("role") or "supporting"),
                    "responsibility_summary": default_summary,
                    "metadata_json": {
                        "origin": "solution_bundle_install",
                        "bundle_kind": kind,
                    },
                    "sort_order": sort_order,
                },
            )
            membership_rows.append(membership)
            if bind_workspace_artifacts:
                binding, _binding_created = WorkspaceArtifactBinding.objects.update_or_create(
                    workspace=workspace,
                    artifact=artifact,
                    defaults={
                        "enabled": enable_bindings,
                        "installed_state": "installed",
                    },
                )
                binding_rows.append(binding)

        return {
            "bundle": normalized,
            "application": application,
            "application_created": application_created,
            "memberships": membership_rows,
            "workspace_bindings": binding_rows,
            "receipts": receipts,
            "policy_source": policy_source,
            "install_source": normalized_install_source,
            "warnings": warnings,
        }


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _env_solution_slugs() -> List[str]:
    raw = str(os.environ.get("XYN_BOOTSTRAP_INSTALL_SOLUTIONS") or "").strip()
    if not raw:
        return []
    rows = [chunk.strip().lower() for chunk in raw.split(",")]
    deduped: List[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row or row in seen:
            continue
        seen.add(row)
        deduped.append(row)
    return deduped


def _bootstrap_workspace_slug() -> str:
    raw = str(
        os.environ.get("XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG")
        or os.environ.get("XYN_WORKSPACE_SLUG")
        or "development"
    ).strip().lower()
    token = raw.replace("_", "-")
    token = "-".join(chunk for chunk in token.split("-") if chunk)
    return token or "development"


def _workspace_title_from_slug(slug: str) -> str:
    value = str(slug or "").strip().replace("-", " ")
    return value.title() if value else "Development"


def _bootstrap_workspace() -> Workspace:
    slug = _bootstrap_workspace_slug()
    workspace = Workspace.objects.filter(slug=slug).first()
    if workspace is not None:
        return workspace
    return Workspace.objects.create(
        slug=slug,
        name=_workspace_title_from_slug(slug),
        description=f"Default {slug} workspace for bootstrap solution bundle install.",
        metadata_json={"bootstrap": "solution_bundle_install"},
    )


def _bundle_source_for_slug(solution_slug: str) -> str:
    source_type = str(os.environ.get("XYN_BOOTSTRAP_SOLUTION_SOURCE") or "local").strip().lower() or "local"
    prefix = str(os.environ.get("XYN_BOOTSTRAP_SOLUTION_PREFIX") or "").strip()
    version = str(os.environ.get("XYN_BOOTSTRAP_SOLUTION_VERSION") or "").strip()
    if source_type == "local":
        if not prefix:
            raise _bundle_error("XYN_BOOTSTRAP_SOLUTION_PREFIX is required when XYN_BOOTSTRAP_SOLUTION_SOURCE=local")
        base = prefix[7:] if prefix.startswith("file://") else prefix
        if version:
            return str(Path(base) / solution_slug / version)
        return str(Path(base) / solution_slug)
    if source_type == "s3":
        bucket = str(os.environ.get("XYN_BOOTSTRAP_SOLUTION_BUCKET") or "").strip()
        if not bucket:
            raise _bundle_error("XYN_BOOTSTRAP_SOLUTION_BUCKET is required when XYN_BOOTSTRAP_SOLUTION_SOURCE=s3")
        clean_prefix = prefix.strip().strip("/")
        segments = [segment for segment in [clean_prefix, solution_slug, version] if segment]
        key = "/".join(segments) if segments else solution_slug
        return f"s3://{bucket}/{key}"
    raise _bundle_error(f"unsupported XYN_BOOTSTRAP_SOLUTION_SOURCE: {source_type}")


def _application_exists_for_solution(*, workspace: Workspace, solution_slug: str) -> bool:
    return Application.objects.filter(
        workspace=workspace,
        metadata_json__solution_bundle_slug=solution_slug,
    ).exists() or Application.objects.filter(
        workspace=workspace,
        metadata_json__generated_artifact_key=solution_slug,
    ).exists()


def bootstrap_install_solution_bundles_from_env(*, reason: str = "startup") -> Dict[str, Any]:
    slugs = _env_solution_slugs()
    if not slugs:
        return {"enabled": False, "reason": "no_solution_slugs", "results": []}
    workspace = _bootstrap_workspace()
    missing_only = _env_bool("XYN_BOOTSTRAP_IF_MISSING_ONLY", True)
    results: List[Dict[str, Any]] = []
    for solution_slug in slugs:
        row: Dict[str, Any] = {"solution_slug": solution_slug, "workspace_slug": workspace.slug}
        exists = _application_exists_for_solution(workspace=workspace, solution_slug=solution_slug)
        if missing_only and exists:
            row["status"] = "skipped"
            row["reason"] = "present"
            logger.info(
                "Solution bundle bootstrap skipped (%s): solution=%s workspace=%s reason=present",
                reason,
                solution_slug,
                workspace.slug,
            )
            results.append(row)
            continue
        try:
            source = _bundle_source_for_slug(solution_slug)
            bundle = load_solution_bundle_from_source(source)
            install_result = install_solution_bundle(
                workspace=workspace,
                bundle=bundle,
                install_source=source,
                installed_by=None,
            )
            app = install_result.get("application")
            memberships = install_result.get("memberships") if isinstance(install_result.get("memberships"), list) else []
            artifact_versions = []
            for member in memberships:
                artifact = getattr(member, "artifact", None)
                if artifact is None:
                    continue
                artifact_versions.append(f"{artifact.slug}@{str(artifact.package_version or '')}")
            row.update(
                {
                    "status": "installed" if bool(install_result.get("application_created")) else "updated",
                    "source": source,
                    "application_id": str(getattr(app, "id", "") or ""),
                    "policy_source": str(install_result.get("policy_source") or "reconstructed"),
                    "install_source": str(install_result.get("install_source") or source),
                    "artifact_revisions": artifact_versions,
                    "warnings": [str(item) for item in (install_result.get("warnings") or []) if str(item).strip()],
                }
            )
            logger.info(
                "Solution bundle bootstrap %s (%s): solution=%s workspace=%s policy_source=%s install_source=%s artifacts=%s",
                row["status"],
                reason,
                solution_slug,
                workspace.slug,
                row["policy_source"],
                row["install_source"],
                ", ".join(artifact_versions) if artifact_versions else "none",
            )
        except Exception as exc:
            row.update({"status": "failed", "error": str(exc)})
            logger.warning(
                "Solution bundle bootstrap failed (%s): solution=%s workspace=%s error=%s",
                reason,
                solution_slug,
                workspace.slug,
                exc,
            )
        results.append(row)
    return {
        "enabled": True,
        "reason": reason,
        "workspace_id": str(workspace.id),
        "workspace_slug": workspace.slug,
        "if_missing_only": missing_only,
        "results": results,
    }
