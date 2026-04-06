from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0154_artifact_ownership_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="SolutionChangeSessionRepoCommit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("repository_slug", models.CharField(max_length=120)),
                ("branch", models.CharField(blank=True, default="", max_length=120)),
                ("commit_sha", models.CharField(max_length=128)),
                ("changed_files_json", models.JSONField(blank=True, default=list)),
                (
                    "validation_status",
                    models.CharField(
                        choices=[("unknown", "Unknown"), ("pending", "Pending"), ("passed", "Passed"), ("failed", "Failed")],
                        default="unknown",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "solution_change_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="repo_commits",
                        to="xyn_orchestrator.solutionchangesession",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="solution_change_session_repo_commits",
                        to="xyn_orchestrator.workspace",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="solutionchangesessionrepocommit",
            constraint=models.UniqueConstraint(
                fields=("solution_change_session", "repository_slug", "commit_sha"),
                name="uniq_solution_change_session_repo_commit",
            ),
        ),
    ]
