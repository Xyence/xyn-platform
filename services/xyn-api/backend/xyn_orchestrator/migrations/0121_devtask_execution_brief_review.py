from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0120_devtask_execution_brief"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="devtask",
            name="execution_brief_review_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="devtask",
            name="execution_brief_review_state",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("ready", "Ready"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("superseded", "Superseded"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="devtask",
            name="execution_brief_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="devtask",
            name="execution_brief_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dev_tasks_brief_reviewed",
                to="auth.user",
            ),
        ),
    ]

