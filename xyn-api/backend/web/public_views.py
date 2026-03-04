from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .models import MenuItem, Page, SiteConfig, WebSection


def _menu_items():
    items = (
        MenuItem.objects.filter(visible=True)
        .select_related("page")
        .order_by("order", "label")
    )
    payload = []
    for item in items:
        payload.append(
            {
                "label": item.label,
                "path": item.path,
                "kind": item.kind,
                "requires_auth": item.requires_auth,
                "page_slug": item.page.slug if item.page_id else None,
                "external_url": item.external_url or None,
                "order": item.order,
            }
        )
    return payload


def _section_payload(sections):
    return [
        {
            "key": section.key,
            "section_type": section.section_type,
            "title": section.title or None,
            "body_md": section.body_md or "",
            "data_json": section.data_json,
            "order": section.order,
        }
        for section in sections
    ]


@require_GET
def public_menu(_request):
    return JsonResponse({"items": _menu_items()})


@require_GET
def public_pages(_request):
    pages = Page.objects.filter(published=True).order_by("slug")
    payload = [{"title": page.title, "slug": page.slug} for page in pages]
    return JsonResponse({"items": payload})


@require_GET
def public_page_detail(_request, slug: str):
    page = get_object_or_404(Page, slug=slug, published=True)
    return JsonResponse({"title": page.title, "slug": page.slug})


@require_GET
def public_page_sections(_request, slug: str):
    page = get_object_or_404(Page, slug=slug, published=True)
    sections = WebSection.objects.filter(page=page, visible=True).order_by("order", "key")
    return JsonResponse({"items": _section_payload(sections)})


@require_GET
def public_home(_request):
    home_page = Page.objects.filter(slug="home", published=True).first()
    if home_page:
        sections = WebSection.objects.filter(page=home_page, visible=True).order_by(
            "order", "key"
        )
        page_payload = {"title": home_page.title, "slug": home_page.slug}
    else:
        sections = WebSection.objects.filter(page__isnull=True, visible=True).order_by(
            "order", "key"
        )
        page_payload = None
    return JsonResponse(
        {
            "menu": _menu_items(),
            "page": page_payload,
            "sections": _section_payload(sections),
        }
    )


@require_GET
def public_site_config(_request):
    config = SiteConfig.objects.first()
    return JsonResponse({"site_name": config.site_name if config else ""})
