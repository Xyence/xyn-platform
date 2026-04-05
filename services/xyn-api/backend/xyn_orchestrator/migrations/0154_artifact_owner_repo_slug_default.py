from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0153_artifact_legacy_column_defaults"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='xyn_orchestrator_artifact'
                  AND column_name='owner_repo_slug'
              ) THEN
                ALTER TABLE xyn_orchestrator_artifact
                  ALTER COLUMN owner_repo_slug SET DEFAULT '';
              END IF;
            END
            $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

