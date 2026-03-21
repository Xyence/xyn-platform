import uuid

import django.db.models.deletion
from django.db import migrations, models


def _backfill_orchestration_job_run_fields(apps, schema_editor):
    JobRun = apps.get_model("xyn_orchestrator", "OrchestrationJobRun")
    for row in JobRun.objects.select_related("run", "run__pipeline", "run__workspace").all().iterator():
        run = row.run
        if run is None:
            continue
        row.workspace_id = run.workspace_id
        row.pipeline_id = run.pipeline_id
        row.correlation_id = str(run.correlation_id or "")
        row.chain_id = str(run.chain_id or "")
        row.scope_jurisdiction = str(run.scope_jurisdiction or "")
        row.scope_source = str(run.scope_source or "")
        row.trigger_cause = str(run.trigger_cause or "manual")
        row.trigger_key = str(run.trigger_key or "")
        row.save(
            update_fields=[
                "workspace",
                "pipeline",
                "correlation_id",
                "chain_id",
                "scope_jurisdiction",
                "scope_source",
                "trigger_cause",
                "trigger_key",
                "updated_at",
            ]
        )


def _copy_legacy_job_outputs(apps, schema_editor):
    JobRun = apps.get_model("xyn_orchestrator", "OrchestrationJobRun")
    JobRunOutput = apps.get_model("xyn_orchestrator", "OrchestrationJobRunOutput")
    for row in JobRun.objects.all().iterator():
        output_json = row.output_json if isinstance(row.output_json, dict) else {}
        if not output_json and not row.output_artifact_id and not str(row.output_change_token or "").strip():
            continue
        JobRunOutput.objects.update_or_create(
            job_run_id=row.id,
            output_key="default",
            defaults={
                "output_type": "legacy",
                "output_uri": "",
                "output_change_token": str(row.output_change_token or "").strip(),
                "artifact_id": row.output_artifact_id,
                "metadata_json": {},
                "payload_json": output_json,
            },
        )


