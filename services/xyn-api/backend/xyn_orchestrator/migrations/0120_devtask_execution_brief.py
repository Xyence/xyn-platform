from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0119_application_target_repository"),
    ]

    operations = [
        migrations.AddField(
            model_name="devtask",
            name="execution_brief",
            field=models.JSONField(blank=True, null=True),
        ),
    ]

