from django.db import migrations


def forward(apps, schema_editor):
    Workspace = apps.get_model("xyn_orchestrator", "Workspace")
    for slug in ("platform-builder", "civic-lab"):
        workspace = Workspace.objects.filter(slug=slug).first()
        if not workspace:
            continue
        metadata = workspace.metadata_json if isinstance(workspace.metadata_json, dict) else {}
        if metadata.get("xyn_system_workspace") is True:
            continue
        metadata = dict(metadata)
        metadata["xyn_system_workspace"] = True
        metadata.setdefault("seed", "legacy")
        workspace.metadata_json = metadata
        workspace.save(update_fields=["metadata_json", "updated_at"])


def backward(apps, schema_editor):
    Workspace = apps.get_model("xyn_orchestrator", "Workspace")
    for slug in ("platform-builder", "civic-lab"):
        workspace = Workspace.objects.filter(slug=slug).first()
        if not workspace:
            continue
        metadata = workspace.metadata_json if isinstance(workspace.metadata_json, dict) else {}
        if "xyn_system_workspace" not in metadata:
            continue
        metadata = dict(metadata)
        metadata.pop("xyn_system_workspace", None)
        workspace.metadata_json = metadata
        workspace.save(update_fields=["metadata_json", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0105_seed_release_target_deployment_types"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
