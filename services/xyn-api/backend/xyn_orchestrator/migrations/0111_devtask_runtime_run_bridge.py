from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0110_retire_net_inventory_bridge_artifact"),
    ]

    operations = [
        migrations.AddField(
            model_name="devtask",
            name="runtime_run_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="devtask",
            name="runtime_workspace_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
