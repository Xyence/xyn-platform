import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.text import slugify
from django_ckeditor_5.fields import CKEditor5Field


class Article(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    summary = models.TextField(blank=True)
    body = CKEditor5Field("body", config_name="default")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:220]
        if self.status == "published" and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def create_version_snapshot(self, source: str = "manual") -> "ArticleVersion":
        return ArticleVersion.objects.create(
            article=self,
            title=self.title,
            summary=self.summary,
            body=self.body,
            source=source,
        )

    def create_version_if_changed(self, source: str = "manual") -> bool:
        latest = (
            ArticleVersion.objects.filter(article=self)
            .order_by("-version_number")
            .first()
        )
        if not latest:
            self.create_version_snapshot(source=source)
            return True
        if (
            latest.title != self.title
            or latest.summary != self.summary
            or latest.body != self.body
        ):
            self.create_version_snapshot(source=source)
            return True
        return False


class ArticleVersion(models.Model):
    SOURCE_CHOICES = [
        ("ai", "AI"),
        ("manual", "Manual"),
    ]

    article = models.ForeignKey(Article, related_name="versions", on_delete=models.CASCADE)
    version_number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    body = CKEditor5Field("body", config_name="default")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="ai")
    prompt = models.TextField(blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("article", "version_number")

    def __str__(self) -> str:
        return f"{self.article.title} v{self.version_number}"

    def save(self, *args, **kwargs):
        if not self.version_number:
            latest = (
                ArticleVersion.objects.filter(article=self.article)
                .aggregate(max_version=Max("version_number"))
                .get("max_version")
            )
            self.version_number = (latest or 0) + 1
        super().save(*args, **kwargs)


class OpenAIConfig(models.Model):
    name = models.CharField(max_length=100, default="default")
    api_key = models.TextField()
    default_model = models.CharField(max_length=100, default="gpt-5.2")
    persistent_context = models.TextField(blank=True)
    system_instructions = models.TextField(
        default=(
            "You are assisting in drafting technical articles for Xyence, a CTO and "
            "platform consulting firm. Output a JSON object with a title, summary, "
            "and HTML body suitable for a website article. Treat the response as a "
            "draft artifact that will be versioned in a CMS."
        )
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"OpenAI Config ({self.name})"


class VoiceNote(models.Model):
    STATUS_CHOICES = [
        ("uploaded", "Uploaded"),
        ("queued", "Queued"),
        ("transcribing", "Transcribing"),
        ("transcribed", "Transcribed"),
        ("drafting", "Drafting"),
        ("ready", "Ready"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200, blank=True)
    audio_file = models.FileField(upload_to="voice_notes/")
    mime_type = models.CharField(max_length=100, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    language_code = models.CharField(max_length=20, default="en-US")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="uploaded")
    job_id = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="voice_notes"
    )

    def __str__(self) -> str:
        return self.title or f"Voice note {self.id}"


class VoiceTranscript(models.Model):
    PROVIDER_CHOICES = [
        ("google_stt", "Google Speech-to-Text"),
        ("stub", "Stub"),
    ]

    voice_note = models.OneToOneField(VoiceNote, on_delete=models.CASCADE, related_name="transcript")
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES, default="stub")
    transcript_text = models.TextField()
    confidence = models.FloatField(null=True, blank=True)
    raw_response_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Transcript for {self.voice_note_id}"


class Blueprint(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("archived", "Archived"),
        ("deprovisioning", "Deprovisioning"),
        ("deprovisioned", "Deprovisioned"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    namespace = models.CharField(max_length=120, default="core")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    archived_at = models.DateTimeField(null=True, blank=True)
    deprovisioned_at = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    spec_text = models.TextField(blank=True)
    repo_slug = models.CharField(max_length=120, blank=True, default="")
    blueprint_family_id = models.CharField(max_length=120, blank=True, default="")
    derived_from_artifact = models.ForeignKey(
        "Artifact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="derived_blueprints",
    )
    artifact = models.OneToOneField(
        "Artifact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_blueprint",
    )
    metadata_json = models.JSONField(null=True, blank=True)
    deprovision_last_run = models.ForeignKey(
        "Run", null=True, blank=True, on_delete=models.SET_NULL, related_name="blueprints_deprovisioned"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="blueprints_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="blueprints_updated"
    )

    class Meta:
        unique_together = ("name", "namespace")

    @staticmethod
    def _default_repo_slug(name: str) -> str:
        value = slugify(name or "") or "blueprint"
        return value[:120] or "blueprint"

    def save(self, *args, **kwargs):
        if not self.repo_slug:
            self.repo_slug = self._default_repo_slug(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.namespace}.{self.name}"


class BlueprintRevision(models.Model):
    blueprint = models.ForeignKey(Blueprint, on_delete=models.CASCADE, related_name="revisions")
    revision = models.PositiveIntegerField()
    spec_json = models.JSONField()
    blueprint_kind = models.CharField(
        max_length=20,
        choices=[
            ("solution", "Solution"),
            ("module", "Module"),
            ("bundle", "Bundle"),
        ],
        default="solution",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="blueprint_revisions_created"
    )

    class Meta:
        unique_together = ("blueprint", "revision")
        ordering = ["-revision"]

    def __str__(self) -> str:
        return f"{self.blueprint} v{self.revision}"


class BlueprintDraftSession(models.Model):
    STATUS_CHOICES = [
        ("drafting", "Drafting"),
        ("queued", "Queued"),
        ("ready", "Ready"),
        ("ready_with_errors", "Ready with errors"),
        ("published", "Published"),
        ("archived", "Archived"),
        ("failed", "Failed"),
    ]
    KIND_CHOICES = [
        ("solution", "Solution"),
        ("module", "Module"),
        ("bundle", "Bundle"),
    ]
    DRAFT_KIND_CHOICES = [
        ("blueprint", "Blueprint"),
        ("solution", "Solution"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=200, blank=True)
    blueprint = models.ForeignKey(
        Blueprint, null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_sessions_source"
    )
    draft_kind = models.CharField(max_length=20, choices=DRAFT_KIND_CHOICES, default="blueprint")
    blueprint_kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="solution")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="drafting")
    namespace = models.CharField(max_length=120, blank=True)
    project_key = models.CharField(max_length=200, blank=True)
    initial_prompt = models.TextField(blank=True)
    initial_prompt_locked = models.BooleanField(default=False)
    revision_instruction = models.TextField(blank=True)
    selected_context_pack_ids = models.JSONField(default=list, blank=True)
    source_artifacts = models.JSONField(default=list, blank=True)
    has_generated_output = models.BooleanField(default=False)
    submitted_payload_json = models.JSONField(null=True, blank=True)
    current_draft_json = models.JSONField(null=True, blank=True)
    requirements_summary = models.TextField(blank=True)
    validation_errors_json = models.JSONField(null=True, blank=True)
    suggested_fixes_json = models.JSONField(null=True, blank=True)
    diff_summary = models.TextField(blank=True)
    job_id = models.CharField(max_length=100, blank=True)
    last_error = models.TextField(blank=True)
    context_pack_ids = models.JSONField(default=list, blank=True)
    context_pack_refs_json = models.JSONField(null=True, blank=True)
    effective_context_hash = models.CharField(max_length=64, blank=True)
    effective_context_preview = models.TextField(blank=True)
    context_resolved_at = models.DateTimeField(null=True, blank=True)
    linked_blueprint = models.ForeignKey(
        Blueprint, null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_sessions"
    )
    artifact = models.OneToOneField(
        "Artifact",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_draft_session",
    )
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_sessions_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_sessions_updated"
    )

    def __str__(self) -> str:
        return self.name


class DraftSessionVoiceNote(models.Model):
    draft_session = models.ForeignKey(BlueprintDraftSession, on_delete=models.CASCADE)
    voice_note = models.ForeignKey(VoiceNote, on_delete=models.CASCADE)
    ordering = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("draft_session", "voice_note")
        ordering = ["ordering"]

    def __str__(self) -> str:
        return f"{self.draft_session} -> {self.voice_note}"


class DraftSessionRevision(models.Model):
    ACTION_CHOICES = [
        ("generate", "Generate"),
        ("revise", "Revise"),
        ("save", "Save"),
        ("snapshot", "Snapshot"),
        ("submit", "Submit"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft_session = models.ForeignKey(BlueprintDraftSession, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default="save")
    instruction = models.TextField(blank=True)
    draft_json = models.JSONField(null=True, blank=True)
    requirements_summary = models.TextField(blank=True)
    diff_summary = models.TextField(blank=True)
    validation_errors_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_session_revisions_created"
    )

    class Meta:
        ordering = ["-revision_number", "-created_at"]
        unique_together = ("draft_session", "revision_number")

    def __str__(self) -> str:
        return f"{self.draft_session_id} r{self.revision_number}"

class BlueprintInstance(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("planned", "Planned"),
        ("applied", "Applied"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blueprint = models.ForeignKey(Blueprint, on_delete=models.CASCADE, related_name="instances")
    revision = models.PositiveIntegerField()
    release_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    plan_id = models.CharField(max_length=100, blank=True)
    operation_id = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="blueprint_instances_created"
    )

    def __str__(self) -> str:
        return f"{self.blueprint} -> {self.release_id or self.id}"


class ReleaseTarget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blueprint = models.ForeignKey(Blueprint, on_delete=models.CASCADE, related_name="release_targets")
    name = models.CharField(max_length=200)
    environment = models.CharField(max_length=120, blank=True)
    target_instance_ref = models.CharField(max_length=120, blank=True)
    target_instance = models.ForeignKey(
        "ProvisionedInstance", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_targets"
    )
    fqdn = models.CharField(max_length=200)
    dns_json = models.JSONField(null=True, blank=True)
    runtime_json = models.JSONField(null=True, blank=True)
    tls_json = models.JSONField(null=True, blank=True)
    env_json = models.JSONField(null=True, blank=True)
    secret_refs_json = models.JSONField(null=True, blank=True)
    config_json = models.JSONField(null=True, blank=True)
    auto_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_targets_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_targets_updated"
    )

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("blueprint", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["blueprint", "environment"],
                condition=models.Q(auto_generated=True),
                name="uniq_auto_release_target_per_bp_env",
            )
        ]

    def __str__(self) -> str:
        return f"{self.blueprint} target {self.name}"


class IdentityProvider(models.Model):
    id = models.CharField(primary_key=True, max_length=120)
    display_name = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True)
    issuer = models.URLField()
    discovery_json = models.JSONField(null=True, blank=True)
    client_id = models.CharField(max_length=240)
    client_secret_ref_json = models.JSONField(null=True, blank=True)
    scopes_json = models.JSONField(null=True, blank=True)
    pkce_enabled = models.BooleanField(default=True)
    prompt = models.CharField(max_length=40, blank=True)
    domain_rules_json = models.JSONField(null=True, blank=True)
    claims_json = models.JSONField(null=True, blank=True)
    audience_rules_json = models.JSONField(null=True, blank=True)
    fallback_default_role_id = models.CharField(max_length=120, null=True, blank=True)
    require_group_match = models.BooleanField(default=False)
    group_claim_path = models.CharField(max_length=240, default="groups")
    group_role_mappings_json = models.JSONField(default=list, blank=True)
    cached_discovery_doc = models.JSONField(null=True, blank=True)
    cached_jwks = models.JSONField(null=True, blank=True)
    last_discovery_refresh_at = models.DateTimeField(null=True, blank=True)
    jwks_cached_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="identity_providers_created"
    )

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.display_name or self.id


