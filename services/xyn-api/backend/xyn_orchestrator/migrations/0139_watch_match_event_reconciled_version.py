from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0138_reconciled_state_current_pointer"),
    ]

    operations = [
        migrations.AddField(
            model_name="watchmatchevent",
            name="reconciled_state_version",
            field=models.CharField(blank=True, db_index=True, default="", max_length=160),
        ),
    ]
