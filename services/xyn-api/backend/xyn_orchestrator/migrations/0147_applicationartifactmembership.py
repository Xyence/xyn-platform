from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0146_signalreadmodel"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApplicationArtifactMembership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("primary_ui", "Primary UI"),
                            ("primary_api", "Primary API"),
                            ("integration_adapter", "Integration Adapter"),
                            ("worker", "Worker"),
                            ("runtime_service", "Runtime Service"),
                            ("shared_library", "Shared Library"),
                            ("supporting", "Supporting"),
                        ],
                        default="supporting",
                        max_length=40,
                    ),
                ),
                ("responsibility_summary", models.TextField(blank=True)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="artifact_memberships",
                        to="xyn_orchestrator.application",
                    ),
                ),
                (
                    "artifact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="application_memberships",
                        to="xyn_orchestrator.artifact",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="application_artifact_memberships",
                        to="xyn_orchestrator.workspace",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="applicationartifactmembership",
            constraint=models.UniqueConstraint(fields=("application", "artifact"), name="uniq_application_artifact_membership"),
        ),
    ]

