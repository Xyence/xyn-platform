from django.db import migrations


def retire_net_inventory_bridge_artifact(apps, schema_editor):
    Artifact = apps.get_model("xyn_orchestrator", "Artifact")

    # Historical migrations still create the temporary bridge artifact so older
    # databases can replay cleanly. The current generated-artifact path installs
    # app.net-inventory instead, so retire the bridge artifact from active state.
    Artifact.objects.filter(slug="net-inventory").delete()


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0109_mark_net_inventory_bridge_artifact"),
    ]

    operations = [
        migrations.RunPython(retire_net_inventory_bridge_artifact, noop),
    ]
