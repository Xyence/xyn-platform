from __future__ import annotations

from django.core.management.base import BaseCommand

from xyn_orchestrator.models import Artifact
from xyn_orchestrator.runtime_artifact_provenance import (
    RUNTIME_PROVENANCE_HINTS,
    build_runtime_artifact_git_provenance,
    canonical_git_provenance_missing_fields,
    merge_runtime_provenance,
    runtime_git_source_ref,
)


class Command(BaseCommand):
    help = "Backfill canonical git provenance + source refs for runtime artifacts (xyn-api/xyn-ui/workbench/xyn-runtime)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            action="append",
            dest="slugs",
            default=[],
            help="Optional artifact slug filter (repeatable). Defaults to known runtime artifact slugs.",
        )
        parser.add_argument(
            "--workspace-slug",
            dest="workspace_slug",
            default="",
            help="Optional workspace slug filter.",
        )
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")
        parser.add_argument(
            "--strict",
            action="store_true",
            dest="strict",
            help="Fail command if any targeted runtime artifact is missing canonical git provenance fields.",
        )

    def handle(self, *args, **options):
        slugs = [str(item).strip() for item in (options.get("slugs") or []) if str(item).strip()]
        if not slugs:
            slugs = list(RUNTIME_PROVENANCE_HINTS.keys())
        workspace_slug = str(options.get("workspace_slug") or "").strip()
        dry_run = bool(options.get("dry_run"))
        strict = bool(options.get("strict"))

        qs = Artifact.objects.filter(slug__in=slugs).select_related("workspace").order_by("-updated_at", "-created_at")
        if workspace_slug:
            qs = qs.filter(workspace__slug=workspace_slug)
        rows = list(qs)
        updated = 0
        scanned = 0
        invalid = 0
        for artifact in rows:
            scanned += 1
            scope = artifact.scope_json if isinstance(artifact.scope_json, dict) else {}
            existing = artifact.provenance_json if isinstance(artifact.provenance_json, dict) else {}
            canonical_git = build_runtime_artifact_git_provenance(
                slug=str(artifact.slug or ""),
                manifest_ref=str(scope.get("manifest_ref") or ""),
                existing_provenance=existing,
            )
            if not canonical_git:
                continue
            merged = merge_runtime_provenance(existing, canonical_git)
            missing = canonical_git_provenance_missing_fields(merged)
            if missing:
                invalid += 1
                self.stdout.write(
                    f"[warning] artifact={artifact.slug} workspace={artifact.workspace.slug} missing={','.join(missing)}"
                )
                continue
            source_ref_type, source_ref_id = runtime_git_source_ref(canonical_git)
            change_fields = []
            if merged != existing:
                artifact.provenance_json = merged
                change_fields.append("provenance_json")
            if str(artifact.source_ref_type or "") != source_ref_type:
                artifact.source_ref_type = source_ref_type
                change_fields.append("source_ref_type")
            if str(artifact.source_ref_id or "") != source_ref_id:
                artifact.source_ref_id = source_ref_id
                change_fields.append("source_ref_id")
            if not change_fields:
                continue
            updated += 1
            if dry_run:
                self.stdout.write(
                    f"[dry-run] artifact={artifact.slug} workspace={artifact.workspace.slug} changes={','.join(change_fields)}"
                )
                continue
            artifact.save(update_fields=[*change_fields, "updated_at"])

        if strict and invalid > 0:
            raise SystemExit(f"runtime_artifact_provenance_backfill strict failure: invalid={invalid}")
        self.stdout.write(
            self.style.SUCCESS(
                "runtime_artifact_provenance_backfill "
                f"scanned={scanned} updated={updated} invalid={invalid} dry_run={str(dry_run).lower()}"
            )
        )
