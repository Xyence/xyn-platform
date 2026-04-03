from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0155_solutionchangesessionrepocommit"),
    ]

    operations = [
        migrations.AlterField(
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
                    ("committed", "Committed"),
                    ("promoted", "Promoted"),
                    ("failed", "Failed"),
                ],
                default="not_started",
                max_length=32,
            ),
        ),
    ]
