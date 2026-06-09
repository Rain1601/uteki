"""Seed the trigger table with the 4 active triggers (after the P8.5 IA
refactor — trg-event-003 + trg-earnings-002 were folded into trg-news-002).

Mirrors apps/web/lib/triggers.ts's TRIGGERS array so the frontend can
swap from hardcoded fixture → fetched data without behavior change.

watchlist_symbols changed format: the fixture used demo IDs like
"us-aapl", but the persisted column references company.symbol values
("AAPL"). Empty list means the trigger applies to all watchlist
companies (with cadence_minutes/0 = event-driven, that's the default
for the macro stream which isn't per-ticker).

Idempotent — TriggerStore.upsert handles re-runs cleanly.

Usage (from services/api/):
    uv run python scripts/seed_triggers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "src"))

from sqlmodel import Session  # noqa: E402

from uteki_api.core.db import engine, init_db  # noqa: E402
from uteki_api.triggers.store import default_trigger_store  # noqa: E402


SEED: list[dict] = [
    {
        "id": "trg-news-001",
        "name": "宏观经济 · 非公司个体新闻",
        "kind": "news",
        "skill": "uteki",
        "condition": (
            "CNBC macro feed (jeff-cox) + Fed / CPI / GDP / 政策事件。"
            "明确不收公司个体新闻 — 公司流走 trg-news-002。"
        ),
        "watchlist_symbols": [],
        "cadence_minutes": 30,
        "cadence_text": "每 30 分钟扫描",
        "earnings_window_hours": 0,
        "boost_in_earnings_window_minutes": 0,
        "enabled": True,
        "sort_order": 1,
    },
    {
        "id": "trg-news-002",
        "name": "公司监听 · 总流",
        "kind": "news",
        "skill": "uteki",
        "condition": (
            "watchlist 公司全部信号：Google News per-ticker + SEC 8-K "
            "(管理层/监管/并购) + 10-Q/10-K (财报) + IR/Newswire RSS。"
            "按 ticker 分组浏览，按 事件 tag 过滤。"
        ),
        "watchlist_symbols": ["AAPL", "NVDA", "MSFT", "GOOGL", "TSLA", "TSM"],
        "cadence_minutes": 60,
        "cadence_text": "Google News 60 分钟 · SEC 日次 · 财报窗口加速",
        # When a watchlist company's earnings event is within 6 hours, poll
        # SEC + Newswire every 5 minutes so we don't miss the 8-K landing.
        "earnings_window_hours": 6,
        "boost_in_earnings_window_minutes": 5,
        "enabled": True,
        "sort_order": 2,
    },
    {
        "id": "trg-price-004",
        "name": "价格 / 成交量异常",
        "kind": "price",
        "skill": "uteki",
        "condition": "price move > 5% OR volume > 2.5x 20D average",
        "watchlist_symbols": ["NVDA"],
        "cadence_minutes": 15,
        "cadence_text": "盘中每 15 分钟",
        "earnings_window_hours": 0,
        "boost_in_earnings_window_minutes": 0,
        "enabled": False,  # not implemented yet
        "sort_order": 3,
    },
    {
        "id": "trg-cron-005",
        "name": "每周组合复盘",
        "kind": "schedule",
        "skill": "research_pipeline",
        "condition": "cron: 0 17 * * 5",
        "watchlist_symbols": [],
        "cadence_minutes": 0,  # cron-driven, not interval polled
        "cadence_text": "每周五收盘后",
        "earnings_window_hours": 0,
        "boost_in_earnings_window_minutes": 0,
        "enabled": True,
        "sort_order": 4,
    },
]


def main() -> int:
    init_db()
    with Session(engine) as db:
        for spec in SEED:
            trig = default_trigger_store.upsert(
                db,
                id=spec["id"],
                name=spec["name"],
                kind=spec["kind"],
                skill=spec["skill"],
                condition=spec["condition"],
                watchlist_symbols=",".join(spec["watchlist_symbols"]),
                cadence_minutes=spec["cadence_minutes"],
                cadence_text=spec["cadence_text"],
                earnings_window_hours=spec["earnings_window_hours"],
                boost_in_earnings_window_minutes=spec["boost_in_earnings_window_minutes"],
                enabled=spec["enabled"],
                sort_order=spec["sort_order"],
            )
            print(f"  · {trig.id:<16} {trig.name}")
    print(f"✓ seeded {len(SEED)} triggers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
