from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0111_devtask_runtime_run_bridge"),
    ]

    operations = [
        migrations.AddField(
            model_name="devtask",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="devtask",
            name="execution_policy",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="devtask",
            name="intent_type",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="devtask",
            name="source_conversation_id",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="devtask",
            name="target_branch",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="devtask",
            name="target_repo",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name="devtask",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("awaiting_review", "Awaiting review"),
                    ("completed", "Completed"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("canceled", "Canceled"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
    ]
