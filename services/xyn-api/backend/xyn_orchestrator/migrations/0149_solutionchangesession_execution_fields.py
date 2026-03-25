from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0148_solutionchangesession"),
    ]

    operations = [
        migrations.AddField(
            model_name="solutionchangesession",
            name="execution_status",
            field=models.CharField(
                choices=[
                    ("not_started", "Not Started"),
                    ("staged", "Staged"),
                    ("preview_preparing", "Preview Preparing"),
                    ("preview_ready", "Preview Ready"),
                    ("validating", "Validating"),
                    ("ready_for_promotion", "Ready for Promotion"),
                    ("failed", "Failed"),
                ],
                default="not_started",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="solutionchangesession",
            name="preview_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="solutionchangesession",
            name="staged_changes_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="solutionchangesession",
            name="validation_json",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