def _normalize_orchestration_status_tokens(apps, schema_editor):
    Run = apps.get_model("xyn_orchestrator", "OrchestrationRun")
    JobRun = apps.get_model("xyn_orchestrator", "OrchestrationJobRun")
    Attempt = apps.get_model("xyn_orchestrator", "OrchestrationJobRunAttempt")

    Run.objects.filter(status="canceled").update(status="cancelled")
    JobRun.objects.filter(status="canceled").update(status="cancelled")
    Attempt.objects.filter(status="canceled").update(status="cancelled")

    Run.objects.filter(trigger_cause="rerun").update(trigger_cause="retry")
    Run.objects.filter(trigger_cause="event").update(trigger_cause="system")


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0125_orchestration_scaffolding"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrchestrationJobSchedule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("schedule_key", models.CharField(max_length=120)),
                (
                    "schedule_kind",
                    models.CharField(
                        choices=[("manual", "Manual"), ("interval", "Interval"), ("cron", "Cron"), ("event", "Event")],
                        default="manual",
                        max_length=20,
                    ),
                ),
                ("enabled", models.BooleanField(db_index=True, default=True)),
                ("cron_expression", models.CharField(blank=True, default="", max_length=120)),
                ("interval_seconds", models.PositiveIntegerField(default=0)),
                ("timezone_name", models.CharField(blank=True, default="UTC", max_length=80)),
                ("next_fire_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_fired_at", models.DateTimeField(blank=True, null=True)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "job_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedules",
                        to="xyn_orchestrator.orchestrationjobdefinition",
                    ),
                ),
            ],
            options={"ordering": ["schedule_key", "created_at"]},
        ),
        migrations.CreateModel(
            name="OrchestrationJobRunAttempt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("attempt_number", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                            ("cancelled", "Cancelled"),
                            ("stale", "Stale"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("executor_key", models.CharField(blank=True, default="", max_length=120)),
                ("summary", models.CharField(blank=True, default="", max_length=240)),
                ("error_text", models.TextField(blank=True, default="")),
                ("error_details_json", models.JSONField(blank=True, null=True)),
                ("metrics_json", models.JSONField(blank=True, default=dict)),
                ("output_json", models.JSONField(blank=True, default=dict)),
                ("retryable", models.BooleanField(default=False)),
                ("queued_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("stale_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "job_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempts",
                        to="xyn_orchestrator.orchestrationjobrun",
                    ),
                ),
            ],
            options={"ordering": ["attempt_number", "created_at"]},
        ),
        migrations.CreateModel(
            name="OrchestrationJobRunOutput",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("output_key", models.CharField(max_length=120)),
                ("output_type", models.CharField(default="generic", max_length=80)),
                ("output_uri", models.TextField(blank=True, default="")),
                ("output_change_token", models.CharField(blank=True, db_index=True, default="", max_length=160)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "artifact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="orchestration_job_outputs",
                        to="xyn_orchestrator.artifact",
                    ),
                ),
                (
                    "attempt",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="outputs",
                        to="xyn_orchestrator.orchestrationjobrunattempt",
                    ),
                ),
                (
                    "job_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="outputs",
                        to="xyn_orchestrator.orchestrationjobrun",
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.RenameField(
            model_name="orchestrationrun",
            old_name="trigger_type",
            new_name="trigger_cause",
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="chain_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="correlation_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="dedupe_key",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="error_details_json",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="idempotency_key",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="metrics_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="queued_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="stale_deadline_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="orchestrationrun",
            name="stale_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="chain_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="correlation_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="dedupe_key",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="error_details_json",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="idempotency_key",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="metrics_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="pipeline",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="job_runs",
                to="xyn_orchestrator.orchestrationpipeline",
            ),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="queued_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="scope_jurisdiction",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="scope_source",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="stale_deadline_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="stale_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="trigger_cause",
            field=models.CharField(
                choices=[
                    ("scheduled", "Scheduled"),
                    ("upstream_change", "Upstream Change"),
                    ("manual", "Manual"),
                    ("retry", "Retry"),
                    ("backfill", "Backfill"),
                    ("system", "System"),
                ],
                db_index=True,
                default="manual",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="trigger_key",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="orchestrationjobrun",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="orchestration_job_runs",
                to="xyn_orchestrator.workspace",
            ),
        ),
        migrations.RunPython(_backfill_orchestration_job_run_fields, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="orchestrationjobrun",
            name="pipeline",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="job_runs",
                to="xyn_orchestrator.orchestrationpipeline",
            ),
        ),
        migrations.AlterField(
            model_name="orchestrationjobrun",
            name="workspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="orchestration_job_runs",
                to="xyn_orchestrator.workspace",
            ),
        ),
        migrations.RunPython(_copy_legacy_job_outputs, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="orchestrationjobrun",
            name="output_artifact",
        ),
        migrations.RemoveField(
            model_name="orchestrationjobrun",
            name="output_json",
        ),
        migrations.AlterField(
            model_name="orchestrationrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                    ("stale", "Stale"),
                    ("skipped", "Skipped"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="orchestrationrun",
            name="trigger_cause",
            field=models.CharField(
                choices=[
                    ("scheduled", "Scheduled"),
                    ("upstream_change", "Upstream Change"),
                    ("manual", "Manual"),
                    ("retry", "Retry"),
                    ("backfill", "Backfill"),
                    ("system", "System"),
                ],
                db_index=True,
                default="manual",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="orchestrationjobrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("skipped", "Skipped"),
                    ("cancelled", "Cancelled"),
                    ("stale", "Stale"),
                    ("waiting_retry", "Waiting Retry"),
                ],
                db_index=True,
                default="queued",
                max_length=20,
            ),
        ),
        migrations.RunPython(_normalize_orchestration_status_tokens, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="orchestrationjobschedule",
            constraint=models.UniqueConstraint(fields=("job_definition", "schedule_key"), name="uniq_orchestration_job_schedule_key"),
        ),
        migrations.AddConstraint(
            model_name="orchestrationjobrunattempt",
            constraint=models.UniqueConstraint(fields=("job_run", "attempt_number"), name="uniq_orch_job_run_attempt_number"),
        ),
        migrations.AddConstraint(
            model_name="orchestrationjobrunoutput",
            constraint=models.UniqueConstraint(fields=("job_run", "output_key"), name="uniq_orch_job_run_output_key"),
        ),
        migrations.AddConstraint(
            model_name="orchestrationrun",
            constraint=models.UniqueConstraint(
                condition=models.Q(idempotency_key__gt=""),
                fields=("workspace", "pipeline", "idempotency_key"),
                name="uniq_orch_run_idempotency",
            ),
        ),
        migrations.AddConstraint(
            model_name="orchestrationjobrun",
            constraint=models.UniqueConstraint(
                condition=models.Q(idempotency_key__gt=""),
                fields=("workspace", "job_definition", "idempotency_key"),
                name="uniq_orch_job_run_idempotency",
            ),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobschedule",
            index=models.Index(fields=["enabled", "next_fire_at"], name="ix_orch_job_sched_poll"),
        ),
        migrations.AddIndex(
            model_name="orchestrationrun",
            index=models.Index(fields=["workspace", "status", "queued_at"], name="ix_orch_run_scheduler_poll"),
        ),
        migrations.AddIndex(
            model_name="orchestrationrun",
            index=models.Index(fields=["workspace", "trigger_cause", "created_at"], name="ix_orch_run_trigger_time"),
        ),
        migrations.AddIndex(
            model_name="orchestrationrun",
            index=models.Index(fields=["workspace", "correlation_id", "created_at"], name="ix_orch_run_corr_time"),
        ),
        migrations.AddIndex(
            model_name="orchestrationrun",
            index=models.Index(fields=["workspace", "chain_id", "created_at"], name="ix_orch_run_chain_time"),
        ),
        migrations.AddIndex(
            model_name="orchestrationrun",
            index=models.Index(fields=["workspace", "scope_jurisdiction", "scope_source", "status"], name="ix_orch_run_partition_status"),
        ),
        migrations.AddIndex(
            model_name="orchestrationrun",
            index=models.Index(fields=["pipeline", "stale_deadline_at", "status"], name="ix_orch_run_stale_poll"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrun",
            index=models.Index(fields=["job_definition", "status", "created_at"], name="ix_orch_job_run_job_status"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrun",
            index=models.Index(fields=["workspace", "pipeline", "status", "next_attempt_at"], name="ix_orch_job_run_poll"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrun",
            index=models.Index(fields=["workspace", "scope_jurisdiction", "scope_source", "status"], name="ix_orch_job_run_partition_status"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrun",
            index=models.Index(fields=["workspace", "correlation_id", "created_at"], name="ix_orch_job_run_corr_time"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrun",
            index=models.Index(fields=["workspace", "chain_id", "created_at"], name="ix_orch_job_run_chain_time"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrun",
            index=models.Index(fields=["job_definition", "scope_jurisdiction", "scope_source"], name="ix_orch_job_run_job_partition"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrun",
            index=models.Index(fields=["pipeline", "stale_deadline_at", "status"], name="ix_orch_job_run_stale_poll"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrunattempt",
            index=models.Index(fields=["job_run", "status"], name="ix_orch_attempt_job_status"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrunattempt",
            index=models.Index(fields=["status", "queued_at"], name="ix_orch_attempt_sched_poll"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrunoutput",
            index=models.Index(fields=["job_run", "created_at"], name="ix_orch_output_job_time"),
        ),
        migrations.AddIndex(
            model_name="orchestrationjobrunoutput",
            index=models.Index(fields=["output_type", "created_at"], name="ix_orch_output_type_time"),
        ),
    ]
