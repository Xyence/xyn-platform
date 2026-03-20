from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0137_ingest_artifact_record"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReconciledStateCurrentPointer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reconciled_state_version", models.CharField(blank=True, db_index=True, default="", max_length=160)),
                ("scope_jurisdiction", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("scope_source", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("promoted_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "pipeline",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="current_reconciled_pointers",
                        to="xyn_orchestrator.orchestrationpipeline",
                    ),
                ),
                (
                    "publication",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="current_reconciled_pointers",
                        to="xyn_orchestrator.orchestrationstagepublication",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="current_reconciled_pointers",
                        to="xyn_orchestrator.workspace",
                    ),
                ),
            ],
            options={
                "ordering": ["-promoted_at", "-updated_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="reconciledstatecurrentpointer",
            constraint=models.UniqueConstraint(
                fields=("workspace", "pipeline", "scope_jurisdiction", "scope_source"),
                name="uniq_recon_ptr_scope",
            ),
        ),
        migrations.AddIndex(
            model_name="reconciledstatecurrentpointer",
            index=models.Index(
                fields=["workspace", "pipeline", "scope_jurisdiction", "scope_source", "promoted_at"],
                name="ix_recon_ptr_scope_time",
            ),
        ),
        migrations.AddIndex(
            model_name="reconciledstatecurrentpointer",
            index=models.Index(
                fields=["workspace", "reconciled_state_version"],
                name="ix_recon_ptr_version",
            ),
        ),
    ]
