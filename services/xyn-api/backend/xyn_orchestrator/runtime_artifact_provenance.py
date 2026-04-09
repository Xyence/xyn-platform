from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, Tuple


DEFAULT_REPO_URLS: Dict[str, str] = {
    "xyn-platform": "https://github.com/Xyence/xyn-platform",
    "xyn": "https://github.com/Xyence/xyn",
}

RUNTIME_PROVENANCE_HINTS: Dict[str, Dict[str, str]] = {
    "xyn-api": {"repo_key": "xyn-platform", "monorepo_subpath": "services/xyn-api"},
    "xyn-ui": {"repo_key": "xyn-platform", "monorepo_subpath": "apps/xyn-ui"},
    "core.workbench": {"repo_key": "xyn-platform", "monorepo_subpath": "apps/xyn-ui"},
    "core.xyn-runtime": {"repo_key": "xyn", "monorepo_subpath": "core"},
}

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")


def build_runtime_artifact_git_provenance(
    *,
    slug: str,
    manifest_ref: str = "",
    existing_provenance: Any = None,
) -> Dict[str, str]:
    token = str(slug or "").strip().lower()
    hint = RUNTIME_PROVENANCE_HINTS.get(token)
    if not hint:
        return {}
    existing = dict(existing_provenance) if isinstance(existing_provenance, dict) else {}
    source = existing.get("source") if isinstance(existing.get("source"), dict) else {}

    repo_key = str(hint.get("repo_key") or source.get("repo_key") or existing.get("repo_key") or "").strip()
    if not repo_key:
        return {}

    repo_url = str(
        source.get("repo_url")
        or existing.get("repo_url")
        or os.getenv(f"XYN_RUNTIME_REPO_URL_{repo_key.upper().replace('-', '_')}", "")
        or DEFAULT_REPO_URLS.get(repo_key)
        or ""
    ).strip()
    branch_hint = str(
        source.get("branch_hint")
        or existing.get("branch_hint")
        or os.getenv("XYN_RUNTIME_SOURCE_BRANCH_HINT", "")
        or "develop"
    ).strip()
    monorepo_subpath = str(
        source.get("monorepo_subpath")
        or existing.get("monorepo_subpath")
        or hint.get("monorepo_subpath")
        or ""
    ).strip()
    manifest = str(
        source.get("manifest_ref")
        or existing.get("manifest_ref")
        or manifest_ref
        or ""
    ).strip()

    commit_sha = str(
        source.get("commit_sha")
        or existing.get("commit_sha")
        or _commit_from_env(repo_key=repo_key, slug=token)
        or ""
    ).strip().lower()
    if commit_sha and not _COMMIT_RE.match(commit_sha):
        commit_sha = ""

    payload = {
        "kind": "git",
        "repo_key": repo_key,
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "branch_hint": branch_hint,
        "monorepo_subpath": monorepo_subpath,
        "manifest_ref": manifest,
    }
    return {key: value for key, value in payload.items() if str(value or "").strip()}


def merge_runtime_provenance(existing: Any, canonical_git: Dict[str, str]) -> Dict[str, Any]:
    merged = dict(existing) if isinstance(existing, dict) else {}
    if not canonical_git:
        return merged
    source = merged.get("source") if isinstance(merged.get("source"), dict) else {}
    for key, value in canonical_git.items():
        if not str(value or "").strip():
            continue
        merged[key] = value
        source[key] = value
    if source:
        merged["source"] = source
    merged.setdefault("source_system", "seed-kernel")
    return merged


def runtime_git_source_ref(canonical_git: Dict[str, str]) -> Tuple[str, str]:
    if str(canonical_git.get("kind") or "").strip().lower() != "git":
        return "", ""
    repo_identity = str(canonical_git.get("repo_key") or canonical_git.get("repo_url") or "").strip()
    if not repo_identity:
        return "", ""
    suffix = str(canonical_git.get("monorepo_subpath") or canonical_git.get("manifest_ref") or "").strip()
    commit = str(canonical_git.get("commit_sha") or "").strip().lower()
    if commit:
        commit = commit[:12]
    source_ref_id = "|".join([part for part in [repo_identity, suffix, commit] if part])
    if len(source_ref_id) > 120:
        digest = hashlib.sha1(source_ref_id.encode("utf-8")).hexdigest()[:12]
        head = source_ref_id[: 120 - len(digest) - 1]
        source_ref_id = f"{head}:{digest}"
    return "GitSource", source_ref_id


def _commit_from_env(*, repo_key: str, slug: str) -> str:
    explicit = str(os.getenv("XYN_RUNTIME_SOURCE_COMMIT_SHA", "")).strip()
    if explicit:
        return explicit
    by_repo = str(os.getenv(f"XYN_RUNTIME_SOURCE_COMMIT_SHA_{repo_key.upper().replace('-', '_')}", "")).strip()
    if by_repo:
        return by_repo
    image_tokens = []
    if slug == "xyn-api":
        image_tokens.append(str(os.getenv("XYN_API_IMAGE", "")).strip())
    if slug == "xyn-ui":
        image_tokens.append(str(os.getenv("XYN_UI_IMAGE", "")).strip())
    for image_ref in image_tokens:
        commit = _commit_from_image_ref(image_ref)
        if commit:
            return commit
    return ""


def _commit_from_image_ref(image_ref: str) -> str:
    token = str(image_ref or "").strip()
    if not token or ":" not in token:
        return ""
    tag = token.rsplit(":", 1)[-1].strip().lower()
    if _COMMIT_RE.match(tag):
        return tag
    return ""
