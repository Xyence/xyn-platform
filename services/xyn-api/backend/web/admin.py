from django.contrib import admin

from .models import MenuItem, Page, SiteConfig, WebSection


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "published", "updated_at")
    list_filter = ("published",)
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("slug",)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("label", "path", "kind", "page", "visible", "requires_auth", "order")
    list_filter = ("kind", "visible", "requires_auth")
    search_fields = ("label", "path", "page__title", "page__slug")
    ordering = ("order", "label")


@admin.register(WebSection)
class WebSectionAdmin(admin.ModelAdmin):
    list_display = ("key", "page", "section_type", "order", "visible")
    list_filter = ("section_type", "visible", "page")
    search_fields = ("key", "title", "page__title", "page__slug")
    ordering = ("page", "order", "key")


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("site_name", "updated_at")
