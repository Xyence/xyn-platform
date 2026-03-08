from django.db import migrations


def seed_net_inventory_artifact(apps, schema_editor):
    # Temporary bridge artifact: this seeds a stable Django-side module record so the
    # sibling Xyn demo path can bind and count a visible capability while the real
    # generated publish/import/install lifecycle is still unfinished (DEBT-02).
    Workspace = apps.get_model("xyn_orchestrator", "Workspace")
    ArtifactType = apps.get_model("xyn_orchestrator", "ArtifactType")
    Artifact = apps.get_model("xyn_orchestrator", "Artifact")

    module_type, _ = ArtifactType.objects.get_or_create(
        slug="module",
        defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
    )
    host_workspace = Workspace.objects.filter(slug="platform-builder").first()
    if host_workspace is None:
        host_workspace = Workspace.objects.order_by("created_at").first()
    if host_workspace is None:
        host_workspace = Workspace.objects.create(slug="platform-builder", name="Platform Builder")

    slug = "net-inventory"
    title = "Network Inventory"
    summary = "Installed capability artifact for network inventory operations inside the Xyn runtime shell."
    manifest_ref = "registry/modules/net-inventory.artifact.manifest.json"
    scope_json = {
        "slug": slug,
        "manifest_ref": manifest_ref,
        "summary": summary,
        "bridge_artifact": True,
        "bridge_visibility": "workspace_bound_only",
        "bridge_debt_ref": "DEBT-02",
    }

    artifact = Artifact.objects.filter(slug=slug).order_by("-updated_at", "-created_at").first()
    if artifact is None:
        Artifact.objects.create(
            workspace=host_workspace,
            type=module_type,
            title=title,
            slug=slug,
            status="published",
            visibility="team",
            summary=summary,
            scope_json=scope_json,
            provenance_json={"source_system": "seed-kernel", "source_id": slug},
        )
        return

    scope = dict(scope_json)
    changed = False
    if str(artifact.title or "") != title:
        artifact.title = title
        changed = True
    if str(artifact.summary or "") != summary:
        artifact.summary = summary
        changed = True
    if scope != (artifact.scope_json or {}):
        artifact.scope_json = scope
        changed = True
    if changed:
        artifact.save(update_fields=["title", "summary", "scope_json", "updated_at"])


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0107_remove_legacy_demo_artifacts"),
    ]

    operations = [
        migrations.RunPython(seed_net_inventory_artifact, noop),
    ]
