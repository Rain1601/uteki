"""Skills package — the catalog of named agents the API exposes.

`default_skills` is the singleton registry; each skill class is also re-exported
here for convenience. Registration is synchronous at import time so that the
FastAPI app sees a populated registry before its lifespan runs.

M6: registers two new leaf skills (Planner, Evaluator) and one pipeline
meta-skill (ResearchPipeline) that strings them together with Research.
"""

from __future__ import annotations

from uteki_api.skills.earnings import EarningsSkill
from uteki_api.skills.evaluator import EvaluatorSkill
from uteki_api.skills.pipelines import ResearchPipeline
from uteki_api.skills.planner import PlannerSkill
from uteki_api.skills.qna import QnaSkill
from uteki_api.skills.recap import RecapSkill
from uteki_api.skills.registry import SkillEntry, SkillRegistry, default_skills
from uteki_api.skills.research import ResearchAgent
from uteki_api.skills.screener import ScreenerSkill

# --- register built-in skills ------------------------------------------------

_research = ResearchAgent()
default_skills.register(
    _research,
    description="行业 / 主题研究：sector overview · 竞争格局 · peer comps · ideas shortlist · 笔记草稿。",
    version="v2",
    default_tools=list(ResearchAgent.DEFAULT_TOOLS),
    default_model=ResearchAgent.DEFAULT_MODEL,
)

_earnings = EarningsSkill()
default_skills.register(
    _earnings,
    description="财报评审：读电话会、量化变动、起草点评草稿（M2 暂需用户粘贴 transcript）。",
    version="v1",
    default_tools=list(EarningsSkill.DEFAULT_TOOLS),
    default_model=EarningsSkill.DEFAULT_MODEL,
)

_recap = RecapSkill()
default_skills.register(
    _recap,
    description="盘后复盘：回顾大盘、盘点持仓、总结当日亮点与风险。",
    version="v1",
    default_tools=list(RecapSkill.DEFAULT_TOOLS),
    default_model=RecapSkill.DEFAULT_MODEL,
)

_screener = ScreenerSkill()
default_skills.register(
    _screener,
    description="多因子选股：拉行情、过滤、排序，输出 Top 5 候选与理由。",
    version="v1",
    default_tools=list(ScreenerSkill.DEFAULT_TOOLS),
    default_model=ScreenerSkill.DEFAULT_MODEL,
)

_qna = QnaSkill()
default_skills.register(
    _qna,
    description="极简问答：理解问题并给出简洁直接的回答。",
    version="v1",
    default_tools=list(QnaSkill.DEFAULT_TOOLS),
    default_model=QnaSkill.DEFAULT_MODEL,
)

_planner = PlannerSkill()
default_skills.register(
    _planner,
    description="拆解需求：把一句话研究意图扩成 plan.md + sprint-contract.json。不调工具。",
    version="v1",
    default_tools=list(PlannerSkill.DEFAULT_TOOLS),
    default_model=PlannerSkill.DEFAULT_MODEL,
)

_evaluator = EvaluatorSkill()
default_skills.register(
    _evaluator,
    description="按 sprint contract 跑 verifier 评判 draft，输出 eval-report.json。skeptical by default。",
    version="v1",
    default_tools=list(EvaluatorSkill.DEFAULT_TOOLS),
    default_model=EvaluatorSkill.DEFAULT_MODEL,
)

_research_pipeline = ResearchPipeline()
default_skills.register(
    _research_pipeline,
    description="完整研究流水线：Planner → Research → Evaluator → 必要时迭代（max 3 轮）。",
    version="v1",
    default_tools=list(ResearchPipeline.DEFAULT_TOOLS),
    default_model=ResearchPipeline.DEFAULT_MODEL,
    kind="pipeline",
)


__all__ = [
    "SkillRegistry",
    "SkillEntry",
    "default_skills",
    "ResearchAgent",
    "EarningsSkill",
    "RecapSkill",
    "ScreenerSkill",
    "QnaSkill",
    "PlannerSkill",
    "EvaluatorSkill",
    "ResearchPipeline",
]
