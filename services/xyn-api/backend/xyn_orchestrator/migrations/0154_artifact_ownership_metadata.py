from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0153_solutionruntimebinding"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifact",
            name="edit_mode",
            field=models.CharField(
                choices=[("repo_backed", "Repo Backed"), ("generated", "Generated"), ("read_only", "Read Only")],
                default="generated",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="artifact",
            name="owner_path_prefixes_json",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="artifact",
            name="owner_repo_slug",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
