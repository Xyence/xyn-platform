from django.db import migrations


def mark_net_inventory_bridge_artifact(apps, schema_editor):
    Artifact = apps.get_model("xyn_orchestrator", "Artifact")

    artifact = Artifact.objects.filter(slug="net-inventory").order_by("-updated_at", "-created_at").first()
    if artifact is None:
        return

    scope = dict(artifact.scope_json or {})
    scope["bridge_artifact"] = True
    scope["bridge_visibility"] = "workspace_bound_only"
    scope["bridge_debt_ref"] = "DEBT-02"
    scope.setdefault("manifest_ref", "registry/modules/net-inventory.artifact.manifest.json")
    scope.setdefault("slug", "net-inventory")

    if scope != (artifact.scope_json or {}):
        artifact.scope_json = scope
        artifact.save(update_fields=["scope_json", "updated_at"])


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0108_seed_net_inventory_artifact"),
    ]

    operations = [
        migrations.RunPython(mark_net_inventory_bridge_artifact, noop),
    ]
