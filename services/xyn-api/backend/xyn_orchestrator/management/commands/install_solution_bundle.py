from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand

from xyn_orchestrator.models import Workspace
from xyn_orchestrator.solution_bundles import (
    SolutionBundleError,
    install_solution_bundle,
    load_solution_bundle_from_source,
)


class Command(BaseCommand):
    help = "Install/update a solution bundle into a workspace from file/package/S3 source."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            action="append",
            default=[],
            help="Bundle source. Supported: file path, file://, package://<id>, s3://bucket/key. Repeatable.",
        )
        parser.add_argument(
            "--from-env",
            action="store_true",
            help="Include sources from XYN_SOLUTION_BUNDLE_SOURCES (comma-separated).",
        )
        parser.add_argument("--workspace-id", dest="workspace_id", default="", help="Target workspace id.")
        parser.add_argument("--workspace-slug", dest="workspace_slug", default="", help="Target workspace slug.")

    def handle(self, *args, **options):
        workspace_id = str(options.get("workspace_id") or "").strip()
        workspace_slug = str(options.get("workspace_slug") or "").strip()
        if workspace_id and workspace_slug:
            self.stdout.write(self.style.ERROR("Provide either --workspace-id or --workspace-slug, not both."))
            return
        workspace = None
        if workspace_id:
            workspace = Workspace.objects.filter(id=workspace_id).first()
        elif workspace_slug:
            workspace = Workspace.objects.filter(slug=workspace_slug).first()
        if workspace is None:
            self.stdout.write(self.style.ERROR("workspace not found"))
            return

        sources = [str(item or "").strip() for item in (options.get("source") or []) if str(item or "").strip()]
        if bool(options.get("from_env")):
            env_sources = str(os.environ.get("XYN_SOLUTION_BUNDLE_SOURCES") or "").strip()
            if env_sources:
                sources.extend([chunk.strip() for chunk in env_sources.split(",") if chunk.strip()])
        if not sources:
            self.stdout.write(
                self.style.ERROR("No sources provided. Use --source or --from-env with XYN_SOLUTION_BUNDLE_SOURCES.")
            )
            return

        reports = []
        for source in sources:
            try:
                bundle = load_solution_bundle_from_source(source)
                result = install_solution_bundle(
                    workspace=workspace,
                    bundle=bundle,
                    install_source=source,
                    installed_by=None,
                )
            except SolutionBundleError as exc:
                reports.append({"source": source, "status": "failed", "error": str(exc)})
                continue
            application = result.get("application")
            reports.append(
                {
                    "source": source,
                    "status": "success",
                    "application_id": str(getattr(application, "id", "") or ""),
                    "application_name": str(getattr(application, "name", "") or ""),
                    "policy_source": str(result.get("policy_source") or "reconstructed"),
                    "install_source": str(result.get("install_source") or source),
                    "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
                }
            )
        self.stdout.write(json.dumps({"workspace_id": str(workspace.id), "results": reports}, indent=2, sort_keys=True))
