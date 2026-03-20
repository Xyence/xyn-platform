from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")

_ADDRESS_SUFFIXES = {
    "street": "st",
    "st": "st",
    "avenue": "ave",
    "ave": "ave",
    "road": "rd",
    "rd": "rd",
    "boulevard": "blvd",
    "blvd": "blvd",
    "drive": "dr",
    "dr": "dr",
    "lane": "ln",
    "ln": "ln",
    "court": "ct",
    "ct": "ct",
    "place": "pl",
    "pl": "pl",
    "terrace": "ter",
    "ter": "ter",
    "parkway": "pkwy",
    "pkwy": "pkwy",
}

_DIRECTIONALS = {
    "north": "n",
    "n": "n",
    "south": "s",
    "s": "s",
    "east": "e",
    "e": "e",
    "west": "w",
    "w": "w",
}

_UNIT_TOKENS = {"apt", "apartment", "unit", "ste", "suite", "#"}

_ENTITY_SUFFIXES = {"llc", "inc", "corp", "co", "ltd", "lp", "llp", "trust"}

_AddressAdapter = Callable[[str], Dict[str, Any]]
_ParcelAdapter = Callable[[str], Dict[str, Any]]

_ADDRESS_ADAPTERS: Dict[str, _AddressAdapter] = {}
_PARCEL_ADAPTERS: Dict[str, _ParcelAdapter] = {}


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


def register_address_adapter(jurisdiction: str, adapter: _AddressAdapter) -> None:
    key = normalize_text(jurisdiction).replace(" ", "-")
    if key and callable(adapter):
        _ADDRESS_ADAPTERS[key] = adapter


def register_parcel_adapter(jurisdiction: str, adapter: _ParcelAdapter) -> None:
    key = normalize_text(jurisdiction).replace(" ", "-")
    if key and callable(adapter):
        _PARCEL_ADAPTERS[key] = adapter


def _normalize_tokens(value: str) -> list[str]:
    clean = _NON_ALNUM.sub(" ", value)
    clean = _WHITESPACE.sub(" ", clean).strip()
    return [token for token in clean.split(" ") if token]


def normalize_address_record(raw: Any, *, jurisdiction: Optional[str] = None) -> dict[str, Any]:
    raw_value = str(raw or "").strip()
    if not raw_value:
        return {
            "raw": "",
            "normalized": "",
            "components": {},
            "quality": "bad",
            "format": "generic",
        }
    adapter_key = normalize_text(jurisdiction).replace(" ", "-") if jurisdiction else ""
    if adapter_key and adapter_key in _ADDRESS_ADAPTERS:
        return _ADDRESS_ADAPTERS[adapter_key](raw_value)

    tokens = _normalize_tokens(raw_value.lower())
    house_number = tokens[0] if tokens and tokens[0].isdigit() else ""
    idx = 1 if house_number else 0
    predirectional = _DIRECTIONALS.get(tokens[idx], "") if idx < len(tokens) else ""
    if predirectional:
        idx += 1
    remaining = tokens[idx:]
    unit = ""
    if remaining:
        for i, token in enumerate(remaining):
            if token in _UNIT_TOKENS and i + 1 < len(remaining):
                unit = remaining[i + 1]
                remaining = remaining[:i]
                break
    suffix = _ADDRESS_SUFFIXES.get(remaining[-1], "") if remaining else ""
    if suffix:
        remaining = remaining[:-1]
    street_name = " ".join(remaining)

    normalized_parts = [
        part for part in [house_number, predirectional, street_name, suffix] if part
    ]
    if unit:
        normalized_parts.append(f"unit {unit}")
    normalized = " ".join(normalized_parts).strip()

    quality = "ok" if house_number and street_name else ("partial" if house_number or street_name else "bad")
    return {
        "raw": raw_value,
        "normalized": normalized,
        "components": {
            "house_number": house_number,
            "predirectional": predirectional,
            "street_name": street_name,
            "street_suffix": suffix,
            "unit": unit,
        },
        "quality": quality,
        "format": "generic",
    }


def normalize_owner_name(raw: Any) -> dict[str, Any]:
    raw_value = str(raw or "").strip()
    if not raw_value:
        return {
            "raw": "",
            "normalized": "",
            "display_name": "",
            "kind": "unknown",
            "tokens": [],
        }
    lowered = raw_value.lower()
    tokens = _normalize_tokens(lowered)
    has_suffix = any(token in _ENTITY_SUFFIXES for token in tokens)
    kind = "entity" if has_suffix else "person"
    tokens_no_suffix = [token for token in tokens if token not in _ENTITY_SUFFIXES]

    normalized = " ".join(tokens_no_suffix).strip()
    if "," in raw_value:
        parts = [part.strip() for part in raw_value.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            normalized = " ".join(_normalize_tokens(f"{parts[1]} {parts[0]}".lower()))
            kind = "person"

    display_tokens = [token.capitalize() for token in tokens_no_suffix] if tokens_no_suffix else []
    display_name = " ".join(display_tokens).strip()
    return {
        "raw": raw_value,
        "normalized": normalized,
        "display_name": display_name,
        "kind": kind,
        "tokens": tokens_no_suffix,
    }


def normalize_parcel_id(raw: Any, *, jurisdiction: Optional[str] = None) -> dict[str, Any]:
    raw_value = str(raw or "").strip()
    if not raw_value:
        return {
            "raw": "",
            "normalized": "",
            "alternate_forms": [],
            "format": "generic",
        }
    adapter_key = normalize_text(jurisdiction).replace(" ", "-") if jurisdiction else ""
    if adapter_key and adapter_key in _PARCEL_ADAPTERS:
        return _PARCEL_ADAPTERS[adapter_key](raw_value)

    normalized = re.sub(r"[^a-z0-9]+", "", raw_value.lower())
    groups = [token for token in re.split(r"[^a-z0-9]+", raw_value.lower()) if token]
    alternate = "-".join(groups) if len(groups) > 1 else ""
    alternate_forms = [alternate] if alternate else []
    return {
        "raw": raw_value,
        "normalized": normalized,
        "alternate_forms": alternate_forms,
        "format": "generic",
    }
