from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0126_orchestration_lifecycle_persistence"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="orchestrationjobrun",
            old_name="ix_orch_job_run_partition_status",
            new_name="ix_orch_jrun_part_status",
        ),
    ]
