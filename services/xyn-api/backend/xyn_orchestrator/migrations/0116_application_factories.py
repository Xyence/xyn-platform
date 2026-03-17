from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0115_goal_planning"),
    ]

    operations = [
        migrations.CreateModel(
            name="Application",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=240)),
                ("summary", models.TextField(blank=True)),
                ("source_factory_key", models.CharField(max_length=120)),
                ("source_conversation_id", models.CharField(blank=True, max_length=120)),
                ("status", models.CharField(choices=[("active", "Active"), ("completed", "Completed"), ("archived", "Archived")], default="active", max_length=20)),
                ("plan_fingerprint", models.CharField(blank=True, default="", max_length=128)),
                ("request_objective", models.TextField(blank=True)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_applications", to="xyn_orchestrator.useridentity")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="applications", to="xyn_orchestrator.workspace")),
            ],
            options={"ordering": ["-updated_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="ApplicationPlan",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=240)),
                ("summary", models.TextField(blank=True)),
                ("source_factory_key", models.CharField(max_length=120)),
                ("source_conversation_id", models.CharField(blank=True, max_length=120)),
                ("status", models.CharField(choices=[("review", "Review"), ("applied", "Applied"), ("canceled", "Canceled")], default="review", max_length=20)),
                ("request_objective", models.TextField(blank=True)),
                ("plan_fingerprint", models.CharField(blank=True, default="", max_length=128)),
                ("plan_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("application", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="plans", to="xyn_orchestrator.application")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_application_plans", to="xyn_orchestrator.useridentity")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="application_plans", to="xyn_orchestrator.workspace")),
            ],
            options={"ordering": ["-updated_at", "-created_at"]},
        ),
        migrations.AddField(
            model_name="goal",
            name="application",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="goals", to="xyn_orchestrator.application"),
        ),
        migrations.AddConstraint(
            model_name="application",
            constraint=models.UniqueConstraint(condition=models.Q(("plan_fingerprint__gt", "")), fields=("workspace", "plan_fingerprint"), name="uniq_application_plan_fingerprint_per_workspace"),
        ),
        migrations.AddConstraint(
            model_name="applicationplan",
            constraint=models.UniqueConstraint(condition=models.Q(("plan_fingerprint__gt", "")), fields=("workspace", "plan_fingerprint"), name="uniq_application_plan_fingerprint_review_per_workspace"),
        ),
    ]
