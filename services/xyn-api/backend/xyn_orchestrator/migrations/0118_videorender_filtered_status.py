from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0117_managed_repository"),
    ]

    operations = [
        migrations.AlterField(
            model_name="videorender",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("filtered", "Filtered"),
                    ("canceled", "Canceled"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
    ]
