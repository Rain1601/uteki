"""Pipeline meta-skills — compose multiple skills into one harness run.

A pipeline is a ``BaseAgent`` that does not call the LLM itself; instead it
delegates to other registered skills (Planner → Generator → Evaluator) and
re-yields their events upstream. Shared state (tool executor, artifacts
facade) is propagated to sub-skills via plain attribute assignment so the
sub-skill behaves exactly as it would under its own harness run, minus
duplicate book-keeping.
"""

from __future__ import annotations

from uteki_api.skills.pipelines.research_pipeline import ResearchPipeline

__all__ = ["ResearchPipeline"]
