"""Trigger registry.

Triggers cause agent runs to happen without a human typing into the chat:

- **CronTrigger**: cron expression → fire run at schedule.
  e.g. 工作日盘后 16:00 跑一次持仓回顾.
- **EventTrigger**: external webhook (新财报披露 / 突发新闻 / 价格突破阈值)
  → fire run with payload as context.

This module only registers definitions. Actual scheduling is wired in
`main.py`'s lifespan (apscheduler) and event endpoints in `api/triggers.py`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CronTrigger(BaseModel):
    id: str
    kind: Literal["cron"] = "cron"
    cron: str            # e.g. "0 16 * * 1-5"
    agent: str           # which skill to run
    prompt: str          # the user message to feed it
    enabled: bool = True


class EventTrigger(BaseModel):
    id: str
    kind: Literal["event"] = "event"
    topic: str           # e.g. "earnings_release", "breaking_news", "price_alert"
    agent: str
    prompt_template: str  # may interpolate `{title}`, `{symbol}`, etc.
    enabled: bool = True


Trigger = CronTrigger | EventTrigger


class TriggerRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Trigger] = {}

    def register(self, trigger: Trigger) -> None:
        self._items[trigger.id] = trigger

    def list(self) -> list[Trigger]:
        return list(self._items.values())

    def by_topic(self, topic: str) -> list[EventTrigger]:
        return [
            t for t in self._items.values()
            if isinstance(t, EventTrigger) and t.enabled and t.topic == topic
        ]

    def crons(self) -> list[CronTrigger]:
        return [t for t in self._items.values() if isinstance(t, CronTrigger) and t.enabled]


default_triggers = TriggerRegistry()
# Example seeds — remove or replace in production
default_triggers.register(
    CronTrigger(
        id="daily-recap",
        cron="0 16 * * 1-5",
        agent="research",
        prompt="给我今天 A 股的盘后概要，重点关注我关注的板块。",
    )
)
default_triggers.register(
    EventTrigger(
        id="earnings-watch",
        topic="earnings_release",
        agent="research",
        prompt_template="{symbol} 刚发布了财报：{title}。请分析关键指标和潜在影响。",
    )
)

# M7: maintenance task — not a skill run. The scheduler wiring (apscheduler)
# is still TODO; until then, this is documentation + a hook point. When the
# scheduler lands, it should detect agent="__maintenance__" and dispatch to
# `eval.drift_monitor.check_drift()` directly instead of calling `harness.run`.
default_triggers.register(
    CronTrigger(
        id="daily-eval-drift-check",
        cron="0 18 * * *",
        agent="__maintenance__",
        prompt="uteki_api.eval.drift_monitor.check_drift",
    )
)
