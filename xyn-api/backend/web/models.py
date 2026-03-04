import uuid

from django.core.exceptions import ValidationError
from django.db import models


class Page(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.title


class MenuItem(models.Model):
    class Kind(models.TextChoices):
        PAGE = "page", "Page"
        ARTICLES_INDEX = "articles_index", "Articles index"
        EXTERNAL = "external", "External"
        ROUTE = "route", "Route"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=120)
    path = models.CharField(max_length=200)
    kind = models.CharField(max_length=30, choices=Kind.choices, default=Kind.PAGE)
    page = models.ForeignKey(
        Page, on_delete=models.SET_NULL, null=True, blank=True, related_name="menu_items"
    )
    external_url = models.URLField(blank=True)
    requires_auth = models.BooleanField(default=False)
    visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "label"]

    def __str__(self) -> str:
        return self.label

    def clean(self) -> None:
        errors = {}
        if self.kind == self.Kind.PAGE and not self.page:
            errors["page"] = "Page is required when kind is page."
        if self.kind == self.Kind.EXTERNAL and not self.external_url:
            errors["external_url"] = "External URL is required when kind is external."
        if errors:
            raise ValidationError(errors)


class WebSection(models.Model):
    class SectionType(models.TextChoices):
        HERO = "hero", "Hero"
        FEATURE_GRID = "feature_grid", "Feature grid"
        SERVICE_CARDS = "service_cards", "Service cards"
        CTA_BAND = "cta_band", "CTA band"
        QUOTE = "quote", "Quote"
        SIMPLE_MD = "simple_md", "Simple markdown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sections",
    )
    key = models.CharField(max_length=120)
    section_type = models.CharField(max_length=40, choices=SectionType.choices)
    title = models.CharField(max_length=200, blank=True)
    body_md = models.TextField(blank=True)
    data_json = models.JSONField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "key"]
        unique_together = ("page", "key")

    def __str__(self) -> str:
        if self.page:
            return f"{self.page.slug}: {self.key}"
        return f"home: {self.key}"


class SiteConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site Config"
        verbose_name_plural = "Site Config"

    def __str__(self) -> str:
        return self.site_name or "Site Config"
