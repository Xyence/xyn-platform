from __future__ import annotations

from typing import Final

SUPPORTED_SCHEDULE_KINDS_V1: Final[tuple[str, ...]] = ("manual", "interval")
UNSUPPORTED_SCHEDULE_KINDS_V1: Final[tuple[str, ...]] = ("cron",)
SUPPORTED_POLLED_SCHEDULE_KINDS_V1: Final[tuple[str, ...]] = ("interval",)

CRON_UNSUPPORTED_MESSAGE: Final[str] = (
    "Cron scheduling is intentionally unsupported in orchestration v1. "
    "Do not use or imply cron scheduling until platform cron support is explicitly implemented and accepted."
)


def supported_schedule_kinds() -> tuple[str, ...]:
    return SUPPORTED_SCHEDULE_KINDS_V1


def unsupported_schedule_kinds() -> tuple[str, ...]:
    return UNSUPPORTED_SCHEDULE_KINDS_V1


def polled_schedule_kinds() -> tuple[str, ...]:
    return SUPPORTED_POLLED_SCHEDULE_KINDS_V1


def is_supported_schedule_kind(kind: str) -> bool:
    return str(kind or "").strip() in SUPPORTED_SCHEDULE_KINDS_V1


def is_polled_schedule_kind(kind: str) -> bool:
    return str(kind or "").strip() in SUPPORTED_POLLED_SCHEDULE_KINDS_V1
