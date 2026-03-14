from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0121_devtask_execution_brief_review"),
    ]

    operations = [
        migrations.AddField(
            model_name="devtask",
            name="execution_brief_history",
            field=models.JSONField(blank=True, default=list),
        ),
    ]

