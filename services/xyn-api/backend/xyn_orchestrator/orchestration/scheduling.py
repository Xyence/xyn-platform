from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TriggerKind = Literal["manual", "interval", "cron", "event"]


@dataclass(frozen=True)
class ScheduledTrigger:
    """Pipeline-level trigger definition resolved by the scheduler loop."""

    key: str
    kind: TriggerKind
    enabled: bool = True
    cron_expression: str = ""
    interval_seconds: int = 0
    timezone_name: str = "UTC"
    description: str = ""

    def validate(self) -> None:
        if not self.key.strip():
            raise ValueError("trigger key is required")
        if self.kind == "cron" and not self.cron_expression.strip():
            raise ValueError("cron trigger requires cron_expression")
        if self.kind == "interval" and int(self.interval_seconds or 0) <= 0:
            raise ValueError("interval trigger requires interval_seconds > 0")
