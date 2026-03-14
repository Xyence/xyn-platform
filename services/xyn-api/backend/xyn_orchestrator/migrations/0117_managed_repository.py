from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0116_application_factories"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManagedRepository",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("slug", models.SlugField(max_length=120, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=200)),
                ("remote_url", models.TextField()),
                ("default_branch", models.CharField(default="main", max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "auth_mode",
                    models.CharField(
                        blank=True,
                        choices=[("", "Default"), ("local", "Local"), ("https_token", "HTTPS token"), ("ssh", "SSH")],
                        default="",
                        max_length=32,
                    ),
                ),
                ("metadata_json", models.JSONField(blank=True, null=True)),
                ("local_cache_relpath", models.CharField(blank=True, max_length=240)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["slug"]},
        ),
    ]