class AppOIDCClient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app_id = models.CharField(max_length=120)
    login_mode = models.CharField(max_length=40, default="redirect")
    default_provider = models.ForeignKey(
        IdentityProvider, null=True, blank=True, on_delete=models.SET_NULL, related_name="default_for_apps"
    )
    allowed_providers_json = models.JSONField(null=True, blank=True)
    redirect_uris_json = models.JSONField(null=True, blank=True)
    post_logout_redirect_uris_json = models.JSONField(null=True, blank=True)
    session_json = models.JSONField(null=True, blank=True)
    token_validation_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="oidc_clients_created"
    )

    class Meta:
        ordering = ["app_id", "-created_at"]

    def __str__(self) -> str:
        return self.app_id


class SecretStore(models.Model):
    KIND_CHOICES = [
        ("aws_secrets_manager", "AWS Secrets Manager"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=60, choices=KIND_CHOICES, default="aws_secrets_manager")
    is_default = models.BooleanField(default=False)
    config_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="xyn_single_default_secret_store",
            )
        ]

    def clean(self):
        if self.is_default:
            existing = SecretStore.objects.filter(is_default=True)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({"is_default": "Only one default secret store is allowed."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class SecretRef(models.Model):
    SCOPE_CHOICES = [
        ("platform", "Platform"),
        ("tenant", "Tenant"),
        ("user", "User"),
        ("team", "Team"),
    ]
    TYPE_CHOICES = [
        ("secrets_manager", "Secrets Manager"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=240)
    scope_kind = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    scope_id = models.UUIDField(null=True, blank=True)
    store = models.ForeignKey(SecretStore, on_delete=models.CASCADE, related_name="secret_refs")
    external_ref = models.CharField(max_length=512)
    type = models.CharField(max_length=40, choices=TYPE_CHOICES, default="secrets_manager")
    version = models.CharField(max_length=120, null=True, blank=True)
    description = models.CharField(max_length=500, blank=True)
    metadata_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="secret_refs_created"
    )

    class Meta:
        ordering = ["scope_kind", "name"]
        unique_together = ("scope_kind", "scope_id", "name")

    def clean(self):
        if self.scope_kind == "platform" and self.scope_id is not None:
            raise ValidationError({"scope_id": "scope_id must be null for platform scope."})
        if self.scope_kind != "platform" and self.scope_id is None:
            raise ValidationError({"scope_id": "scope_id is required for non-platform scopes."})
        existing = SecretRef.objects.filter(scope_kind=self.scope_kind, name=self.name)
        if self.scope_id is None:
            existing = existing.filter(scope_id__isnull=True)
        else:
            existing = existing.filter(scope_id=self.scope_id)
        if self.pk:
            existing = existing.exclude(pk=self.pk)
        if existing.exists():
            raise ValidationError({"name": "Secret name already exists for this scope."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.scope_kind}:{self.name}"


class UserIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_id = models.CharField(max_length=120, blank=True)
    provider = models.CharField(max_length=50)
    issuer = models.CharField(max_length=240)
    subject = models.CharField(max_length=240)
    email = models.CharField(max_length=240, blank=True)
    display_name = models.CharField(max_length=240, blank=True)
    claims_json = models.JSONField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("issuer", "subject")
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.provider}:{self.subject}"


class RoleBinding(models.Model):
    SCOPE_CHOICES = [
        ("platform", "Platform"),
        ("tenant", "Tenant"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_identity = models.ForeignKey(
        UserIdentity, on_delete=models.CASCADE, related_name="role_bindings"
    )
    scope_kind = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="platform")
    scope_id = models.UUIDField(null=True, blank=True)
    role = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user_identity", "scope_kind", "scope_id", "role")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_identity_id} {self.role}"


class Module(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("deprecated", "Deprecated"),
        ("archived", "Archived"),
    ]
    TYPE_CHOICES = [
        ("adapter", "Adapter"),
        ("service", "Service"),
        ("ui", "UI"),
        ("workflow", "Workflow"),
        ("schema", "Schema"),
        ("infra", "Infra"),
        ("lib", "Lib"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    namespace = models.CharField(max_length=120)
    name = models.CharField(max_length=120)
    fqn = models.CharField(max_length=240, unique=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    current_version = models.CharField(max_length=64)
    latest_module_spec_json = models.JSONField(null=True, blank=True)
    capabilities_provided_json = models.JSONField(null=True, blank=True)
    interfaces_json = models.JSONField(null=True, blank=True)
    dependencies_json = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="modules_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="modules_updated"
    )

    class Meta:
        unique_together = ("namespace", "name")
        ordering = ["namespace", "name"]

    def __str__(self) -> str:
        return self.fqn


class Bundle(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("deprecated", "Deprecated"),
        ("archived", "Archived"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    namespace = models.CharField(max_length=120)
    name = models.CharField(max_length=120)
    fqn = models.CharField(max_length=240, unique=True)
    current_version = models.CharField(max_length=64)
    bundle_spec_json = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="bundles_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="bundles_updated"
    )

    class Meta:
        unique_together = ("namespace", "name")
        ordering = ["namespace", "name"]

    def __str__(self) -> str:
        return self.fqn


class Capability(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=64, default="1.0")
    profiles_json = models.JSONField(null=True, blank=True)
    capability_spec_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


class Environment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    base_domain = models.CharField(max_length=200, blank=True)
    aws_region = models.CharField(max_length=50, blank=True)
    metadata_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Tenant(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("suspended", "Suspended"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    metadata_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Contact(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=200)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    role_title = models.CharField(max_length=120, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    metadata_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant.name})"


class TenantMembership(models.Model):
    ROLE_CHOICES = [
        ("tenant_admin", "Tenant Admin"),
        ("tenant_operator", "Tenant Operator"),
        ("tenant_viewer", "Tenant Viewer"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user_identity = models.ForeignKey(UserIdentity, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=40, choices=ROLE_CHOICES, default="tenant_viewer")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant__name"]
        unique_together = ("tenant", "user_identity")

    def __str__(self) -> str:
        return f"{self.tenant.name} - {self.user_identity.email or self.user_identity.subject}"


class Workspace(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("deprecated", "Deprecated"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=200)
    org_name = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    kind = models.CharField(max_length=64, default="customer")
    lifecycle_stage = models.CharField(max_length=64, default="prospect")
    parent_workspace = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    auth_mode = models.CharField(max_length=20, default="local")
    oidc_config_ref = models.CharField(max_length=255, blank=True, default="")
    oidc_enabled = models.BooleanField(default=False)
    oidc_issuer_url = models.URLField(blank=True, default="")
    oidc_client_id = models.CharField(max_length=255, blank=True, default="")
    oidc_client_secret_ref = models.ForeignKey(
        SecretRef,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workspace_oidc_policies",
    )
    oidc_scopes = models.CharField(max_length=255, default="openid profile email")
    oidc_claim_email = models.CharField(max_length=120, default="email")
    oidc_allow_auto_provision = models.BooleanField(default=False)
    oidc_allowed_email_domains_json = models.JSONField(default=list, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WorkspaceMembership(models.Model):
    ROLE_CHOICES = [
        ("reader", "Reader"),
        ("contributor", "Contributor"),
        ("publisher", "Publisher"),
        ("moderator", "Moderator"),
        ("admin", "Admin"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user_identity = models.ForeignKey(UserIdentity, on_delete=models.CASCADE, related_name="workspace_memberships")
    role = models.CharField(max_length=40, choices=ROLE_CHOICES, default="reader")
    termination_authority = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["workspace__name", "user_identity__email"]
        unique_together = ("workspace", "user_identity")

    def __str__(self) -> str:
        return f"{self.workspace.slug}:{self.user_identity_id}:{self.role}"


class ArtifactType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=120, blank=True)
    schema_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ArticleCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Artifact(models.Model):
    ARTIFACT_STATE_CHOICES = [
        ("provisional", "Provisional"),
        ("canonical", "Canonical"),
        ("immutable", "Immutable"),
        ("deprecated", "Deprecated"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("reviewed", "Reviewed"),
        ("ratified", "Ratified"),
        ("published", "Published"),
        ("deprecated", "Deprecated"),
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("error", "Error"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="artifacts")
    type = models.ForeignKey(ArtifactType, on_delete=models.PROTECT, related_name="artifacts")
    article_category = models.ForeignKey(
        ArticleCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="artifacts"
    )
    artifact_state = models.CharField(max_length=20, choices=ARTIFACT_STATE_CHOICES, default="provisional")
    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True, default="")
    schema_version = models.CharField(max_length=80, blank=True, default="")
    content_hash = models.CharField(max_length=128, blank=True, default="")
    validation_status = models.CharField(
        max_length=20,
        choices=[
            ("pass", "Pass"),
            ("fail", "Fail"),
            ("warning", "Warning"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
    )
    validation_errors_json = models.JSONField(null=True, blank=True)
    tags_json = models.JSONField(default=list, blank=True)
    slug = models.SlugField(max_length=240, blank=True, default="")
    source_ref_type = models.CharField(max_length=80, blank=True, default="")
    source_ref_id = models.CharField(max_length=120, blank=True, default="")
    family_id = models.CharField(max_length=120, blank=True, default="")
    parent_artifact = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="derived_artifacts",
    )
    lineage_root = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lineage_descendants",
    )
    format = models.CharField(
        max_length=30,
        choices=[
            ("standard", "Standard"),
            ("video_explainer", "Video Explainer"),
            ("workflow", "Workflow"),
        ],
        default="standard",
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    version = models.PositiveIntegerField(default=1)
    package_version = models.CharField(max_length=40, blank=True, default="")
    content_ref = models.JSONField(null=True, blank=True)
    dependencies = models.JSONField(default=list, blank=True)
    bindings = models.JSONField(default=list, blank=True)
    lineage_json = models.JSONField(null=True, blank=True)
    author = models.ForeignKey(UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="artifacts_authored")
    custodian = models.ForeignKey(UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="artifacts_custodied")
    ratified_by = models.ForeignKey(UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="artifacts_ratified")
    ratified_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    visibility = models.CharField(max_length=30, default="private")
    verifiers_required_json = models.JSONField(default=list, blank=True)
    verifiers_satisfied_json = models.JSONField(default=list, blank=True)
    provenance_json = models.JSONField(default=dict, blank=True)
    scope_json = models.JSONField(default=dict, blank=True)
    video_spec_json = models.JSONField(null=True, blank=True)
    workflow_profile = models.CharField(max_length=40, blank=True, default="")
    workflow_spec_json = models.JSONField(null=True, blank=True)
    workflow_state_schema_version = models.PositiveIntegerField(null=True, blank=True)
    video_ai_config_json = models.JSONField(null=True, blank=True)
    video_context_pack = models.ForeignKey(
        "ContextPack",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="video_articles",
    )
    video_latest_render = models.ForeignKey(
        "VideoRender",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                condition=~Q(slug=""),
                name="uniq_artifact_workspace_slug",
            ),
            models.UniqueConstraint(
                fields=["source_ref_type", "source_ref_id"],
                condition=(~Q(source_ref_type="") & ~Q(source_ref_id="")),
                name="uniq_artifact_source_ref",
            ),
            models.UniqueConstraint(
                fields=["family_id", "artifact_state"],
                condition=(~Q(family_id="") & Q(artifact_state="canonical")),
                name="uniq_artifact_canonical_per_family",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class WorkspaceArtifactBinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="artifact_bindings")
    artifact = models.ForeignKey("Artifact", on_delete=models.CASCADE, related_name="workspace_bindings")
    enabled = models.BooleanField(default=True)
    installed_state = models.CharField(max_length=40, default="installed")
    config_ref = models.CharField(max_length=240, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "artifact"],
                name="uniq_workspace_artifact_binding",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.workspace_id}:{self.artifact_id}"


class ArtifactSurface(models.Model):
    SURFACE_KIND_CHOICES = [
        ("config", "Config"),
        ("editor", "Editor"),
        ("dashboard", "Dashboard"),
        ("visualizer", "Visualizer"),
        ("docs", "Docs"),
    ]
    NAV_VISIBILITY_CHOICES = [
        ("hidden", "Hidden"),
        ("contextual", "Contextual"),
        ("always", "Always"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="surfaces")
    key = models.CharField(max_length=120)
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True, default="")
    surface_kind = models.CharField(max_length=20, choices=SURFACE_KIND_CHOICES, default="editor")
    route = models.CharField(max_length=280)
    nav_visibility = models.CharField(max_length=20, choices=NAV_VISIBILITY_CHOICES, default="hidden")
    nav_label = models.CharField(max_length=120, blank=True, default="")
    nav_icon = models.CharField(max_length=120, blank=True, default="")
    nav_group = models.CharField(max_length=120, blank=True, default="")
    renderer = models.JSONField(default=dict, blank=True)
    context = models.JSONField(default=dict, blank=True)
    permissions = models.JSONField(default=dict, blank=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "key"]
        unique_together = ("artifact", "key")
        constraints = [
            models.UniqueConstraint(
                fields=["route"],
                condition=~Q(route=""),
                name="uniq_artifact_surface_route",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.artifact_id}:{self.key}"


class ArtifactRuntimeRole(models.Model):
    ROLE_KIND_CHOICES = [
        ("route_provider", "Route Provider"),
        ("job", "Job"),
        ("event_handler", "Event Handler"),
        ("integration", "Integration"),
        ("auth", "Auth"),
        ("data_model", "Data Model"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="runtime_roles")
    role_kind = models.CharField(max_length=40, choices=ROLE_KIND_CHOICES)
    spec = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role_kind", "id"]

    def __str__(self) -> str:
        return f"{self.artifact_id}:{self.role_kind}"


class ArtifactRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    content_json = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="artifact_revisions_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision_number"]
        unique_together = ("artifact", "revision_number")

    def __str__(self) -> str:
        return f"{self.artifact_id}:r{self.revision_number}"


class VideoRender(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("filtered", "Filtered"),
        ("canceled", "Canceled"),
    ]
    OUTCOME_CHOICES = [
        ("success", "Success"),
        ("failed", "Failed"),
        ("filtered", "Filtered"),
        ("canceled", "Canceled"),
        ("timeout", "Timeout"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="video_renders")
    provider = models.CharField(max_length=80, default="unknown")
    model_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    request_payload_json = models.JSONField(default=dict, blank=True)
    result_payload_json = models.JSONField(default=dict, blank=True)
    output_assets = models.JSONField(default=list, blank=True)
    context_pack = models.ForeignKey(
        "ContextPack",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="video_renders",
    )
    context_pack_version = models.CharField(max_length=64, blank=True)
    context_pack_updated_at = models.DateTimeField(null=True, blank=True)
    context_pack_hash = models.CharField(max_length=64, blank=True)
    spec_snapshot_hash = models.CharField(max_length=64, blank=True)
    input_snapshot_hash = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, blank=True, default="")
    provider_operation_name = models.CharField(max_length=255, blank=True)
    provider_operation_id = models.CharField(max_length=120, blank=True)
    provider_filtered_count = models.PositiveIntegerField(null=True, blank=True)
    provider_filtered_reasons = models.JSONField(default=list, blank=True)
    provider_error_code = models.CharField(max_length=80, blank=True)
    provider_error_message = models.TextField(blank=True)
    provider_response_excerpt = models.JSONField(default=dict, blank=True)
    last_provider_status_at = models.DateTimeField(null=True, blank=True)
    export_package_generated = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    error_details_json = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self) -> str:
        return f"{self.article_id}:{self.status}:{self.provider}"


class WorkflowRun(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("aborted", "Aborted"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow_artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="workflow_runs")
    user = models.ForeignKey(UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="workflow_runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.workflow_artifact_id}:{self.status}:{self.id}"


class WorkflowRunEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="events")
    step_id = models.CharField(max_length=120, blank=True)
    event_type = models.CharField(max_length=80)
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.event_type}:{self.step_id}"


class IntentScript(models.Model):
    SCOPE_CHOICES = [
        ("tour", "Tour"),
        ("artifact", "Artifact"),
        ("manual", "Manual"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("final", "Final"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=240)
    scope_type = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    scope_ref_id = models.CharField(max_length=120)
    format_version = models.CharField(max_length=40, default="1")
    script_json = models.JSONField(default=dict, blank=True)
    script_text = models.TextField(blank=True, default="")
    artifact = models.ForeignKey(Artifact, null=True, blank=True, on_delete=models.SET_NULL, related_name="intent_scripts")
    created_by = models.ForeignKey(
        "xyn_orchestrator.UserIdentity",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="intent_scripts_created",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.scope_type}:{self.scope_ref_id}:{self.title}"


class ArtifactEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=120)
    actor = models.ForeignKey(UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="artifact_events")
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.artifact_id}:{self.event_type}"


class LedgerEvent(models.Model):
    ACTION_CHOICES = [
        ("artifact.create", "Artifact Create"),
        ("artifact.update", "Artifact Update"),
        ("artifact.canonize", "Artifact Canonize"),
        ("artifact.deprecate", "Artifact Deprecate"),
        ("artifact.archive", "Artifact Archive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_user = models.ForeignKey(UserIdentity, on_delete=models.PROTECT, related_name="ledger_events")
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="ledger_events")
    artifact_type = models.CharField(max_length=80, blank=True, default="")
    artifact_state = models.CharField(max_length=20, blank=True, default="")
    parent_artifact = models.ForeignKey(
        Artifact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_child_events",
    )
    lineage_root = models.ForeignKey(
        Artifact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_lineage_events",
    )
    summary = models.CharField(max_length=280, blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=320, blank=True, default="")
    source_ref_type = models.CharField(max_length=80, blank=True, default="")
    source_ref_id = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="uniq_ledger_event_dedupe_key",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action}:{self.artifact_id}:{self.created_at.isoformat()}"


class ArtifactLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    from_artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="links_from")
    to_artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="links_to")
    link_type = models.CharField(max_length=120)

    class Meta:
        unique_together = ("from_artifact", "to_artifact", "link_type")

    def __str__(self) -> str:
        return f"{self.from_artifact_id}->{self.to_artifact_id}:{self.link_type}"


class ArtifactExternalRef(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="external_refs")
    system = models.CharField(max_length=60, default="django")
    external_id = models.CharField(max_length=120)
    slug_path = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("system", "external_id")
        constraints = [
            models.UniqueConstraint(fields=["system", "slug_path"], condition=~Q(slug_path=""), name="uniq_artifact_extref_slug")
        ]

    def __str__(self) -> str:
        return f"{self.system}:{self.external_id}"


class ArtifactReaction(models.Model):
    VALUE_CHOICES = [
        ("endorse", "Endorse"),
        ("oppose", "Oppose"),
        ("neutral", "Neutral"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(UserIdentity, on_delete=models.CASCADE, related_name="artifact_reactions")
    value = models.CharField(max_length=20, choices=VALUE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("artifact", "user")


class ArtifactComment(models.Model):
    STATUS_CHOICES = [
        ("visible", "Visible"),
        ("hidden", "Hidden"),
        ("deleted", "Deleted"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="artifact_comments")
    parent_comment = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="visible")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class PublishBinding(models.Model):
    SCOPE_TYPE_CHOICES = [
        ("category", "Category"),
        ("article", "Article"),
    ]
    TARGET_TYPE_CHOICES = [
        ("xyn_ui_route", "Xyn UI Route"),
        ("public_web_path", "Public Web Path"),
        ("external_url", "External URL"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope_type = models.CharField(max_length=20, choices=SCOPE_TYPE_CHOICES)
    scope_id = models.UUIDField()
    target_type = models.CharField(max_length=30, choices=TARGET_TYPE_CHOICES)
    target_value = models.CharField(max_length=500)
    label = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label", "target_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["scope_type", "scope_id", "target_type", "target_value"],
                name="uniq_publish_binding_scope_target",
            )
        ]

    def __str__(self) -> str:
        return f"{self.scope_type}:{self.scope_id}:{self.target_value}"


class BrandProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="brand_profile")
    display_name = models.CharField(max_length=200, null=True, blank=True)
    logo_url = models.CharField(max_length=500, null=True, blank=True)
    primary_color = models.CharField(max_length=40, null=True, blank=True)
    secondary_color = models.CharField(max_length=40, null=True, blank=True)
    theme_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant__name"]

    def __str__(self) -> str:
        return f"{self.tenant.name} branding"


class PlatformBranding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand_name = models.CharField(max_length=200, default="Xyn")
    logo_url = models.CharField(max_length=500, null=True, blank=True)
    favicon_url = models.CharField(max_length=500, null=True, blank=True)
    primary_color = models.CharField(max_length=40, default="#0f4c81")
    background_color = models.CharField(max_length=40, default="#f5f7fb")
    background_gradient = models.CharField(max_length=240, null=True, blank=True)
    text_color = models.CharField(max_length=40, default="#10203a")
    font_family = models.CharField(max_length=120, null=True, blank=True)
    button_radius_px = models.IntegerField(default=12)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="platform_branding_updates"
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.brand_name


class AppBrandingOverride(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app_id = models.CharField(max_length=120, unique=True)
    display_name = models.CharField(max_length=200, null=True, blank=True)
    logo_url = models.CharField(max_length=500, null=True, blank=True)
    primary_color = models.CharField(max_length=40, null=True, blank=True)
    background_color = models.CharField(max_length=40, null=True, blank=True)
    background_gradient = models.CharField(max_length=240, null=True, blank=True)
    text_color = models.CharField(max_length=40, null=True, blank=True)
    font_family = models.CharField(max_length=120, null=True, blank=True)
    button_radius_px = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="app_branding_updates"
    )

    class Meta:
        ordering = ["app_id"]

    def __str__(self) -> str:
        return self.app_id


class Device(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("offline", "Offline"),
        ("unknown", "Unknown"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=200)
    device_type = models.CharField(max_length=120)
    mgmt_ip = models.CharField(max_length=120, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="unknown")
    tags = models.JSONField(null=True, blank=True)
    metadata_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("tenant", "name")
        indexes = [models.Index(fields=["tenant", "status"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant.name})"


class DraftAction(models.Model):
    ACTION_CLASS_CHOICES = [
        ("read_only", "Read Only"),
        ("write_proposed", "Write Proposed"),
        ("write_execute", "Write Execute"),
        ("account_security_write", "Account Security Write"),
    ]
    ACTION_TYPE_CHOICES = [
        ("device.reboot", "Device Reboot"),
        ("device.factory_reset", "Device Factory Reset"),
        ("device.push_config", "Device Push Config"),
        ("credential_ref.attach", "Credential Ref Attach"),
        ("adapter.enable", "Adapter Enable"),
        ("adapter.configure", "Adapter Configure"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending_verification", "Pending Verification"),
        ("pending_ratification", "Pending Ratification"),
        ("executing", "Executing"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("canceled", "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="draft_actions")
    device = models.ForeignKey(Device, null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_actions")
    instance_ref = models.CharField(max_length=120, blank=True, default="")
    action_type = models.CharField(max_length=120, choices=ACTION_TYPE_CHOICES)
    action_class = models.CharField(max_length=40, choices=ACTION_CLASS_CHOICES)
    params_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default="draft")
    requested_by = models.ForeignKey(
        UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_actions_requested"
    )
    custodian = models.ForeignKey(
        UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_actions_custodied"
    )
    last_error_code = models.CharField(max_length=120, blank=True, default="")
    last_error_message = models.TextField(blank=True, default="")
    provenance_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "status"]), models.Index(fields=["device", "created_at"])]

    def __str__(self) -> str:
        return f"{self.action_type}:{self.id}"


class ActionVerifierEvidence(models.Model):
    STATUS_CHOICES = [
        ("required", "Required"),
        ("satisfied", "Satisfied"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft_action = models.ForeignKey(DraftAction, on_delete=models.CASCADE, related_name="verifier_evidence")
    verifier_type = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="required")
    evidence_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["draft_action", "verifier_type"])]


class RatificationEvent(models.Model):
    METHOD_CHOICES = [
        ("ui_confirm", "UI Confirm"),
        ("admin_override", "Admin Override"),
        ("policy_auto", "Policy Auto"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft_action = models.ForeignKey(DraftAction, on_delete=models.CASCADE, related_name="ratification_events")
    ratified_by = models.ForeignKey(
        UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="ratifications"
    )
    ratified_at = models.DateTimeField(default=timezone.now)
    method = models.CharField(max_length=40, choices=METHOD_CHOICES, default="ui_confirm")
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-ratified_at"]


class ExecutionReceipt(models.Model):
    OUTCOME_CHOICES = [
        ("success", "Success"),
        ("failure", "Failure"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft_action = models.ForeignKey(DraftAction, on_delete=models.CASCADE, related_name="receipts")
    executed_at = models.DateTimeField(default=timezone.now)
    executed_by = models.ForeignKey(
        UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="execution_receipts"
    )
    adapter_key = models.CharField(max_length=120, blank=True, default="")
    request_payload_redacted_json = models.JSONField(default=dict, blank=True)
    response_redacted_json = models.JSONField(default=dict, blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES)
    error_code = models.CharField(max_length=120, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    logs_ref = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-executed_at"]


class DraftActionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft_action = models.ForeignKey(DraftAction, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=120)
    from_status = models.CharField(max_length=40, blank=True, default="")
    to_status = models.CharField(max_length=40, blank=True, default="")
    actor = models.ForeignKey(
        UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="draft_action_events"
    )
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["draft_action", "created_at"])]


class ReleasePlan(models.Model):
    TARGET_CHOICES = [
        ("module", "Module"),
        ("bundle", "Bundle"),
        ("release", "Release"),
        ("blueprint", "Blueprint"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    target_kind = models.CharField(max_length=20, choices=TARGET_CHOICES)
    target_fqn = models.CharField(max_length=240)
    from_version = models.CharField(max_length=64, blank=True)
    to_version = models.CharField(max_length=64)
    milestones_json = models.JSONField(null=True, blank=True)
    blueprint = models.ForeignKey(
        "Blueprint", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_plans"
    )
    environment = models.ForeignKey(
        "Environment", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_plans"
    )
    last_run = models.ForeignKey(
        "Run", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_plans"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_plans_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="release_plans_updated"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.target_kind}:{self.target_fqn} {self.from_version}->{self.to_version}"


class Release(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("deprecated", "Deprecated"),
    ]
    BUILD_STATE_CHOICES = [
        ("draft", "Draft"),
        ("building", "Building"),
        ("ready", "Ready"),
        ("failed", "Failed"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blueprint = models.ForeignKey(
        "Blueprint", null=True, blank=True, on_delete=models.SET_NULL, related_name="releases"
    )
    version = models.CharField(max_length=64)
    release_plan = models.ForeignKey(
        ReleasePlan, null=True, blank=True, on_delete=models.SET_NULL, related_name="releases"
    )
    created_from_run = models.ForeignKey(
        "Run", null=True, blank=True, on_delete=models.SET_NULL, related_name="releases"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    build_state = models.CharField(max_length=20, choices=BUILD_STATE_CHOICES, default="draft")
    artifacts_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="releases_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="releases_updated"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.version} ({self.status})"


class Registry(models.Model):
    TYPE_CHOICES = [
        ("module", "Module"),
        ("bundle", "Bundle"),
        ("blueprint", "Blueprint"),
        ("release", "Release"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("error", "Error"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    registry_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="registries_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="registries_updated"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Run(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    ENTITY_CHOICES = [
        ("blueprint", "Blueprint"),
        ("registry", "Registry"),
        ("module", "Module"),
        ("release_plan", "Release plan"),
        ("dev_task", "Dev task"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=30, choices=ENTITY_CHOICES)
    entity_id = models.UUIDField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    summary = models.CharField(max_length=240, blank=True)
    log_text = models.TextField(blank=True)
    error = models.TextField(blank=True)
    metadata_json = models.JSONField(null=True, blank=True)
    context_pack_refs_json = models.JSONField(null=True, blank=True)
    context_hash = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="runs_created"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.entity_id} ({self.status})"


class RunArtifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="artifacts")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=100, blank=True)
    url = models.TextField(blank=True)
    metadata_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.run_id})"


class RunCommandExecution(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="command_executions")
    step_name = models.CharField(max_length=120, blank=True)
    command_index = models.PositiveIntegerField(default=0)
    shell = models.CharField(max_length=40, default="sh")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    exit_code = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    ssm_command_id = models.CharField(max_length=120, blank=True)
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


class ReleasePlanDeployState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    release_plan = models.ForeignKey(ReleasePlan, on_delete=models.CASCADE, related_name="deploy_states")
    instance = models.ForeignKey(
        "ProvisionedInstance", on_delete=models.CASCADE, related_name="deploy_states"
    )
    last_applied_hash = models.CharField(max_length=64, blank=True)
    last_applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("release_plan", "instance")


class ReleasePlanDeployment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    release_plan = models.ForeignKey(ReleasePlan, on_delete=models.CASCADE, related_name="deployments")
    instance = models.ForeignKey(
        "ProvisionedInstance", on_delete=models.CASCADE, related_name="deployments"
    )
    last_applied_hash = models.CharField(max_length=64, blank=True)
    last_applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("release_plan", "instance")


class Deployment(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    KIND_CHOICES = [
        ("release", "Release"),
        ("release_plan", "Release plan"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=64, unique=True)
    idempotency_base = models.CharField(max_length=64, db_index=True)
    app_id = models.CharField(max_length=120, blank=True)
    environment = models.ForeignKey(
        "Environment", null=True, blank=True, on_delete=models.SET_NULL, related_name="deployments"
    )
    release = models.ForeignKey("Release", on_delete=models.CASCADE, related_name="deployments")
    instance = models.ForeignKey(
        "ProvisionedInstance", on_delete=models.CASCADE, related_name="deployment_records"
    )
    release_plan = models.ForeignKey(
        ReleasePlan, null=True, blank=True, on_delete=models.SET_NULL, related_name="deployment_records"
    )
    deploy_kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="release")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    submitted_by = models.CharField(max_length=120, blank=True)
    transport = models.CharField(max_length=40, default="ssm")
    transport_ref = models.JSONField(null=True, blank=True)
    health_check_status = models.CharField(max_length=20, blank=True)
    health_check_details_json = models.JSONField(null=True, blank=True)
    stdout_excerpt = models.TextField(blank=True)
    stderr_excerpt = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    artifacts_json = models.JSONField(null=True, blank=True)
    run = models.ForeignKey(Run, null=True, blank=True, on_delete=models.SET_NULL, related_name="deployments")
    rollback_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="rollback_attempts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

class ContextPack(models.Model):
    PURPOSE_CHOICES = [
        ("any", "Any"),
        ("planner", "Planner"),
        ("coder", "Coder"),
        ("deployer", "Deployer"),
        ("operator", "Operator"),
        ("video_explainer", "Video Explainer"),
        ("explainer_script", "Explainer Script"),
        ("explainer_storyboard", "Explainer Storyboard"),
        ("explainer_visual_prompts", "Explainer Visual Prompts"),
        ("explainer_narration", "Explainer Narration"),
        ("explainer_title_description", "Explainer Title Description"),
    ]
    SCOPE_CHOICES = [
        ("global", "Global"),
        ("namespace", "Namespace"),
        ("project", "Project"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    purpose = models.CharField(max_length=40, choices=PURPOSE_CHOICES, default="any")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    namespace = models.CharField(max_length=120, blank=True)
    project_key = models.CharField(max_length=120, blank=True)
    version = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    content_markdown = models.TextField()
    applies_to_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="context_packs_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="context_packs_updated"
    )
    seeded_by_pack_slug = models.CharField(max_length=200, blank=True)
    seeded_version = models.CharField(max_length=64, blank=True)
    seeded_content_hash = models.CharField(max_length=128, blank=True)
    seeded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("name", "version", "purpose", "scope", "namespace", "project_key")

    def __str__(self) -> str:
        return f"{self.name} ({self.scope}) v{self.version}"


class SeedPack(models.Model):
    SCOPE_CHOICES = [
        ("core", "Core"),
        ("optional", "Optional"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=160, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    version = models.CharField(max_length=64)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="optional")
    namespace = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"{self.slug}@{self.version}"


class SeedItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seed_pack = models.ForeignKey(SeedPack, on_delete=models.CASCADE, related_name="items")
    entity_type = models.CharField(max_length=60)
    entity_slug = models.CharField(max_length=200)
    entity_unique_key_json = models.JSONField(default=dict)
    payload_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seed_pack__slug", "entity_type", "entity_slug"]
        constraints = [
            models.UniqueConstraint(
                fields=["seed_pack", "entity_type", "entity_slug"],
                name="uniq_seed_item_per_pack_entity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.seed_pack.slug}:{self.entity_type}:{self.entity_slug}"


class SeedApplication(models.Model):
    STATUS_CHOICES = [
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seed_pack = models.ForeignKey(SeedPack, on_delete=models.CASCADE, related_name="applications")
    applied_at = models.DateTimeField(auto_now_add=True)
    applied_by = models.ForeignKey(
        "xyn_orchestrator.UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="seed_applications"
    )
    result_summary_json = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="succeeded")
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-applied_at"]

    def __str__(self) -> str:
        return f"{self.seed_pack.slug}:{self.status}@{self.applied_at.isoformat() if self.applied_at else 'n/a'}"


class SeedApplicationItem(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("unchanged", "Unchanged"),
        ("skipped", "Skipped"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seed_application = models.ForeignKey(SeedApplication, on_delete=models.CASCADE, related_name="items")
    seed_item = models.ForeignKey(SeedItem, on_delete=models.CASCADE, related_name="application_items")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    target_entity_id = models.UUIDField(null=True, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["seed_application__applied_at", "seed_item__entity_type", "seed_item__entity_slug"]

    def __str__(self) -> str:
        return f"{self.seed_item.entity_slug}:{self.action}"


class EnvironmentAppState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.ForeignKey(
        "Environment", on_delete=models.CASCADE, related_name="app_states"
    )
    app_id = models.CharField(max_length=120)
    current_release = models.ForeignKey(
        "Release", null=True, blank=True, on_delete=models.SET_NULL, related_name="current_in_env_states"
    )
    last_good_release = models.ForeignKey(
        "Release", null=True, blank=True, on_delete=models.SET_NULL, related_name="last_good_in_env_states"
    )
    last_deployed_at = models.DateTimeField(null=True, blank=True)
    last_good_at = models.DateTimeField(null=True, blank=True)
    last_deploy_run = models.ForeignKey(
        "Run", null=True, blank=True, on_delete=models.SET_NULL, related_name="environment_app_states"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("environment", "app_id")
        ordering = ["environment__name", "app_id"]

    def __str__(self) -> str:
        return f"{self.environment.slug}:{self.app_id}"


class ManagedRepository(models.Model):
    AUTH_MODE_CHOICES = [
        ("", "Default"),
        ("local", "Local"),
        ("https_token", "HTTPS token"),
        ("ssh", "SSH"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    display_name = models.CharField(max_length=200, blank=True)
    remote_url = models.TextField()
    default_branch = models.CharField(max_length=120, default="main")
    is_active = models.BooleanField(default=True)
    auth_mode = models.CharField(max_length=32, blank=True, default="", choices=AUTH_MODE_CHOICES)
    metadata_json = models.JSONField(null=True, blank=True)
    local_cache_relpath = models.CharField(max_length=240, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.display_name or self.slug


class DevTask(models.Model):
    EXECUTION_BRIEF_REVIEW_STATES = [
        ("draft", "Draft"),
        ("ready", "Ready"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("superseded", "Superseded"),
    ]
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("awaiting_review", "Awaiting review"),
        ("completed", "Completed"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("canceled", "Canceled"),
    ]
    TYPE_CHOICES = [
        ("codegen", "Codegen"),
        ("module_scaffold", "Module scaffold"),
        ("release_plan_generate", "Release plan generate"),
        ("registry_sync", "Registry sync"),
        ("deploy", "Deploy"),
        ("deploy_release_plan", "Deploy release plan"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    task_type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    priority = models.IntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    locked_by = models.CharField(max_length=120, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    source_entity_type = models.CharField(max_length=60)
    source_entity_id = models.UUIDField()
    source_conversation_id = models.CharField(max_length=120, blank=True)
    intent_type = models.CharField(max_length=80, blank=True)
    target_repo = models.CharField(max_length=120, blank=True)
    target_branch = models.CharField(max_length=120, blank=True)
    execution_brief = models.JSONField(null=True, blank=True)
    execution_brief_history = models.JSONField(default=list, blank=True)
    execution_brief_review_state = models.CharField(max_length=20, choices=EXECUTION_BRIEF_REVIEW_STATES, default="draft")
    execution_brief_review_notes = models.TextField(blank=True)
    execution_brief_reviewed_at = models.DateTimeField(null=True, blank=True)
    execution_brief_reviewed_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="dev_tasks_brief_reviewed"
    )
    execution_policy = models.JSONField(null=True, blank=True)
    goal = models.ForeignKey("Goal", null=True, blank=True, on_delete=models.SET_NULL, related_name="work_items")
    coordination_thread = models.ForeignKey(
        "CoordinationThread", null=True, blank=True, on_delete=models.SET_NULL, related_name="work_items"
    )
    dependency_work_item_ids = models.JSONField(default=list, blank=True)
    source_run = models.ForeignKey(
        Run, null=True, blank=True, on_delete=models.SET_NULL, related_name="dev_tasks_source"
    )
    input_artifact_key = models.CharField(max_length=200, blank=True)
    work_item_id = models.CharField(max_length=120, blank=True)
    result_run = models.ForeignKey(
        Run, null=True, blank=True, on_delete=models.SET_NULL, related_name="dev_tasks_result"
    )
    runtime_run_id = models.UUIDField(null=True, blank=True)
    runtime_workspace_id = models.UUIDField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    context_purpose = models.CharField(max_length=20, default="any")
    context_packs = models.ManyToManyField(ContextPack, blank=True, related_name="dev_tasks")
    target_instance = models.ForeignKey(
        "ProvisionedInstance", null=True, blank=True, on_delete=models.SET_NULL, related_name="dev_tasks"
    )
    force = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="dev_tasks_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="dev_tasks_updated"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.task_type})"


class ProvisionedInstance(models.Model):
    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("provisioning", "Provisioning"),
        ("running", "Running"),
        ("ready", "Ready"),
        ("error", "Error"),
        ("terminating", "Terminating"),
        ("terminated", "Terminated"),
    ]
    HEALTH_CHOICES = [
        ("unknown", "Unknown"),
        ("healthy", "Healthy"),
        ("degraded", "Degraded"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    environment = models.ForeignKey(
        "Environment", null=True, blank=True, on_delete=models.SET_NULL, related_name="instances"
    )
    aws_region = models.CharField(max_length=50)
    instance_id = models.CharField(max_length=255, blank=True)
    runtime_substrate = models.CharField(max_length=20, default="local")
    instance_type = models.CharField(max_length=64)
    ami_id = models.CharField(max_length=64)
    security_group_id = models.CharField(max_length=64, blank=True)
    subnet_id = models.CharField(max_length=64, blank=True)
    vpc_id = models.CharField(max_length=64, blank=True)
    public_ip = models.GenericIPAddressField(null=True, blank=True)
    private_ip = models.GenericIPAddressField(null=True, blank=True)
    ssm_status = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="requested")
    last_error = models.TextField(blank=True)
    desired_release = models.ForeignKey(
        "Release", null=True, blank=True, on_delete=models.SET_NULL, related_name="desired_instances"
    )
    observed_release = models.ForeignKey(
        "Release", null=True, blank=True, on_delete=models.SET_NULL, related_name="observed_instances"
    )
    observed_at = models.DateTimeField(null=True, blank=True)
    last_deploy_run = models.ForeignKey(
        "Run", null=True, blank=True, on_delete=models.SET_NULL, related_name="deploy_runs"
    )
    health_status = models.CharField(max_length=20, choices=HEALTH_CHOICES, default="unknown")
    tags_json = models.JSONField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="provisioned_instances_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="provisioned_instances_updated"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.aws_region})"


class WorkspaceAppInstance(models.Model):
    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("active", "Active"),
        ("error", "Error"),
    ]

    DEPLOYMENT_TARGET_CHOICES = [
        ("local", "Local"),
        ("aws", "AWS"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="app_instances")
    artifact = models.ForeignKey("Artifact", null=True, blank=True, on_delete=models.SET_NULL, related_name="workspace_app_instances")
    app_slug = models.CharField(max_length=120)
    customer_name = models.CharField(max_length=255, blank=True)
    fqdn = models.CharField(max_length=255)
    deployment_target = models.CharField(max_length=20, choices=DEPLOYMENT_TARGET_CHOICES, default="local")
    dns_config_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="requested")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="workspace_app_instances_created"
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="workspace_app_instances_updated"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "app_slug", "fqdn"], name="uniq_workspace_app_instance_fqdn"),
        ]

    def __str__(self) -> str:
        return f"{self.app_slug}@{self.fqdn}"


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.TextField()
    metadata_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.message[:120]


class PlatformConfigDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField(default=1)
    config_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="platform_configs_created"
    )

    class Meta:
        ordering = ["-created_at", "-version"]

    def __str__(self) -> str:
        return f"Platform config v{self.version}"


class ArtifactPackage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=240)
    version = models.CharField(max_length=40)
    manifest = models.JSONField(default=dict, blank=True)
    file_blob_ref = models.CharField(max_length=600, blank=True, default="")
    package_hash = models.CharField(max_length=128, blank=True, default="")
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="artifact_packages_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("name", "version", "package_hash")

    def __str__(self) -> str:
        return f"{self.name}@{self.version}"


class ArtifactInstallReceipt(models.Model):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("failed", "Failed"),
        ("partial", "Partial"),
    ]
    MODE_CHOICES = [
        ("install", "Install"),
        ("upgrade", "Upgrade"),
        ("reinstall", "Reinstall"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    package = models.ForeignKey(
        "ArtifactPackage", null=True, blank=True, on_delete=models.SET_NULL, related_name="install_receipts"
    )
    package_name = models.CharField(max_length=240)
    package_version = models.CharField(max_length=40)
    package_hash = models.CharField(max_length=128, blank=True, default="")
    installed_at = models.DateTimeField(default=timezone.now)
    installed_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="artifact_install_receipts"
    )
    install_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="install")
    resolved_bindings = models.JSONField(default=dict, blank=True)
    operations = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="success")
    error_summary = models.TextField(blank=True, default="")
    artifact_changes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-installed_at"]

    def __str__(self) -> str:
        return f"{self.package_name}@{self.package_version}:{self.status}"


class ArtifactBindingValue(models.Model):
    TYPE_CHOICES = [
        ("string", "String"),
        ("secret_ref", "Secret Ref"),
        ("model_ref", "Model Ref"),
        ("url", "URL"),
        ("json", "JSON"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, unique=True)
    binding_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="string")
    value = models.JSONField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    secret_ref = models.ForeignKey(
        "SecretRef", null=True, blank=True, on_delete=models.SET_NULL, related_name="artifact_bindings"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="artifact_binding_values_updated"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ModelProvider(models.Model):
    PROVIDER_CHOICES = [
        ("openai", "OpenAI"),
        ("anthropic", "Anthropic"),
        ("google", "Google"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.CharField(max_length=40, choices=PROVIDER_CHOICES, unique=True)
    name = models.CharField(max_length=120)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.name


class ModelConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(ModelProvider, on_delete=models.PROTECT, related_name="model_configs")
    credential = models.ForeignKey(
        "ProviderCredential", null=True, blank=True, on_delete=models.SET_NULL, related_name="model_configs"
    )
    model_name = models.CharField(max_length=160)
    temperature = models.FloatField(default=0.2)
    max_tokens = models.IntegerField(default=1200)
    top_p = models.FloatField(default=1.0)
    frequency_penalty = models.FloatField(default=0.0)
    presence_penalty = models.FloatField(default=0.0)
    extra_json = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider__slug", "model_name"]

    def __str__(self) -> str:
        return f"{self.provider.slug}:{self.model_name}"


class AgentPurpose(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("deprecated", "Deprecated"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=500, blank=True)
    model_config = models.ForeignKey(ModelConfig, null=True, blank=True, on_delete=models.SET_NULL, related_name="purposes")
    # Short purpose-level guidance prepended to agent system prompts at runtime.
    preamble = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    default_context_pack_refs_json = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    # Backward-compatibility field; status is the source of truth.
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_purposes_updated"
    )

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.slug


class ProviderCredential(models.Model):
    AUTH_TYPE_CHOICES = [
        ("api_key", "API key"),
        ("env_ref", "Environment variable"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(ModelProvider, on_delete=models.PROTECT, related_name="credentials")
    name = models.CharField(max_length=160)
    auth_type = models.CharField(max_length=40, choices=AUTH_TYPE_CHOICES, default="api_key")
    api_key_encrypted = models.TextField(blank=True, null=True)
    secret_ref = models.ForeignKey(
        "SecretRef", null=True, blank=True, on_delete=models.SET_NULL, related_name="provider_credentials"
    )
    env_var_name = models.CharField(max_length=160, blank=True)
    is_default = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider__slug", "-is_default", "name"]

    def __str__(self) -> str:
        return f"{self.provider.slug}:{self.name}"


class AgentDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=160)
    model_config = models.ForeignKey(ModelConfig, on_delete=models.PROTECT, related_name="agent_definitions")
    system_prompt_text = models.TextField(blank=True)
    context_pack_refs_json = models.JSONField(default=list, blank=True)
    is_default = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    purposes = models.ManyToManyField(AgentPurpose, through="AgentDefinitionPurpose", related_name="agent_definitions")

    class Meta:
        ordering = ["name", "slug"]

    def __str__(self) -> str:
        return self.slug


class AgentDefinitionPurpose(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_definition = models.ForeignKey(AgentDefinition, on_delete=models.CASCADE, related_name="purpose_links")
    purpose = models.ForeignKey(AgentPurpose, on_delete=models.CASCADE, related_name="agent_links")
    is_default_for_purpose = models.BooleanField(default=False)

    class Meta:
        unique_together = ("agent_definition", "purpose")
        ordering = ["agent_definition__slug", "purpose__slug"]
        constraints = [
            models.UniqueConstraint(
                fields=["purpose"],
                condition=Q(is_default_for_purpose=True),
                name="uniq_default_agent_per_purpose",
            )
        ]

    def __str__(self) -> str:
        return f"{self.agent_definition.slug}:{self.purpose.slug}"


class Report(models.Model):
    TYPE_CHOICES = [
        ("bug", "Bug"),
        ("feature", "Feature"),
    ]
    PRIORITY_CHOICES = [
        ("p0", "P0"),
        ("p1", "P1"),
        ("p2", "P2"),
        ("p3", "P3"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=240)
    description = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="p2")
    tags_json = models.JSONField(default=list, blank=True)
    context_json = models.JSONField(default=dict, blank=True)
    notification_errors_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports_created"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.report_type}:{self.title}"


class ReportAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="attachments")
    filename = models.CharField(max_length=300)
    content_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    storage_provider = models.CharField(max_length=40, default="local")
    storage_bucket = models.CharField(max_length=255, blank=True)
    storage_key = models.CharField(max_length=700, blank=True)
    storage_path = models.CharField(max_length=900, blank=True)
    storage_metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.report_id})"


class AppNotification(models.Model):
    CATEGORY_CHOICES = [
        ("application", "Application"),
        ("system", "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, null=True, blank=True, on_delete=models.SET_NULL, related_name="app_notifications"
    )
    source_app_key = models.CharField(max_length=160, db_index=True)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default="application", db_index=True)
    notification_type_key = models.CharField(max_length=120, db_index=True)
    title = models.CharField(max_length=240)
    summary = models.TextField(blank=True, default="")
    payload_json = models.JSONField(default=dict, blank=True)
    deep_link = models.CharField(max_length=500, blank=True, default="")
    source_entity_type = models.CharField(max_length=120, blank=True, default="")
    source_entity_id = models.CharField(max_length=160, blank=True, default="")
    source_metadata_json = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        UserIdentity, null=True, blank=True, on_delete=models.SET_NULL, related_name="app_notifications_created"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "created_at"], name="ix_app_notif_workspace_created"),
            models.Index(fields=["source_app_key", "notification_type_key"], name="ix_app_notif_source_type"),
        ]

    def __str__(self) -> str:
        return f"{self.source_app_key}:{self.notification_type_key}:{self.title}"


class NotificationRecipient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(AppNotification, on_delete=models.CASCADE, related_name="recipients")
    recipient = models.ForeignKey(UserIdentity, on_delete=models.CASCADE, related_name="notification_recipients")
    unread = models.BooleanField(default=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "recipient"],
                name="uniq_notification_recipient",
            )
        ]
        indexes = [
            models.Index(fields=["recipient", "unread", "created_at"], name="ix_notif_recipient_feed"),
        ]

    def __str__(self) -> str:
        return f"{self.notification_id}:{self.recipient_id}:{'unread' if self.unread else 'read'}"


class DeliveryTarget(models.Model):
    CHANNEL_CHOICES = [
        ("email", "Email"),
    ]
    VERIFICATION_STATUS_CHOICES = [
        ("unverified", "Unverified"),
        ("verified", "Verified"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(UserIdentity, on_delete=models.CASCADE, related_name="delivery_targets")
    channel = models.CharField(max_length=40, choices=CHANNEL_CHOICES, default="email", db_index=True)
    address = models.CharField(max_length=320)
    enabled = models.BooleanField(default=True, db_index=True)
    verification_status = models.CharField(
        max_length=40, choices=VERIFICATION_STATUS_CHOICES, default="unverified", db_index=True
    )
    is_primary = models.BooleanField(default=False)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_primary", "-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "channel", "address"],
                name="uniq_delivery_target_owner_channel_address",
            ),
            models.UniqueConstraint(
                fields=["owner", "channel"],
                condition=Q(is_primary=True),
                name="uniq_primary_delivery_target_owner_channel",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "channel", "enabled"], name="ix_dlv_tgt_owner_chan_en"),
        ]

    def __str__(self) -> str:
        return f"{self.owner_id}:{self.channel}:{self.address}"


class DeliveryPreference(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(UserIdentity, on_delete=models.CASCADE, related_name="delivery_preferences")
    workspace = models.ForeignKey(
        Workspace, null=True, blank=True, on_delete=models.CASCADE, related_name="delivery_preferences"
    )
    source_app_key = models.CharField(max_length=160, blank=True, default="")
    notification_type_key = models.CharField(max_length=120, blank=True, default="")
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "workspace", "source_app_key", "notification_type_key"],
                condition=Q(workspace__isnull=False),
                name="uniq_delivery_pref_owner_workspace_scope",
            ),
            models.UniqueConstraint(
                fields=["owner", "source_app_key", "notification_type_key"],
                condition=Q(workspace__isnull=True),
                name="uniq_delivery_pref_owner_global_scope",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "workspace"], name="ix_dlv_pref_owner_ws"),
            models.Index(fields=["owner", "source_app_key"], name="ix_dlv_pref_owner_src"),
        ]

    def __str__(self) -> str:
        scope = str(self.workspace_id) if self.workspace_id else "global"
        return f"{self.owner_id}:{scope}:{self.source_app_key}:{self.notification_type_key}"


class DeliveryAttempt(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("delivered", "Delivered"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(AppNotification, on_delete=models.CASCADE, related_name="delivery_attempts")
    recipient = models.ForeignKey(
        NotificationRecipient, null=True, blank=True, on_delete=models.SET_NULL, related_name="delivery_attempts"
    )
    target = models.ForeignKey(DeliveryTarget, null=True, blank=True, on_delete=models.SET_NULL, related_name="delivery_attempts")
    channel = models.CharField(max_length=40, choices=DeliveryTarget.CHANNEL_CHOICES, default="email", db_index=True)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default="pending", db_index=True)
    retry_count = models.PositiveIntegerField(default=0)
    provider_name = models.CharField(max_length=120, blank=True, default="")
    provider_message_id = models.CharField(max_length=240, blank=True, default="")
    error_text = models.TextField(blank=True, default="")
    error_details_json = models.JSONField(null=True, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-attempted_at", "-created_at"]
        indexes = [
            models.Index(fields=["notification", "status", "attempted_at"], name="ix_dlv_attempt_notif_st"),
            models.Index(fields=["target", "status", "attempted_at"], name="ix_dlv_attempt_tgt_st"),
        ]

    def __str__(self) -> str:
        return f"{self.notification_id}:{self.channel}:{self.status}:{self.retry_count}"


class CoordinationThread(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("queued", "Queued"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    ]
    PRIORITY_CHOICES = [
        ("critical", "Critical"),
        ("high", "High"),
        ("normal", "Normal"),
        ("low", "Low"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="coordination_threads")
    goal = models.ForeignKey("Goal", null=True, blank=True, on_delete=models.SET_NULL, related_name="threads")
    owner = models.ForeignKey(
        "UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="coordination_threads"
    )
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    domain = models.CharField(max_length=80, blank=True)
    work_in_progress_limit = models.PositiveIntegerField(default=1)
    execution_policy = models.JSONField(default=dict, blank=True)
    source_conversation_id = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self) -> str:
        return self.title


class CoordinationEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(CoordinationThread, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=80)
    work_item = models.ForeignKey("DevTask", null=True, blank=True, on_delete=models.SET_NULL, related_name="coordination_events")
    run_id = models.UUIDField(null=True, blank=True)
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.thread_id}:{self.event_type}"


class CampaignType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", null=True, blank=True, on_delete=models.CASCADE, related_name="campaign_types")
    key = models.CharField(max_length=120)
    label = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=80, blank=True, default="")
    enabled = models.BooleanField(default=True, db_index=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label", "key"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "key"], name="uniq_campaign_type_workspace_key"),
            models.UniqueConstraint(
                fields=["key"],
                condition=Q(workspace__isnull=True),
                name="uniq_campaign_type_global_key",
            ),
        ]

    def __str__(self) -> str:
        return self.label or self.key


class Campaign(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="campaigns")
    slug = models.SlugField(max_length=120)
    name = models.CharField(max_length=240)
    campaign_type = models.CharField(max_length=120, default="generic")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    description = models.TextField(blank=True)
    archived = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        "UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_campaigns"
    )
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "slug"], name="uniq_campaign_workspace_slug"),
        ]

    def __str__(self) -> str:
        return self.name


class OrchestrationPipeline(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="orchestration_pipelines")
    key = models.CharField(max_length=120)
    name = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    version = models.CharField(max_length=40, default="v1")
    enabled = models.BooleanField(default=True, db_index=True)
    max_concurrency = models.PositiveIntegerField(default=1)
    stale_run_timeout_seconds = models.PositiveIntegerField(default=3600)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        "UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_orchestration_pipelines"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "key"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "key"], name="uniq_orchestration_pipeline_workspace_key"),
        ]

    def __str__(self) -> str:
        return f"{self.key} ({self.workspace_id})"


class OrchestrationJobDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey(OrchestrationPipeline, on_delete=models.CASCADE, related_name="job_definitions")
    job_key = models.CharField(max_length=120)
    stage_key = models.CharField(max_length=80)
    name = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    handler_key = models.CharField(max_length=160)
    enabled = models.BooleanField(default=True, db_index=True)
    only_if_upstream_changed = models.BooleanField(default=False)
    runs_per_jurisdiction = models.BooleanField(default=False)
    runs_per_source = models.BooleanField(default=False)
    concurrency_limit = models.PositiveIntegerField(default=1)
    retry_max_attempts = models.PositiveIntegerField(default=3)
    backoff_initial_seconds = models.PositiveIntegerField(default=30)
    backoff_max_seconds = models.PositiveIntegerField(default=1800)
    backoff_multiplier = models.FloatField(default=2.0)
    produces_artifact = models.BooleanField(default=False)
    artifact_kind = models.CharField(max_length=120, blank=True, default="")
    schedule_json = models.JSONField(default=dict, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stage_key", "job_key"]
        constraints = [
            models.UniqueConstraint(fields=["pipeline", "job_key"], name="uniq_orchestration_job_definition_key"),
        ]

    def __str__(self) -> str:
        return f"{self.pipeline_id}:{self.job_key}"


class OrchestrationJobSchedule(models.Model):
    SCHEDULE_KIND_CHOICES = [
        ("manual", "Manual"),
        ("interval", "Interval"),
        ("cron", "Cron"),
        ("event", "Event"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_definition = models.ForeignKey(
        OrchestrationJobDefinition, on_delete=models.CASCADE, related_name="schedules"
    )
    schedule_key = models.CharField(max_length=120)
    schedule_kind = models.CharField(max_length=20, choices=SCHEDULE_KIND_CHOICES, default="manual")
    enabled = models.BooleanField(default=True, db_index=True)
    cron_expression = models.CharField(max_length=120, blank=True, default="")
    interval_seconds = models.PositiveIntegerField(default=0)
    timezone_name = models.CharField(max_length=80, blank=True, default="UTC")
    next_fire_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["schedule_key", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_definition", "schedule_key"],
                name="uniq_orchestration_job_schedule_key",
            ),
        ]
        indexes = [
            models.Index(fields=["enabled", "next_fire_at"], name="ix_orch_job_sched_poll"),
        ]

    def __str__(self) -> str:
        return f"{self.job_definition_id}:{self.schedule_key}"

    def clean(self) -> None:
        super().clean()
        kind = str(self.schedule_kind or "").strip()
        if kind == "cron":
            raise ValidationError(
                {
                    "schedule_kind": "cron is not supported in orchestration v1. Use interval or manual schedules."
                }
            )
        if kind == "interval":
            if int(self.interval_seconds or 0) <= 0:
                raise ValidationError({"interval_seconds": "interval_seconds must be > 0 for interval schedules."})
            if not self.next_fire_at and bool(self.enabled):
                raise ValidationError({"next_fire_at": "next_fire_at is required for enabled interval schedules."})
            if str(self.cron_expression or "").strip():
                raise ValidationError({"cron_expression": "cron_expression must be empty for interval schedules."})
        elif kind in {"manual", "event"}:
            if int(self.interval_seconds or 0) > 0:
                raise ValidationError({"interval_seconds": "interval_seconds is only valid for interval schedules."})
            if str(self.cron_expression or "").strip():
                raise ValidationError({"cron_expression": "cron_expression is not supported in orchestration v1."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class OrchestrationJobDependency(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey(OrchestrationPipeline, on_delete=models.CASCADE, related_name="job_dependencies")
    upstream_job = models.ForeignKey(
        OrchestrationJobDefinition, on_delete=models.CASCADE, related_name="downstream_dependencies"
    )
    downstream_job = models.ForeignKey(
        OrchestrationJobDefinition, on_delete=models.CASCADE, related_name="upstream_dependencies"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "upstream_job", "downstream_job"],
                name="uniq_orchestration_job_dependency",
            ),
            models.CheckConstraint(
                check=~Q(upstream_job=models.F("downstream_job")),
                name="check_orchestration_dependency_not_self",
            ),
        ]
        indexes = [
            models.Index(fields=["pipeline", "downstream_job"], name="ix_orch_dependency_downstream"),
            models.Index(fields=["pipeline", "upstream_job"], name="ix_orch_dependency_upstream"),
        ]

    def __str__(self) -> str:
        return f"{self.upstream_job_id}->{self.downstream_job_id}"


class OrchestrationRun(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
        ("stale", "Stale"),
        ("skipped", "Skipped"),
    ]
    TRIGGER_CHOICES = [
        ("scheduled", "Scheduled"),
        ("upstream_change", "Upstream Change"),
        ("manual", "Manual"),
        ("retry", "Retry"),
        ("backfill", "Backfill"),
        ("system", "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="orchestration_runs")
    pipeline = models.ForeignKey(OrchestrationPipeline, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    trigger_cause = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default="manual", db_index=True)
    trigger_key = models.CharField(max_length=120, blank=True, default="")
    correlation_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    chain_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    idempotency_key = models.CharField(max_length=160, blank=True, default="")
    dedupe_key = models.CharField(max_length=160, blank=True, default="")
    initiated_by = models.ForeignKey(
        "UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="orchestration_runs"
    )
    rerun_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="rerun_children"
    )
    scope_jurisdiction = models.CharField(max_length=120, blank=True, default="", db_index=True)
    scope_source = models.CharField(max_length=120, blank=True, default="", db_index=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    metrics_json = models.JSONField(default=dict, blank=True)
    summary = models.CharField(max_length=240, blank=True, default="")
    error_text = models.TextField(blank=True, default="")
    error_details_json = models.JSONField(null=True, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    stale_deadline_at = models.DateTimeField(null=True, blank=True, db_index=True)
    stale_at = models.DateTimeField(null=True, blank=True)
    stale_reason = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "pipeline", "idempotency_key"],
                condition=Q(idempotency_key__gt=""),
                name="uniq_orch_run_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "pipeline", "status"], name="ix_orch_run_ws_pipeline_status"),
            models.Index(fields=["workspace", "created_at"], name="ix_orch_run_ws_created"),
            models.Index(fields=["workspace", "status", "queued_at"], name="ix_orch_run_scheduler_poll"),
            models.Index(fields=["workspace", "trigger_cause", "created_at"], name="ix_orch_run_trigger_time"),
            models.Index(fields=["workspace", "correlation_id", "created_at"], name="ix_orch_run_corr_time"),
            models.Index(fields=["workspace", "chain_id", "created_at"], name="ix_orch_run_chain_time"),
            models.Index(fields=["workspace", "scope_jurisdiction", "scope_source", "status"], name="ix_orch_run_partition_status"),
            models.Index(fields=["pipeline", "stale_deadline_at", "status"], name="ix_orch_run_stale_poll"),
        ]

    def __str__(self) -> str:
        return f"{self.pipeline_id}:{self.status}:{self.id}"


class OrchestrationJobRun(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
        ("cancelled", "Cancelled"),
        ("stale", "Stale"),
        ("waiting_retry", "Waiting Retry"),
    ]
    TRIGGER_CHOICES = [
        ("scheduled", "Scheduled"),
        ("upstream_change", "Upstream Change"),
        ("manual", "Manual"),
        ("retry", "Retry"),
        ("backfill", "Backfill"),
        ("system", "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="orchestration_job_runs")
    pipeline = models.ForeignKey(OrchestrationPipeline, on_delete=models.CASCADE, related_name="job_runs")
    run = models.ForeignKey(OrchestrationRun, on_delete=models.CASCADE, related_name="job_runs")
    job_definition = models.ForeignKey(
        OrchestrationJobDefinition, on_delete=models.CASCADE, related_name="job_runs"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued", db_index=True)
    trigger_cause = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default="manual", db_index=True)
    trigger_key = models.CharField(max_length=120, blank=True, default="")
    correlation_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    chain_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    scope_jurisdiction = models.CharField(max_length=120, blank=True, default="", db_index=True)
    scope_source = models.CharField(max_length=120, blank=True, default="", db_index=True)
    idempotency_key = models.CharField(max_length=160, blank=True, default="")
    dedupe_key = models.CharField(max_length=160, blank=True, default="")
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=1)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    upstream_changed = models.BooleanField(default=False)
    skipped_reason = models.CharField(max_length=240, blank=True, default="")
    summary = models.CharField(max_length=240, blank=True, default="")
    error_text = models.TextField(blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)
    metrics_json = models.JSONField(default=dict, blank=True)
    error_details_json = models.JSONField(null=True, blank=True)
    output_change_token = models.CharField(max_length=160, blank=True, default="")
    queued_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    stale_deadline_at = models.DateTimeField(null=True, blank=True, db_index=True)
    stale_at = models.DateTimeField(null=True, blank=True)
    stale_reason = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["run", "job_definition"], name="uniq_orchestration_job_run_per_run"),
            models.UniqueConstraint(
                fields=["workspace", "job_definition", "idempotency_key"],
                condition=Q(idempotency_key__gt=""),
                name="uniq_orch_job_run_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["run", "status"], name="ix_orch_job_run_run_status"),
            models.Index(fields=["status", "next_attempt_at"], name="ix_orch_job_run_status_retry"),
            models.Index(fields=["job_definition", "status", "created_at"], name="ix_orch_job_run_job_status"),
            models.Index(fields=["workspace", "pipeline", "status", "next_attempt_at"], name="ix_orch_job_run_poll"),
            models.Index(fields=["workspace", "scope_jurisdiction", "scope_source", "status"], name="ix_orch_jrun_part_status"),
            models.Index(fields=["workspace", "correlation_id", "created_at"], name="ix_orch_job_run_corr_time"),
            models.Index(fields=["workspace", "chain_id", "created_at"], name="ix_orch_job_run_chain_time"),
            models.Index(fields=["job_definition", "scope_jurisdiction", "scope_source"], name="ix_orch_job_run_job_partition"),
            models.Index(fields=["pipeline", "stale_deadline_at", "status"], name="ix_orch_job_run_stale_poll"),
        ]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.job_definition_id}:{self.status}"


class OrchestrationJobRunAttempt(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
        ("cancelled", "Cancelled"),
        ("stale", "Stale"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_run = models.ForeignKey(OrchestrationJobRun, on_delete=models.CASCADE, related_name="attempts")
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    executor_key = models.CharField(max_length=120, blank=True, default="")
    summary = models.CharField(max_length=240, blank=True, default="")
    error_text = models.TextField(blank=True, default="")
    error_details_json = models.JSONField(null=True, blank=True)
    metrics_json = models.JSONField(default=dict, blank=True)
    output_json = models.JSONField(default=dict, blank=True)
    retryable = models.BooleanField(default=False)
    queued_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    stale_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["attempt_number", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_run", "attempt_number"],
                name="uniq_orch_job_run_attempt_number",
            ),
        ]
        indexes = [
            models.Index(fields=["job_run", "status"], name="ix_orch_attempt_job_status"),
            models.Index(fields=["status", "queued_at"], name="ix_orch_attempt_sched_poll"),
        ]

    def __str__(self) -> str:
        return f"{self.job_run_id}:attempt:{self.attempt_number}"


class OrchestrationJobRunOutput(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_run = models.ForeignKey(OrchestrationJobRun, on_delete=models.CASCADE, related_name="outputs")
    attempt = models.ForeignKey(
        OrchestrationJobRunAttempt, null=True, blank=True, on_delete=models.SET_NULL, related_name="outputs"
    )
    output_key = models.CharField(max_length=120)
    output_type = models.CharField(max_length=80, default="generic")
    output_uri = models.TextField(blank=True, default="")
    output_change_token = models.CharField(max_length=160, blank=True, default="", db_index=True)
    artifact = models.ForeignKey(
        "Artifact", null=True, blank=True, on_delete=models.SET_NULL, related_name="orchestration_job_outputs"
    )
    metadata_json = models.JSONField(default=dict, blank=True)
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_run", "output_key"],
                name="uniq_orch_job_run_output_key",
            ),
        ]
        indexes = [
            models.Index(fields=["job_run", "created_at"], name="ix_orch_output_job_time"),
            models.Index(fields=["output_type", "created_at"], name="ix_orch_output_type_time"),
        ]

    def __str__(self) -> str:
        return f"{self.job_run_id}:{self.output_key}"


class Goal(models.Model):
    STATUS_CHOICES = [
        ("proposed", "Proposed"),
        ("decomposed", "Decomposed"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("canceled", "Canceled"),
    ]
    TYPE_CHOICES = [
        ("build_system", "Build System"),
        ("extend_system", "Extend System"),
        ("investigate_problem", "Investigate Problem"),
        ("stabilize_system", "Stabilize System"),
    ]
    PRIORITY_CHOICES = [
        ("critical", "Critical"),
        ("high", "High"),
        ("normal", "Normal"),
        ("low", "Low"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="goals")
    application = models.ForeignKey(
        "Application", null=True, blank=True, on_delete=models.SET_NULL, related_name="goals"
    )
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    source_conversation_id = models.CharField(max_length=120, blank=True)
    requested_by = models.ForeignKey(
        "UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_goals"
    )
    goal_type = models.CharField(max_length=40, choices=TYPE_CHOICES, default="build_system")
    planning_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="proposed")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")
    planning_summary = models.TextField(blank=True)
    resolution_notes_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self) -> str:
        return self.title


class Application(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="applications")
    name = models.CharField(max_length=240)
    summary = models.TextField(blank=True)
    source_factory_key = models.CharField(max_length=120)
    source_conversation_id = models.CharField(max_length=120, blank=True)
    requested_by = models.ForeignKey(
        "UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_applications"
    )
    target_repository = models.ForeignKey(
        "ManagedRepository", null=True, blank=True, on_delete=models.SET_NULL, related_name="applications"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    plan_fingerprint = models.CharField(max_length=128, blank=True, default="")
    request_objective = models.TextField(blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "plan_fingerprint"],
                condition=Q(plan_fingerprint__gt=""),
                name="uniq_application_plan_fingerprint_per_workspace",
            )
        ]

    def __str__(self) -> str:
        return self.name


class ApplicationPlan(models.Model):
    STATUS_CHOICES = [
        ("review", "Review"),
        ("applied", "Applied"),
        ("canceled", "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="application_plans")
    application = models.ForeignKey(
        "Application", null=True, blank=True, on_delete=models.SET_NULL, related_name="plans"
    )
    name = models.CharField(max_length=240)
    summary = models.TextField(blank=True)
    source_factory_key = models.CharField(max_length=120)
    source_conversation_id = models.CharField(max_length=120, blank=True)
    requested_by = models.ForeignKey(
        "UserIdentity", null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_application_plans"
    )
    target_repository = models.ForeignKey(
        "ManagedRepository", null=True, blank=True, on_delete=models.SET_NULL, related_name="application_plans"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="review")
    request_objective = models.TextField(blank=True)
    plan_fingerprint = models.CharField(max_length=128, blank=True, default="")
    plan_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "plan_fingerprint"],
                condition=Q(plan_fingerprint__gt=""),
                name="uniq_application_plan_fingerprint_review_per_workspace",
            )
        ]

    def __str__(self) -> str:
        return self.name
