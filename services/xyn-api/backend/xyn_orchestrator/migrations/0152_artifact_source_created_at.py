from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import migrations, models
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def _parse_source_ts(raw: Any) -> dt.datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt.timezone.utc)
    else:
        parsed = parsed.astimezone(dt.timezone.utc)
    return parsed


def _extract_candidate(artifact: Any) -> dt.datetime | None:
    scope = artifact.scope_json if isinstance(artifact.scope_json, dict) else {}
    provenance = artifact.provenance_json if isinstance(artifact.provenance_json, dict) else {}

    imported_manifest = scope.get("imported_manifest") if isinstance(scope.get("imported_manifest"), dict) else {}
    imported_artifact = imported_manifest.get("artifact") if isinstance(imported_manifest.get("artifact"), dict) else {}
    imported_meta = imported_manifest.get("metadata") if isinstance(imported_manifest.get("metadata"), dict) else {}

    for raw in (
        imported_artifact.get("source_created_at"),
        imported_meta.get("source_created_at"),
        scope.get("source_created_at"),
        provenance.get("source_created_at"),
        provenance.get("generated_at"),
    ):
        parsed = _parse_source_ts(raw)
        if parsed is not None:
            return parsed
    return None


def backfill_source_created_at(apps, schema_editor):
    Artifact = apps.get_model("xyn_orchestrator", "Artifact")
    for artifact in Artifact.objects.filter(source_created_at__isnull=True).iterator(chunk_size=500):
        parsed = _extract_candidate(artifact)
        if parsed is None:
            continue
        artifact.source_created_at = parsed
        artifact.save(update_fields=["source_created_at", "updated_at"])


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0151_agentdefinition_avatar_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifact",
            name="source_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_source_created_at, noop),
    ]
