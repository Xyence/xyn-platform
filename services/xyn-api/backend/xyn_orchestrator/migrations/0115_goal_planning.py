from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0114_xco_threads"),
    ]

    operations = [
        migrations.CreateModel(
            name="Goal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=240)),
                ("description", models.TextField(blank=True)),
                ("source_conversation_id", models.CharField(blank=True, max_length=120)),
                (
                    "goal_type",
                    models.CharField(
                        choices=[
                            ("build_system", "Build System"),
                            ("extend_system", "Extend System"),
                            ("investigate_problem", "Investigate Problem"),
                            ("stabilize_system", "Stabilize System"),
                        ],
                        default="build_system",
                        max_length=40,
                    ),
                ),
                (
                    "planning_status",
                    models.CharField(
                        choices=[
                            ("proposed", "Proposed"),
                            ("decomposed", "Decomposed"),
                            ("in_progress", "In Progress"),
                            ("completed", "Completed"),
                            ("canceled", "Canceled"),
                        ],
                        default="proposed",
                        max_length=20,
                    ),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[("critical", "Critical"), ("high", "High"), ("normal", "Normal"), ("low", "Low")],
                        default="normal",
                        max_length=10,
                    ),
                ),
                ("planning_summary", models.TextField(blank=True)),
                ("resolution_notes_json", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_goals",
                        to="xyn_orchestrator.useridentity",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="goals",
                        to="xyn_orchestrator.workspace",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at", "-created_at"]},
        ),
        migrations.AddField(
            model_name="coordinationthread",
            name="goal",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="threads",
                to="xyn_orchestrator.goal",
            ),
        ),
        migrations.AddField(
            model_name="devtask",
            name="goal",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="work_items",
                to="xyn_orchestrator.goal",
            ),
        ),
    ]
