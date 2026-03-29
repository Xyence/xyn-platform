from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0152_artifact_source_created_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="SolutionRuntimeBinding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "activation_mode",
                    models.CharField(
                        choices=[("composed", "Composed"), ("reconstructed", "Reconstructed")],
                        default="reconstructed",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("active", "Active"), ("error", "Error")],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("runtime_target_json", models.JSONField(blank=True, default=dict)),
                ("last_activation_json", models.JSONField(blank=True, default=dict)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runtime_bindings",
                        to="xyn_orchestrator.application",
                    ),
                ),
                (
                    "policy_artifact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="solution_runtime_bindings_as_policy",
                        to="xyn_orchestrator.artifact",
                    ),
                ),
                (
                    "primary_app_artifact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="solution_runtime_bindings_as_primary",
                        to="xyn_orchestrator.artifact",
                    ),
                ),
                (
                    "runtime_instance",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="solution_runtime_bindings",
                        to="xyn_orchestrator.workspaceappinstance",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="solution_runtime_bindings",
                        to="xyn_orchestrator.workspace",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="solutionruntimebinding",
            constraint=models.UniqueConstraint(
                fields=("workspace", "application"),
                name="uniq_solution_runtime_binding_per_application",
            ),
        ),
    ]

