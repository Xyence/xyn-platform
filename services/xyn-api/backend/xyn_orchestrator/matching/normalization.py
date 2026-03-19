from __future__ import annotations

import re
from typing import Any

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_text(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    clean = _NON_ALNUM.sub(" ", raw)
    clean = _WHITESPACE.sub(" ", clean)
    return clean.strip()


def normalize_identifier(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[^a-z0-9]+", "", raw)


def normalize_address(value: Any) -> str:
    raw = normalize_text(value)
    if not raw:
        return ""
    replacements = {
        " street ": " st ",
        " avenue ": " ave ",
        " boulevard ": " blvd ",
        " drive ": " dr ",
        " lane ": " ln ",
        " road ": " rd ",
        " place ": " pl ",
        " court ": " ct ",
        " north ": " n ",
        " south ": " s ",
        " east ": " e ",
        " west ": " w ",
    }
    normalized = f" {raw} "
    for needle, replacement in replacements.items():
        normalized = normalized.replace(needle, replacement)
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    return normalized


def normalize_record_attributes(attributes: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(attributes, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in attributes.items():
        k = str(key or "").strip().lower()
        if not k:
            continue
        if "address" in k:
            normalized[k] = normalize_address(value)
        elif k in {"external_id", "id", "identifier"}:
            normalized[k] = normalize_identifier(value)
        else:
            normalized[k] = normalize_text(value)
    return normalized
