from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("xyn_orchestrator", "0151_agentdefinition_avatar_url"),
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
                  AND column_name='edit_mode'
              ) THEN
                ALTER TABLE xyn_orchestrator_artifact
                  ALTER COLUMN edit_mode SET DEFAULT 'generated';
              END IF;
              IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='xyn_orchestrator_artifact'
                  AND column_name='owner_path_prefixes_json'
              ) THEN
                ALTER TABLE xyn_orchestrator_artifact
                  ALTER COLUMN owner_path_prefixes_json SET DEFAULT '[]'::jsonb;
              END IF;
            END
            $$;
            """,
            reverse_sql="""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='xyn_orchestrator_artifact'
                  AND column_name='edit_mode'
              ) THEN
                ALTER TABLE xyn_orchestrator_artifact
                  ALTER COLUMN edit_mode DROP DEFAULT;
              END IF;
              IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='xyn_orchestrator_artifact'
                  AND column_name='owner_path_prefixes_json'
              ) THEN
                ALTER TABLE xyn_orchestrator_artifact
                  ALTER COLUMN owner_path_prefixes_json DROP DEFAULT;
              END IF;
            END
            $$;
            """,
        ),
    ]
