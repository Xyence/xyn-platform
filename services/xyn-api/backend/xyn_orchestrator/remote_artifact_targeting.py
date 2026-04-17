from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import boto3

from .artifact_packages import import_package_blob_idempotent
from .models import Artifact, ArtifactPackage, ArtifactType, UserIdentity, Workspace
from .solution_bundles import SolutionBundleError, load_solution_bundle_from_source


REMOTE_SOURCE_REF_TYPE = "RemoteArtifactSource"


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _source_key(source: str) -> str:
    token = str(source or "").strip()
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:16] if token else ""


def _source_value(source: Dict[str, Any], key: str) -> str:
    return str(source.get(key) or "").strip() if isinstance(source, dict) else ""


def _derive_owner_path_prefixes(row: Dict[str, Any]) -> List[str]:
    raw = row.get("owner_path_prefixes")
    if not isinstance(raw, list):
        raw = row.get("allowed_paths")
    return [str(item).strip() for item in (raw if isinstance(raw, list) else []) if str(item).strip()]


def _entry_candidates_from_bundle(bundle: Dict[str, Any], *, source_ref: str) -> List[Dict[str, Any]]:
    solution = _as_dict(bundle.get("solution"))
    solution_slug = str(solution.get("slug") or "").strip().lower()
    solution_name = str(solution.get("name") or solution_slug or "Remote Artifact").strip()
    artifacts = _as_dict(bundle.get("artifacts"))
    rows: List[tuple[str, Dict[str, Any]]] = []

    primary = _as_dict(artifacts.get("primary_app"))
    if primary:
        rows.append(("primary_app", primary))
    policy = _as_dict(artifacts.get("policy"))
    if policy:
        rows.append(("policy", policy))
    for item in _as_list(artifacts.get("supporting")):
        row = _as_dict(item)
        if row:
            rows.append(("supporting", row))

    candidates: List[Dict[str, Any]] = []
    for kind, row in rows:
        artifact_slug = str(row.get("slug") or "").strip()
        artifact_type = str(row.get("type") or "").strip() or "application"
        if not artifact_slug:
            continue
        title = str(row.get("title") or artifact_slug).strip() or artifact_slug
        version = str(row.get("version") or "").strip()
        package_source = str(row.get("package_source") or "").strip()
        package_ref = str(row.get("package_ref") or "").strip()
        source_ref_id = f"bundle:{_source_key(source_ref)}:{artifact_slug}:{artifact_type}"
        owner_repo_slug = str(row.get("owner_repo_slug") or row.get("repo_slug") or "").strip()
        owner_paths = _derive_owner_path_prefixes(row)
        candidates.append(
            {
                "artifact_slug": artifact_slug,
                "artifact_type": artifact_type,
                "title": title,
                "summary": str(row.get("responsibility_summary") or "").strip()
                or f"Remote {kind.replace('_', ' ')} candidate from {solution_name}.",
                "artifact_origin": "remote_catalog",
                "installed": False,
                "source_ref_type": REMOTE_SOURCE_REF_TYPE,
                "source_ref_id": source_ref_id,
                "remote_source": {
                    "manifest_source": source_ref,
                    "package_source": package_source,
                    "package_ref": package_ref,
                    "solution_slug": solution_slug,
                    "solution_name": solution_name,
                    "bundle_kind": kind,
                    "version": version,
                    "owner_repo_slug": owner_repo_slug,
                    "owner_path_prefixes": owner_paths,
                },
            }
        )
    return candidates


def _parse_package_source(source: str) -> ArtifactPackage:
    token = str(source or "").strip()
    lowered = token.lower()
    if lowered.startswith("package://") or lowered.startswith("package:"):
        package_id = token.split("://", 1)[1] if "://" in token else token.split(":", 1)[1]
        package = ArtifactPackage.objects.filter(id=package_id.strip()).first()
        if package is None:
            raise SolutionBundleError(f"artifact package not found: {package_id}")
        return package
    if lowered.startswith("s3://"):
        without_scheme = token[5:]
        bucket, _, key = without_scheme.partition("/")
        if not bucket or not key:
            raise SolutionBundleError("package_source must include s3://<bucket>/<key>")
        client = boto3.client("s3")
        response = client.get_object(Bucket=bucket, Key=key)
        blob = response["Body"].read() if response.get("Body") is not None else b""
        package, _ = import_package_blob_idempotent(blob=blob, created_by=None)
        return package
    file_path = token[7:] if lowered.startswith("file://") else token
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise SolutionBundleError(f"artifact package file not found: {path}")
    package, _ = import_package_blob_idempotent(blob=path.read_bytes(), created_by=None)
    return package


def _entry_candidates_from_package(package: ArtifactPackage, *, source_ref: str) -> List[Dict[str, Any]]:
    manifest = _as_dict(package.manifest)
    artifacts = [item for item in _as_list(manifest.get("artifacts")) if isinstance(item, dict)]
    candidates: List[Dict[str, Any]] = []
    for item in artifacts:
        artifact_slug = str(item.get("slug") or "").strip()
        artifact_type = str(item.get("type") or "").strip()
        if not artifact_slug or not artifact_type:
            continue
        source_ref_id = f"package:{_source_key(source_ref)}:{artifact_slug}:{artifact_type}"
        owner_repo_slug = str(item.get("owner_repo_slug") or item.get("repo_slug") or "").strip()
        owner_paths = _derive_owner_path_prefixes(item)
        candidates.append(
            {
                "artifact_slug": artifact_slug,
                "artifact_type": artifact_type,
                "title": str(item.get("title") or artifact_slug).strip() or artifact_slug,
                "summary": "Remote artifact candidate discovered from package manifest.",
                "artifact_origin": "remote_catalog",
                "installed": False,
                "source_ref_type": REMOTE_SOURCE_REF_TYPE,
                "source_ref_id": source_ref_id,
                "remote_source": {
                    "package_source": source_ref,
                    "package_id": str(package.id),
                    "version": str(item.get("version") or "").strip(),
                    "owner_repo_slug": owner_repo_slug,
                    "owner_path_prefixes": owner_paths,
                },
            }
        )
    return candidates


