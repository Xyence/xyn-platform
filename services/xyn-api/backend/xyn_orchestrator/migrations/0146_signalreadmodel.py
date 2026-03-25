from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("xyn_orchestrator", "0145_sourceconnector_governance_json_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SignalReadModel",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("parcel_handle_normalized", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("signal_key", models.CharField(blank=True, db_index=True, default="", max_length=180)),
                ("signal_type", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("dismissed", "Dismissed"), ("resolved", "Resolved")],
                        db_index=True,
                        default="active",
                        max_length=20,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[("info", "Info"), ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
                        db_index=True,
                        default="info",
                        max_length=20,
                    ),
                ),
                ("title", models.CharField(blank=True, default="", max_length=240)),
                ("summary", models.TextField(blank=True, default="")),
                ("event_key", models.CharField(blank=True, db_index=True, default="", max_length=180)),
                ("source_key", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("scope_jurisdiction", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("reconciled_state_version", models.CharField(blank=True, db_index=True, default="", max_length=160)),
                ("signal_set_version", models.CharField(blank=True, db_index=True, default="", max_length=160)),
                ("occurred_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("idempotency_key", models.CharField(blank=True, db_index=True, default="", max_length=180)),
                ("first_observed_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("last_observed_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "campaign",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="signal_read_models",
                        to="xyn_orchestrator.campaign",
                    ),
                ),
                (
                    "domain_event",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="signal_read_model",
                        to="xyn_orchestrator.platformdomainevent",
                    ),
                ),
                (
                    "parcel_identity",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="signal_read_models",
                        to="xyn_orchestrator.parcelcanonicalidentity",
                    ),
                ),
                (
                    "watch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="signal_read_models",
                        to="xyn_orchestrator.watchdefinition",
                    ),
                ),
                (
                    "watch_match_event",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="signal_read_models",
                        to="xyn_orchestrator.watchmatchevent",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="signal_read_models",
                        to="xyn_orchestrator.workspace",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at", "-last_observed_at", "-id"],
                "indexes": [
                    models.Index(fields=["workspace", "status", "last_observed_at"], name="ix_signal_read_status"),
                    models.Index(fields=["workspace", "signal_type", "last_observed_at"], name="ix_signal_read_type"),
                    models.Index(fields=["workspace", "parcel_handle_normalized", "last_observed_at"], name="ix_signal_read_handle"),
                    models.Index(fields=["workspace", "watch", "last_observed_at"], name="ix_signal_read_watch"),
                    models.Index(fields=["workspace", "campaign", "last_observed_at"], name="ix_signal_read_campaign"),
                    models.Index(fields=["workspace", "source_key", "last_observed_at"], name="ix_signal_read_source"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("idempotency_key__gt", "")),
                        fields=("workspace", "idempotency_key"),
                        name="uniq_signal_read_idempotency",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("signal_key__gt", "")),
                        fields=("workspace", "signal_key"),
                        name="uniq_signal_read_signal_key",
                    ),
                ],
            },
        ),
    ]
