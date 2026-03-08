from django.db import migrations


LEGACY_DEMO_ARTIFACT_SLUGS = [
    "ems",
    "ems-lite",
    "hello-app",
    "articles-tour",
    "platform-build-tour",
    "deploy-subscriber-notes",
    "subscriber-notes-walkthrough",
]


def remove_legacy_demo_artifacts(apps, schema_editor):
    Artifact = apps.get_model("xyn_orchestrator", "Artifact")
    Artifact.objects.filter(slug__in=LEGACY_DEMO_ARTIFACT_SLUGS).delete()


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0106_mark_system_workspaces"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_demo_artifacts, noop),
    ]
