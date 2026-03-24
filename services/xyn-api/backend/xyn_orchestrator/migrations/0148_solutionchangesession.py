from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0147_applicationartifactmembership"),
    ]

    operations = [
        migrations.CreateModel(
            name="SolutionChangeSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=240)),
                ("request_text", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("planned", "Planned"), ("archived", "Archived")], default="draft", max_length=20)),
                ("analysis_json", models.JSONField(blank=True, default=dict)),
                ("selected_artifact_ids_json", models.JSONField(blank=True, default=list)),
                ("plan_json", models.JSONField(blank=True, default=dict)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="solution_change_sessions", to="xyn_orchestrator.application"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="solution_change_sessions",
                        to="xyn_orchestrator.useridentity",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="solution_change_sessions", to="xyn_orchestrator.workspace"),
                ),
            ],
            options={
                "ordering": ["-updated_at", "-created_at"],
            },
        ),
    ]

