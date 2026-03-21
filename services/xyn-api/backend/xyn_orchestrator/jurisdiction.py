from __future__ import annotations

import re
from typing import Optional


_CANONICAL_JURISDICTION_RE = re.compile(r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*-(city|county)$")


def normalize_jurisdiction(value: str | None) -> str:
    return str(value or "").strip().lower()


def is_canonical_jurisdiction(value: str | None) -> bool:
    token = normalize_jurisdiction(value)
    if not token:
        return True
    return bool(_CANONICAL_JURISDICTION_RE.match(token))


def require_canonical_jurisdiction(value: str | None, *, context: str = "jurisdiction") -> str:
    token = normalize_jurisdiction(value)
    if not token:
        return ""
    if not is_canonical_jurisdiction(token):
        raise ValueError(
            f"{context} must use canonical form (e.g. mo-stl-city, mo-stl-county). "
            f"Got '{value}'."
        )
    return token


def maybe_canonicalize_jurisdiction(value: str | None) -> Optional[str]:
    token = normalize_jurisdiction(value)
    return token or None
