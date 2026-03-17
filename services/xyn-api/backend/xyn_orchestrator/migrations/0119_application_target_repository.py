from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0118_videorender_filtered_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="target_repository",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="applications",
                to="xyn_orchestrator.managedrepository",
            ),
        ),
        migrations.AddField(
            model_name="applicationplan",
            name="target_repository",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="application_plans",
                to="xyn_orchestrator.managedrepository",
            ),
        ),
    ]
