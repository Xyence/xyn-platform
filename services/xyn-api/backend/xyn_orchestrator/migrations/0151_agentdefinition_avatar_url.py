from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0150_solutionplanningcheckpoint_solutionplanningturn"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentdefinition",
            name="avatar_url",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
