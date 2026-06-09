"""Idempotently seed a default tag taxonomy + a handful of demo news
articles + trigger hits so the /tasks/[id] detail page has content.

Usage (from services/api/):
    uv run python scripts/seed_news_demo.py

Safe to re-run — every insertion checks by name/url first. Designed to
match the frontend's hardcoded trigger fixtures (trg-news-001, …) so
the article list shows up next to the right trigger.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Make the package importable when run directly.
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from uteki_api.core.db import engine, init_db  # noqa: E402
from uteki_api.news.models import (  # noqa: E402
    NewsArticle,
    Tag,
    TagGroup,
    TriggerHit,
)
from uteki_api.news.store import default_news_store as ns  # noqa: E402


# ─── Taxonomy ────────────────────────────────────────────────────────


DEFAULT_TAXONOMY: list[dict] = [
    {
        "name": "重要度",
        "description": "事件对市场的可能影响程度",
        "mode": "single",
        "sort_order": 0,
        "tags": [
            ("critical", "市场级影响 / 系统性风险", "#b0524a"),
            ("high", "板块级影响 / 主要个股", "#c9a97e"),
            ("medium", "局部影响 / 二级板块", "#6f8db0"),
            ("low", "信息流 / 低优先级", None),
        ],
    },
    {
        "name": "类别",
        "description": "资产或主题分类（可多选）",
        "mode": "multi",
        "sort_order": 1,
        "tags": [
            ("macro", "宏观 / 央行 / 利率", None),
            ("equities", "美股 / 港股 / A股", None),
            ("crypto", "加密资产", None),
            ("forex", "外汇 / 大宗", None),
        ],
    },
    {
        "name": "事件",
        "description": "事件类型（可多选）",
        "mode": "multi",
        "sort_order": 2,
        "tags": [
            ("earnings", "财报 / 业绩指引", None),
            ("regulation", "监管 / 反垄断 / 制裁", None),
            ("m_and_a", "并购 / 拆分", None),
            ("guidance", "业绩指引上调 / 下调", None),
        ],
    },
]


def ensure_taxonomy(db: Session) -> dict[str, str]:
    """Returns {tag_name: tag_id} flat map for downstream article seeding."""
    tag_id_by_name: dict[str, str] = {}
    for spec in DEFAULT_TAXONOMY:
        group = db.exec(select(TagGroup).where(TagGroup.name == spec["name"])).first()
        if group is None:
            group = ns.create_tag_group(
                db,
                name=spec["name"],
                description=spec["description"],
                mode=spec["mode"],
                sort_order=spec["sort_order"],
            )
            print(f"  + group {group.name} ({group.mode})")
        for name, desc, color in spec["tags"]:
            existing = db.exec(
                select(Tag).where(Tag.group_id == group.id, Tag.name == name)
            ).first()
            if existing is None:
                t = ns.create_tag(
                    db,
                    group_id=group.id,
                    name=name,
                    description=desc,
                    color=color,
                )
                tag_id_by_name[name] = t.id
                print(f"    · tag {name}")
            else:
                tag_id_by_name[name] = existing.id
    return tag_id_by_name


# ─── Articles ────────────────────────────────────────────────────────


def _now_minus(hours: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


DEMO_ARTICLES: list[dict] = [
    {
        "url": "demo://fed-pause-rate-hikes",
        "title": "Fed signals end of rate-hike cycle after softer CPI",
        "title_zh": "美联储释放停止加息信号，CPI 数据低于预期",
        "summary": "Powell told the press the FOMC is now data-dependent and sees inflation trending toward target without further tightening.",
        "summary_zh": "鲍威尔表示 FOMC 已转入数据依赖模式，认为无需进一步紧缩通胀仍可向 2% 回落。",
        "source": "cnbc",
        "symbols": "SPY,QQQ,TLT,DXY",
        "published_at": _now_minus(2),
        "trigger_id": "trg-news-001",
        "tags": ["critical", "macro"],
    },
    {
        "url": "demo://nvda-blackwell-supply",
        "title": "NVIDIA tightens Blackwell allocations as hyperscalers prebook 2027 capacity",
        "title_zh": "英伟达收紧 Blackwell 配额，云厂商提前锁定 2027 产能",
        "summary": "Allocations now span 18-month windows, locking margin upside through next two fiscal years.",
        "summary_zh": "配额时间窗已经拉到 18 个月，未来两个财年的利润率上行被锁定。",
        "source": "cnbc",
        "symbols": "NVDA,AVGO,AMD",
        "published_at": _now_minus(6),
        "trigger_id": "trg-news-001",
        "tags": ["high", "equities", "guidance"],
    },
    {
        "url": "demo://aapl-china-launch-delay",
        "title": "Apple delays China launch of iPhone 17 Pro by 3 weeks",
        "title_zh": "苹果 iPhone 17 Pro 中国发布推迟三周",
        "summary": "Regulatory approval timing cited; supply chain unchanged. Channel checks suggest minimal Q1 revenue impact.",
        "summary_zh": "苹果援引监管审批时间表，供应链未受影响。渠道数据显示对 Q1 收入影响较小。",
        "source": "cnbc",
        "symbols": "AAPL",
        "published_at": _now_minus(14),
        "trigger_id": "trg-news-001",
        "tags": ["medium", "equities", "regulation"],
    },
    {
        "url": "demo://msft-earnings-prep",
        "title": "Microsoft Q3 earnings: Azure growth + AI capex pacing in focus",
        "title_zh": "微软 Q3 财报前瞻：Azure 增速与 AI 资本开支节奏成关键",
        "summary": "Street looking for Azure rev growth 28-30% YoY; capex guidance is the swing factor for the stock reaction.",
        "summary_zh": "市场预期 Azure 同比增速 28-30%；资本开支指引是股价反应的关键变量。",
        "source": "cnbc",
        "symbols": "MSFT",
        "published_at": _now_minus(24),
        "trigger_id": "trg-earnings-002",
        "tags": ["high", "equities", "earnings"],
    },
    {
        "url": "demo://googl-antitrust-remedy",
        "title": "DOJ files proposed remedies in Google search antitrust case",
        "title_zh": "美国司法部就谷歌搜索反垄断案提交补救方案",
        "summary": "Proposed structural remedies include forced Chrome divestiture and ten-year ban on default-search deals.",
        "summary_zh": "提议的结构性补救包括强制剥离 Chrome 业务及十年内禁止预装搜索协议。",
        "source": "cnbc",
        "symbols": "GOOGL,AAPL,META",
        "published_at": _now_minus(36),
        "trigger_id": "trg-event-003",
        "tags": ["critical", "equities", "regulation"],
    },
    {
        "url": "demo://tsla-china-discount",
        "title": "Tesla offers 10K RMB discount on Model Y in China amid demand softness",
        "title_zh": "特斯拉在华推出 Model Y 1 万元人民币优惠应对需求疲弱",
        "summary": "Second discount in three months. CFO previously said price cuts would be a 'last resort'.",
        "summary_zh": "三个月内第二次降价。此前 CFO 表示降价是 '最后手段'。",
        "source": "cnbc",
        "symbols": "TSLA",
        "published_at": _now_minus(48),
        "trigger_id": "trg-event-003",
        "tags": ["medium", "equities", "guidance"],
    },
    {
        "url": "demo://btc-etf-inflows-record",
        "title": "Spot Bitcoin ETFs see record $1.2B daily inflow",
        "title_zh": "比特币现货 ETF 单日净流入创纪录 12 亿美元",
        "summary": "IBIT alone captured $743M; mark-up pace at strongest since January launch window.",
        "summary_zh": "IBIT 单只产品净流入 7.43 亿美元；当月吸金强度为 1 月上市以来最高。",
        "source": "cnbc",
        "symbols": "BTC,IBIT,COIN",
        "published_at": _now_minus(72),
        "trigger_id": "trg-price-004",
        "tags": ["high", "crypto"],
    },
    {
        "url": "demo://weekly-review-2026-w23",
        "title": "Weekly portfolio review · 2026 W23",
        "title_zh": "每周组合复盘 · 2026 第 23 周",
        "summary": "Tech leadership intact; energy lagging; bond curve flattening signals policy ambiguity.",
        "summary_zh": "科技继续领涨；能源走弱；债券曲线趋平显示政策不确定性。",
        "source": "internal",
        "symbols": "SPY,QQQ,XLE,TLT",
        "published_at": _now_minus(96),
        "trigger_id": "trg-cron-005",
        "tags": ["medium", "macro"],
    },
]


def ensure_articles(db: Session, tag_id_by_name: dict[str, str]) -> None:
    for spec in DEMO_ARTICLES:
        existing = db.exec(
            select(NewsArticle).where(NewsArticle.url == spec["url"])
        ).first()
        if existing is not None:
            print(f"  · already seeded: {spec['title'][:60]}")
            continue
        article = ns.upsert_article(
            db,
            title=spec["title"],
            title_zh=spec["title_zh"],
            summary=spec["summary"],
            summary_zh=spec["summary_zh"],
            content=spec["summary"],
            content_zh=spec["summary_zh"],
            url=spec["url"],
            source=spec["source"],
            symbols=spec["symbols"],
            published_at=spec["published_at"],
        )
        tag_ids = [tag_id_by_name[name] for name in spec["tags"] if name in tag_id_by_name]
        ns.set_article_tags(db, article.id, tag_ids)

        # Idempotency on the hit: only insert if not already linked.
        hit_exists = db.exec(
            select(TriggerHit).where(
                TriggerHit.trigger_id == spec["trigger_id"],
                TriggerHit.article_id == article.id,
            )
        ).first()
        if hit_exists is None:
            ns.record_trigger_hit(
                db,
                trigger_id=spec["trigger_id"],
                article_id=article.id,
                fired_at=spec["published_at"],
            )
        print(f"  + article: {spec['title'][:60]}")


def main() -> int:
    print("▶ ensuring tables exist")
    init_db()
    with Session(engine) as db:
        print("▶ ensuring taxonomy")
        tag_id_by_name = ensure_taxonomy(db)
        print("▶ ensuring demo articles + trigger hits")
        ensure_articles(db, tag_id_by_name)
    print("✓ done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
