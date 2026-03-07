#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_SEED_PATH = Path(__file__).resolve().parents[1] / "seeds" / "xyn-core-context-packs.v1.2.0.json"

DEFAULT_BINDING_SLUGS = {
    "xyn-console-default",
    "xyn-planner-canon",
}

TITLE_OVERRIDES = {
    "xyn-console-default": "Xyn Console Default",
    "xyn-planner-canon": "Xyn Planner Canon",
}

DESCRIPTION_OVERRIDES = {
    "xyn-console-default": "Default pack for palette and assistant command execution inside Xyn.",
    "xyn-planner-canon": "Default pack for app-intent drafting and AppSpec generation.",
}

CAPABILITY_OVERRIDES = {
    "xyn-console-default": ["palette", "assistant", "artifact-navigation"],
    "xyn-planner-canon": ["app-builder", "draft-generation", "app-spec"],
}

PURPOSE_CAPABILITIES = {
    "planner": ["planner"],
    "coder": ["codegen"],
    "video_explainer": ["video-explainer"],
    "explainer_script": ["explainer-script"],
    "explainer_storyboard": ["explainer-storyboard"],
    "explainer_visual_prompts": ["explainer-visual-prompts"],
    "explainer_narration": ["explainer-narration"],
    "explainer_title_description": ["explainer-title-description"],
    "any": ["context-pack"],
}


def _titleize(slug: str) -> str:
    return " ".join(part.capitalize() for part in str(slug or "").replace("_", "-").split("-") if part)


def _first_heading(markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _description_for(slug: str, payload: dict[str, Any]) -> str:
    if slug in DESCRIPTION_OVERRIDES:
        return DESCRIPTION_OVERRIDES[slug]
    purpose = str(payload.get("purpose") or "context pack").strip()
    return f"Authoritative context pack synchronized from xyn-platform for purpose={purpose}."


def _capabilities_for(slug: str, payload: dict[str, Any]) -> list[str]:
    if slug in CAPABILITY_OVERRIDES:
        return CAPABILITY_OVERRIDES[slug]
    purpose = str(payload.get("purpose") or "any").strip().lower()
    values = PURPOSE_CAPABILITIES.get(purpose, ["context-pack"])
    return [str(value) for value in values if str(value).strip()]


def export_runtime_manifest(seed_path: Path) -> dict[str, Any]:
    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    seed_pack = raw.get("seed_pack") if isinstance(raw.get("seed_pack"), dict) else {}
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    context_packs: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or str(item.get("entity_type") or "").strip() != "context_pack":
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if not bool(payload.get("is_active", True)):
            continue
        slug = str(payload.get("name") or item.get("entity_slug") or "").strip()
        if not slug:
            continue
        content_markdown = str(payload.get("content_markdown") or payload.get("content") or "")
        heading = _first_heading(content_markdown)
        context_packs.append(
            {
                "slug": slug,
                "title": TITLE_OVERRIDES.get(slug) or heading or _titleize(slug),
                "description": _description_for(slug, payload),
                "purpose": str(payload.get("purpose") or "any").strip() or "any",
                "scope": str(payload.get("scope") or "global").strip() or "global",
                "version": str(payload.get("version") or "1.0.0").strip() or "1.0.0",
                "capabilities": _capabilities_for(slug, payload),
                "bind_by_default": slug in DEFAULT_BINDING_SLUGS,
                "content_format": "markdown",
                "content": content_markdown,
                "applies_to_json": payload.get("applies_to_json") if isinstance(payload.get("applies_to_json"), dict) else {},
            }
        )
    return {
        "manifest_version": "xyn.context-pack-runtime-manifest.v1",
        "source_system": "xyn-platform",
        "source_seed_pack_slug": str(seed_pack.get("slug") or "xyn-core-context-packs"),
        "source_seed_pack_version": str(seed_pack.get("version") or ""),
        "context_packs": context_packs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export authoritative xyn-platform context packs for xyn-core runtime sync.")
    parser.add_argument("--seed", default=str(DEFAULT_SEED_PATH), help="Path to the authoritative xyn-platform seed pack JSON")
    parser.add_argument("--output", required=True, help="Output path for the runtime manifest JSON")
    args = parser.parse_args()

    seed_path = Path(args.seed).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    manifest = export_runtime_manifest(seed_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
