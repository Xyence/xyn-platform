from __future__ import annotations

import re
from pathlib import Path

IGNORED_PATH_PARTS = {"tests", "migrations", "__pycache__"}

MODEL_DECL_RE = re.compile(r"^\s*class\s+([A-Za-z0-9_]+)\(models\.Model\):")
SEQUENCE_MATCHER_RE = re.compile(r"\bSequenceMatcher\b")
POSTGIS_SQL_RE = re.compile(r"\bST_[A-Za-z_]+\s*\(")
DEPLOYMENT_PROVIDER_MARKER_RE = re.compile(
    r"(boto3|botocore|route53|AWS-RunShellScript|amazonaws\.com|aws_access_key_id|aws_secret_access_key)",
    re.IGNORECASE,
)
DEPLOYMENT_DOMAIN_RE = re.compile(r"(deploy|deployment|provision|release_target|compose)", re.IGNORECASE)

KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("watch", ("xyn_orchestrator/watching/", "xyn_orchestrator/models.py")),
    ("subscription", ("xyn_orchestrator/watching/", "xyn_orchestrator/models.py")),
    ("match", ("xyn_orchestrator/matching/", "xyn_orchestrator/models.py")),
    ("lifecycle", ("xyn_orchestrator/lifecycle_primitive/", "xyn_orchestrator/models.py")),
    ("transition", ("xyn_orchestrator/lifecycle_primitive/", "xyn_orchestrator/models.py")),
    ("provenance", ("xyn_orchestrator/provenance/", "xyn_orchestrator/models.py")),
    ("audit", ("xyn_orchestrator/provenance/", "xyn_orchestrator/models.py")),
    ("geo", ("xyn_orchestrator/geospatial/", "xyn_orchestrator/models.py")),
)

ALLOWED_SEQUENCE_MATCHER_PATHS = (
    "xyn_orchestrator/matching/",
)

ALLOWED_POSTGIS_SQL_PATHS = (
    "xyn_orchestrator/geospatial/repository.py",
)

ALLOWED_DEPLOYMENT_PROVIDER_CORE_PATHS = (
    "xyn_orchestrator/deployments.py",
    "xyn_orchestrator/xyn_api.py",
    "xyn_orchestrator/instance_drivers.py",
    "xyn_orchestrator/dns_providers.py",
    "xyn_orchestrator/provisioning.py",
    "xyn_orchestrator/provisioning_views.py",
    "xyn_orchestrator/blueprints.py",
    "xyn_orchestrator/worker_tasks.py",
    "xyn_orchestrator/instances/",
    "xyn_orchestrator/deployment_provider_contract.py",
    "xyn_orchestrator/architecture_placement.py",
)


def _is_allowed(relpath: str, *, allowed_prefixes: tuple[str, ...]) -> bool:
    return any(relpath == prefix or relpath.startswith(prefix) for prefix in allowed_prefixes)


def scan_backend_canonical_drift(backend_root: Path) -> list[str]:
    runtime_root = backend_root / "xyn_orchestrator"
    findings: list[str] = []

    for path in runtime_root.rglob("*.py"):
        if any(part in IGNORED_PATH_PARTS for part in path.parts):
            continue
        relpath = str(path.relative_to(backend_root)).replace("\\", "/")
        if relpath.startswith("xyn_orchestrator/guardrails/"):
            continue
        contents = path.read_text(encoding="utf-8")
        lines = contents.splitlines()

        for line_number, line in enumerate(lines, start=1):
            model_match = MODEL_DECL_RE.match(line)
            if model_match:
                class_name = model_match.group(1)
                lowered = class_name.lower()
                for keyword, allowed_prefixes in KEYWORD_RULES:
                    if keyword not in lowered:
                        continue
                    if not _is_allowed(relpath, allowed_prefixes=allowed_prefixes):
                        findings.append(
                            f"{relpath}:{line_number} model class '{class_name}' looks like canonical '{keyword}' domain outside approved locations"
                        )

            if SEQUENCE_MATCHER_RE.search(line):
                if not _is_allowed(relpath, allowed_prefixes=ALLOWED_SEQUENCE_MATCHER_PATHS):
                    findings.append(
                        f"{relpath}:{line_number} uses SequenceMatcher outside matching primitive"
                    )

            if POSTGIS_SQL_RE.search(line):
                if not _is_allowed(relpath, allowed_prefixes=ALLOWED_POSTGIS_SQL_PATHS):
                    findings.append(
                        f"{relpath}:{line_number} uses raw PostGIS SQL outside geospatial repository"
                    )

        if DEPLOYMENT_PROVIDER_MARKER_RE.search(contents) and DEPLOYMENT_DOMAIN_RE.search(contents):
            if not _is_allowed(relpath, allowed_prefixes=ALLOWED_DEPLOYMENT_PROVIDER_CORE_PATHS):
                findings.append(
                    f"{relpath}: provider-specific deployment markers found outside approved deployment seams"
                )

    return findings
