from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .ai_runtime import AiConfigError, resolve_ai_config
from .managed_repositories import ManagedRepositoryError, validate_managed_repository_registration
from .managed_storage import managed_artifact_root, managed_workspace_root
from .models import AgentDefinition, ProviderCredential, ManagedRepository


def _check_writable_directory(path: Path) -> Dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "message": f"{path} could not be created: {exc}"}
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".xyn-ready-", delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
    except OSError as exc:
        return {"ok": False, "message": f"{path} is not writable: {exc}"}
    return {"ok": True, "message": f"{path} is writable"}


def _status(ok: bool, *, missing: bool = False) -> str:
    if ok:
        return "ok"
    return "missing" if missing else "error"


def _ai_provider_check() -> Dict[str, Any]:
    enabled_credentials = ProviderCredential.objects.filter(enabled=True).count()
    return {
        "component": "ai_providers",
        "status": _status(enabled_credentials > 0, missing=enabled_credentials == 0),
        "message": (
            f"{enabled_credentials} enabled AI provider credential(s) configured."
            if enabled_credentials > 0
            else "No enabled AI provider credentials are configured."
        ),
        "details": {"enabled_credentials": enabled_credentials},
    }


def _agent_purpose_check(purpose_slug: str) -> Dict[str, Any]:
    count = AgentDefinition.objects.filter(enabled=True, purposes__slug=purpose_slug).distinct().count()
    if count <= 0:
        return {
            "component": f"{purpose_slug}_agents",
            "status": "missing",
            "message": f"No enabled {purpose_slug} agents are configured.",
            "details": {"enabled_agents": count, "purpose": purpose_slug},
        }
    try:
        resolved = resolve_ai_config(purpose_slug=purpose_slug)
        return {
            "component": f"{purpose_slug}_agents",
            "status": "ok",
            "message": (
                f"{count} enabled {purpose_slug} agent(s) available. "
                f"Using {resolved.get('provider')}:{resolved.get('model_name')}."
            ),
            "details": {
                "enabled_agents": count,
                "purpose": purpose_slug,
                "provider": resolved.get("provider"),
                "model_name": resolved.get("model_name"),
                "agent_slug": resolved.get("agent_slug"),
            },
        }
    except AiConfigError as exc:
        return {
            "component": f"{purpose_slug}_agents",
            "status": "error",
            "message": (
                f"{count} enabled {purpose_slug} agent(s) exist, but no usable runtime credential could be resolved: {exc}"
            ),
            "details": {"enabled_agents": count, "purpose": purpose_slug, "error": str(exc)},
        }
def _repository_checks() -> List[Dict[str, Any]]:
    active_repositories = list(ManagedRepository.objects.filter(is_active=True).order_by("slug"))
    if not active_repositories:
        return [
            {
                "component": "repositories",
                "status": "missing",
                "message": "No active repositories are registered.",
                "details": {"registered_repositories": 0},
            }
        ]
    checks: List[Dict[str, Any]] = [
        {
            "component": "repositories",
            "status": "ok",
            "message": f"{len(active_repositories)} active repositor{'y' if len(active_repositories) == 1 else 'ies'} registered.",
            "details": {
                "registered_repositories": len(active_repositories),
                "slugs": [repo.slug for repo in active_repositories[:5]],
            },
        }
    ]
    repo = active_repositories[0]
    try:
        validation = validate_managed_repository_registration(
            remote_url=str(repo.remote_url or ""),
            default_branch=str(repo.default_branch or "main"),
            auth_mode=str(repo.auth_mode or ""),
            verify_remote=True,
        )
        checks.append(
            {
                "component": "repository_access",
                "status": "ok",
                "message": f"Repository '{repo.slug}' is reachable on branch '{validation['branch']}'.",
                "details": {
                    "repository_slug": repo.slug,
                    "branch": validation["branch"],
                    "auth_mode": validation["auth_mode"],
                },
            }
        )
    except ManagedRepositoryError as exc:
        checks.append(
            {
                "component": "repository_access",
                "status": "error",
                "message": f"Repository '{repo.slug}' is not usable: {exc}",
                "details": {
                    "repository_slug": repo.slug,
                    "branch": str(repo.default_branch or "main"),
                    "auth_mode": str(repo.auth_mode or "local"),
                },
            }
        )
    return checks


def system_readiness_report() -> Dict[str, Any]:
    workspace_root = managed_workspace_root()
    artifact_root = managed_artifact_root()
    workspace_check = _check_writable_directory(workspace_root)
    artifact_check = _check_writable_directory(artifact_root)

    checks: List[Dict[str, Any]] = [
        _ai_provider_check(),
        _agent_purpose_check("planning"),
        _agent_purpose_check("coding"),
        {
            "component": "workspace_storage",
            "status": _status(workspace_check["ok"]),
            "message": workspace_check["message"],
            "details": {"path": str(workspace_root)},
        },
        {
            "component": "artifact_storage",
            "status": _status(artifact_check["ok"]),
            "message": artifact_check["message"],
            "details": {"path": str(artifact_root)},
        },
    ]
    checks.extend(_repository_checks())
    ready = all(check["status"] == "ok" for check in checks)
    if ready:
        summary = "System ready"
    elif any(check["status"] == "error" for check in checks):
        summary = "Critical setup issue"
    else:
        summary = "Configuration required"
    return {
        "ready": ready,
        "summary": summary,
        "checks": checks,
        "paths": {
            "workspace_root": str(workspace_root),
            "artifact_root": str(artifact_root),
        },
        "env": {
            "workspace_root_env": str(os.environ.get("XYN_WORKSPACE_ROOT", "")).strip() or None,
            "artifact_root_env": str(os.environ.get("XYN_ARTIFACT_ROOT", "")).strip() or None,
        },
    }
