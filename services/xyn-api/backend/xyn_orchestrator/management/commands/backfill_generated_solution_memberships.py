from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from xyn_orchestrator.models import Workspace
from xyn_orchestrator.xyn_api import _backfill_legacy_generated_solution_memberships


class Command(BaseCommand):
    help = "Backfill deterministic Application/ApplicationArtifactMembership links for legacy generated app artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", dest="workspace_id", default="", help="Optional workspace id filter.")
        parser.add_argument("--workspace-slug", dest="workspace_slug", default="", help="Optional workspace slug filter.")
        parser.add_argument("--dry-run", action="store_true", help="Report backfill actions without persisting.")

    def handle(self, *args, **options):
        workspace_id = str(options.get("workspace_id") or "").strip()
        workspace_slug = str(options.get("workspace_slug") or "").strip()
        dry_run = bool(options.get("dry_run"))

        if workspace_id and workspace_slug:
            self.stdout.write(self.style.ERROR("Provide either --workspace-id or --workspace-slug, not both."))
            return
        if workspace_slug:
            workspace = Workspace.objects.filter(slug=workspace_slug).first()
            if workspace is None:
                self.stdout.write(self.style.ERROR(f"Workspace not found: {workspace_slug}"))
                return
            workspace_id = str(workspace.id)

        summary = _backfill_legacy_generated_solution_memberships(
            workspace_id=workspace_id or None,
            dry_run=dry_run,
        )
        self.stdout.write(json.dumps(summary, indent=2, sort_keys=True, default=str))
