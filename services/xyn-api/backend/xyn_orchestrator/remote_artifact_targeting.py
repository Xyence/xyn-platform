from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .artifact_packages import import_package_blob_idempotent
from .models import Artifact, ArtifactPackage, ArtifactType, UserIdentity, Workspace
from .solution_bundles import SolutionBundleError, load_solution_bundle_from_source


REMOTE_SOURCE_REF_TYPE = "RemoteArtifactSource"
_DEFAULT_REMOTE_CATALOG_LIMIT = 50
_MAX_REMOTE_CATALOG_LIMIT = 200


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _source_key(source: str) -> str:
    token = str(source or "").strip()
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:16] if token else ""


def _source_value(source: Dict[str, Any], key: str) -> str:
    return str(source.get(key) or "").strip() if isinstance(source, dict) else ""


def _env_token(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _env_list(name: str) -> List[str]:
    raw = str(os.environ.get(name) or "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _resolve_s3_region() -> str:
    # Keep resolution deterministic and resilient: prefer explicit region envs.
    for key in (
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "XYN_RUNTIME_ARTIFACT_S3_REGION",
        "XYN_ARTIFACT_S3_REGION",
    ):
        value = _env_token(key)
        if value:
            return value
    # Fallback avoids malformed endpoint construction in environments that omit region.
    return "us-east-1"


def _resolve_s3_endpoint_url() -> str:
    for key in (
        "XYN_RUNTIME_ARTIFACT_S3_ENDPOINT_URL",
        "XYN_ARTIFACT_S3_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_S3",
    ):
        value = _env_token(key)
        if not value:
            continue
        # Guard against malformed endpoint forms like "https://s3..amazonaws.com".
        if "s3..amazonaws.com" in value.lower():
            continue
        return value
    return ""


def _s3_client() -> Any:
    kwargs: Dict[str, Any] = {
        "region_name": _resolve_s3_region(),
        "config": Config(retries={"max_attempts": 4, "mode": "standard"}),
    }
    endpoint_url = _resolve_s3_endpoint_url()
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def _parse_s3_source(source: str) -> Tuple[str, str]:
    token = str(source or "").strip()
    if not token.lower().startswith("s3://"):
        raise SolutionBundleError("source must start with s3://")
    without_scheme = token[5:]
    bucket, _, key = without_scheme.partition("/")
    bucket = bucket.strip()
    key = key.lstrip("/")
    if not bucket:
        raise SolutionBundleError("source must include s3://<bucket>/<key>")
    return bucket, key


def _candidate_summary_match(row: Dict[str, Any], query: str) -> bool:
    if not query:
        return True
    token = query.lower()
    text = " ".join(
        [
            str(row.get("artifact_slug") or ""),
            str(row.get("title") or ""),
            str(row.get("summary") or ""),
            str(_as_dict(row.get("remote_source")).get("solution_slug") or ""),
            str(_as_dict(row.get("remote_source")).get("solution_name") or ""),
        ]
    ).lower()
    return token in text


def _slugify_search_token(value: str) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    normalized = "".join(ch if ch.isalnum() else "-" for ch in token)
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-")


def _configured_remote_source_roots() -> List[str]:
    roots = _env_list("XYN_SOLUTION_BUNDLE_SOURCES")
    bootstrap_source = _env_token("XYN_BOOTSTRAP_SOLUTION_SOURCE").lower() or "local"
    if bootstrap_source == "s3":
        bucket = _env_token("XYN_BOOTSTRAP_SOLUTION_BUCKET")
        prefix = _env_token("XYN_BOOTSTRAP_SOLUTION_PREFIX").strip("/")
        if bucket:
            roots.append(f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}")
    # Preserve order while removing duplicates.
    seen: set[str] = set()
    out: List[str] = []
    for item in roots:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def configured_remote_catalog_sources() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for source in _configured_remote_source_roots():
        lowered = source.lower()
        source_type = "s3" if lowered.startswith("s3://") else ("file" if lowered.startswith("file://") else "path")
        bucket = ""
        prefix = ""
        if source_type == "s3":
            try:
                bucket, prefix = _parse_s3_source(source)
            except Exception:
                pass
        rows.append(
            {
                "source": source,
                "source_type": source_type,
                "bucket": bucket,
                "prefix": prefix,
                "region": _resolve_s3_region() if source_type == "s3" else "",
            }
        )
    return rows


def _manifest_search_tokens(*, query: str = "", artifact_slug: str = "") -> List[str]:
    tokens: List[str] = []
    for raw in (artifact_slug, query):
        value = str(raw or "").strip().lower()
        if not value:
            continue
        slugified = _slugify_search_token(value)
        if slugified:
            tokens.append(slugified)
        compact = "".join(ch for ch in value if ch.isalnum())
        if compact:
            tokens.append(compact)
    # Preserve order while de-duping.
    seen: set[str] = set()
    ordered: List[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _manifest_key_matches_tokens(key: str, *, tokens: List[str]) -> bool:
    if not tokens:
        return True
    lowered = str(key or "").lower()
    normalized = "".join(ch for ch in lowered if ch.isalnum())
    return any(token in lowered or token in normalized for token in tokens)


def _iter_manifest_sources_for_root(
    root: str,
    *,
    max_manifests: int = 500,
    query: str = "",
    artifact_slug: str = "",
) -> Iterable[str]:
    token = str(root or "").strip()
    if not token:
        return []
    lowered = token.lower()
    if lowered.startswith("s3://"):
        bucket, key = _parse_s3_source(token)
        if key.endswith(".json"):
            return [token]
        client = _s3_client()
        prefix = key.rstrip("/")
        candidates: List[str] = []
        kwargs: Dict[str, Any] = {"Bucket": bucket}
        if prefix:
            kwargs["Prefix"] = f"{prefix}/"
        paginator = client.get_paginator("list_objects_v2")
        tokens = _manifest_search_tokens(query=query, artifact_slug=artifact_slug)
        for page in paginator.paginate(**kwargs):
            for row in page.get("Contents", []):
                object_key = str(row.get("Key") or "")
                if not object_key:
                    continue
                if not (object_key.endswith("/manifest.json") or object_key.endswith(".manifest.json")):
                    continue
                if not _manifest_key_matches_tokens(object_key, tokens=tokens):
                    continue
                candidates.append(f"s3://{bucket}/{object_key}")
                if len(candidates) >= max_manifests:
                    return candidates
        return candidates
    path_token = token[7:] if lowered.startswith("file://") else token
    path = Path(path_token)
    if path.is_file():
        return [f"file://{path}"]
    if not path.exists() or not path.is_dir():
        return []
    manifests: List[str] = []
    for candidate in path.rglob("*.json"):
        if candidate.name not in {"manifest.json"} and not candidate.name.endswith(".manifest.json"):
            continue
        manifests.append(f"file://{candidate}")
        if len(manifests) >= max_manifests:
            break
    return manifests


def _fallback_manifest_sources_for_root(
    root: str,
    *,
    query: str = "",
    artifact_slug: str = "",
    max_probes: int = 24,
) -> List[str]:
    token = str(root or "").strip()
    if not token or not token.lower().startswith("s3://"):
        return []
    bucket, key = _parse_s3_source(token)
    prefix = key.strip().strip("/")
    slug_candidates: List[str] = []
    for raw in (artifact_slug, query):
        slug = _slugify_search_token(raw)
        if slug:
            slug_candidates.append(slug)
    # Keep order while de-duping.
    seen_slugs: set[str] = set()
    ordered_slugs: List[str] = []
    for slug in slug_candidates:
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        ordered_slugs.append(slug)
    if not ordered_slugs:
        return []

    probe_keys: List[str] = []
    for slug in ordered_slugs:
        for candidate in (
            f"{slug}.json",
            f"{slug}.manifest.json",
            f"{slug}/manifest.json",
        ):
            probe_keys.append(f"{prefix}/{candidate}" if prefix else candidate)
    # Trim to bounded probes for safety.
    probe_keys = probe_keys[:max_probes]

    client = _s3_client()
    resolved: List[str] = []
    for key_candidate in probe_keys:
        try:
            client.head_object(Bucket=bucket, Key=key_candidate)
        except ClientError:
            continue
        resolved.append(f"s3://{bucket}/{key_candidate}")
    return resolved


def search_remote_artifact_catalog(
    *,
    query: str = "",
    artifact_slug: str = "",
    artifact_type: str = "",
    source_root: str = "",
    limit: int = _DEFAULT_REMOTE_CATALOG_LIMIT,
    cursor: str = "",
) -> Dict[str, Any]:
    source_rows = configured_remote_catalog_sources()
    selected_roots = [source_root.strip()] if str(source_root or "").strip() else [row.get("source", "") for row in source_rows]
    selected_roots = [str(item).strip() for item in selected_roots if str(item).strip()]
    normalized_slug = str(artifact_slug or "").strip()
    normalized_type = str(artifact_type or "").strip()
    normalized_query = str(query or "").strip()
    try:
        normalized_limit = int(limit or _DEFAULT_REMOTE_CATALOG_LIMIT)
    except (TypeError, ValueError):
        normalized_limit = _DEFAULT_REMOTE_CATALOG_LIMIT
    bounded_limit = max(1, min(normalized_limit, _MAX_REMOTE_CATALOG_LIMIT))
    try:
        offset = max(int(str(cursor or "0").strip() or 0), 0)
    except ValueError:
        offset = 0

    discovered: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen: set[str] = set()
    for root in selected_roots:
        try:
            manifest_sources = list(
                _iter_manifest_sources_for_root(
                    root,
                    query=normalized_query,
                    artifact_slug=normalized_slug,
                )
            )
        except Exception as exc:
            errors.append(f"{root}: {str(exc)}")
            continue
        if not manifest_sources:
            # Some catalogs are authored as <slug>.json instead of nested manifest.json.
            # Probe deterministic slug-based candidates to keep discovery useful.
            try:
                manifest_sources = _fallback_manifest_sources_for_root(
                    root,
                    query=normalized_query,
                    artifact_slug=normalized_slug,
                )
            except Exception as exc:
                errors.append(f"{root}: {str(exc)}")
                continue
        for manifest_source in manifest_sources:
            try:
                candidates = list_remote_artifact_candidates(artifact_source={"manifest_source": manifest_source})
            except Exception as exc:
                errors.append(f"{manifest_source}: {str(exc)}")
                continue
            for row in candidates:
                if not isinstance(row, dict):
                    continue
                if normalized_slug and str(row.get("artifact_slug") or "") != normalized_slug:
                    continue
                if normalized_type and str(row.get("artifact_type") or "") != normalized_type:
                    continue
                if not _candidate_summary_match(row, normalized_query):
                    continue
                remote_source = _as_dict(row.get("remote_source"))
                key = "|".join(
                    [
                        str(row.get("artifact_slug") or ""),
                        str(row.get("artifact_type") or ""),
                        str(remote_source.get("manifest_source") or manifest_source),
                    ]
                )
                if key in seen:
                    continue
                seen.add(key)
                discovered.append(row)

    total = len(discovered)
    page = discovered[offset : offset + bounded_limit]
    next_cursor = str(offset + bounded_limit) if (offset + bounded_limit) < total else ""
    return {
        "candidates": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
        "source_roots": selected_roots,
        "errors": errors,
    }


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
        bucket, key = _parse_s3_source(token)
        if not key:
            raise SolutionBundleError("package_source must include s3://<bucket>/<key>")
        client = _s3_client()
        try:
            response = client.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            code = str((exc.response or {}).get("Error", {}).get("Code") or "").strip()
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise SolutionBundleError(f"s3 key not found: s3://{bucket}/{key}") from exc
            if code in {"NoSuchBucket"}:
                raise SolutionBundleError(f"s3 bucket not found: {bucket}") from exc
            raise SolutionBundleError(f"failed to fetch s3 package object: s3://{bucket}/{key}") from exc
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