def list_remote_artifact_candidates(*, artifact_source: Dict[str, Any]) -> List[Dict[str, Any]]:
    source = _as_dict(artifact_source)
    manifest_source = _source_value(source, "manifest_source")
    package_source = _source_value(source, "package_source")
    if manifest_source:
        bundle = load_solution_bundle_from_source(manifest_source)
        return _entry_candidates_from_bundle(bundle, source_ref=manifest_source)
    if package_source:
        package = _parse_package_source(package_source)
        return _entry_candidates_from_package(package, source_ref=package_source)
    raise SolutionBundleError("artifact_source.manifest_source or artifact_source.package_source is required")


def resolve_remote_artifact_candidate(
    *,
    artifact_source: Dict[str, Any],
    artifact_slug: str = "",
    artifact_type: str = "",
) -> Dict[str, Any]:
    candidates = list_remote_artifact_candidates(artifact_source=artifact_source)
    slug_token = str(artifact_slug or _source_value(artifact_source, "artifact_slug") or "").strip()
    type_token = str(artifact_type or _source_value(artifact_source, "artifact_type") or "").strip()

    filtered = candidates
    if slug_token:
        filtered = [row for row in filtered if str(row.get("artifact_slug") or "") == slug_token]
    if type_token:
        filtered = [row for row in filtered if str(row.get("artifact_type") or "") == type_token]

    if not filtered:
        raise SolutionBundleError("remote artifact candidate not found for requested source/slug/type")
    if len(filtered) > 1:
        raise SolutionBundleError("remote artifact candidate is ambiguous; provide artifact_slug and artifact_type")
    return filtered[0]


def _artifact_type_for_slug(type_slug: str) -> ArtifactType:
    normalized = str(type_slug or "").strip().lower() or "application"
    artifact_type = ArtifactType.objects.filter(slug=normalized).first()
    if artifact_type is not None:
        return artifact_type
    label = " ".join(part.capitalize() for part in normalized.replace("_", "-").split("-") if part)
    return ArtifactType.objects.create(slug=normalized, name=label or "Application")


def upsert_remote_catalog_artifact(
    *,
    workspace: Workspace,
    candidate: Dict[str, Any],
    created_by: UserIdentity | None,
) -> Artifact:
    slug = str(candidate.get("artifact_slug") or "").strip()
    type_slug = str(candidate.get("artifact_type") or "").strip() or "application"
    source_ref_type = str(candidate.get("source_ref_type") or REMOTE_SOURCE_REF_TYPE).strip() or REMOTE_SOURCE_REF_TYPE
    source_ref_id = str(candidate.get("source_ref_id") or "").strip()
    if not slug:
        raise SolutionBundleError("remote artifact candidate missing artifact_slug")
    if not source_ref_id:
        source_ref_id = f"remote:{slug}:{type_slug}:{_source_key(json.dumps(_as_dict(candidate), sort_keys=True))}"

    artifact_type = _artifact_type_for_slug(type_slug)
    title = str(candidate.get("title") or slug).strip() or slug
    summary = str(candidate.get("summary") or "").strip()
    remote_source = _as_dict(candidate.get("remote_source"))

    owner_repo_slug = str(remote_source.get("owner_repo_slug") or "").strip()
    owner_path_prefixes = [
        str(item).strip() for item in (_as_list(remote_source.get("owner_path_prefixes"))) if str(item).strip()
    ]

    defaults = {
        "workspace": workspace,
        "type": artifact_type,
        "title": title,
        "summary": summary,
        "slug": slug,
        "artifact_state": "provisional",
        "status": "active",
        "author": created_by,
        "source_ref_type": source_ref_type,
        "source_ref_id": source_ref_id,
        "provenance_json": {
            "artifact_origin": "remote_catalog",
            "remote_source": remote_source,
        },
        "scope_json": {
            "scope_type": "artifact",
            "catalog_mode": "remote_catalog",
            "installed": False,
        },
        "owner_repo_slug": owner_repo_slug,
        "owner_path_prefixes_json": owner_path_prefixes,
        "edit_mode": "repo_backed" if owner_repo_slug and owner_path_prefixes else "read_only",
    }

    artifact = Artifact.objects.filter(source_ref_type=source_ref_type, source_ref_id=source_ref_id).first()
    if artifact is None:
        artifact = Artifact.objects.filter(workspace=workspace, type=artifact_type, slug=slug).first()

    if artifact is None:
        return Artifact.objects.create(**defaults)

    artifact.workspace = workspace
    artifact.type = artifact_type
    artifact.slug = slug
    artifact.title = title
    artifact.summary = summary
    artifact.source_ref_type = source_ref_type
    artifact.source_ref_id = source_ref_id
    artifact.status = "active"
    artifact.artifact_state = "provisional"
    artifact.author = artifact.author or created_by
    artifact.owner_repo_slug = owner_repo_slug
    artifact.owner_path_prefixes_json = owner_path_prefixes
    artifact.edit_mode = "repo_backed" if owner_repo_slug and owner_path_prefixes else "read_only"
    artifact.provenance_json = {
        "artifact_origin": "remote_catalog",
        "remote_source": remote_source,
    }
    artifact.scope_json = {
        "scope_type": "artifact",
        "catalog_mode": "remote_catalog",
        "installed": False,
    }
    artifact.save()
    return artifact
