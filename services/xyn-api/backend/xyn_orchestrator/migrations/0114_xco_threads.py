from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0112_devtask_workitem_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="CoordinationThread",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=240)),
                ("description", models.TextField(blank=True)),
                (
                    "workspace",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="coordination_threads", to="xyn_orchestrator.workspace"),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[("critical", "Critical"), ("high", "High"), ("normal", "Normal"), ("low", "Low")],
                        default="normal",
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("queued", "Queued"), ("paused", "Paused"), ("completed", "Completed"), ("archived", "Archived")],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("domain", models.CharField(blank=True, max_length=80)),
                ("work_in_progress_limit", models.PositiveIntegerField(default=1)),
                ("execution_policy", models.JSONField(blank=True, default=dict)),
                ("source_conversation_id", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="coordination_threads", to="xyn_orchestrator.useridentity"),
                ),
            ],
            options={"ordering": ["-updated_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="CoordinationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(max_length=80)),
                ("run_id", models.UUIDField(blank=True, null=True)),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "thread",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="xyn_orchestrator.coordinationthread"),
                ),
                (
                    "work_item",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="coordination_events", to="xyn_orchestrator.devtask"),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddField(
            model_name="devtask",
            name="coordination_thread",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_items", to="xyn_orchestrator.coordinationthread"),
        ),
        migrations.AddField(
            model_name="devtask",
            name="dependency_work_item_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
