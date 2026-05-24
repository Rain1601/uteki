"""LLM-as-judge subsystem.

Rubric markdown files (sibling of this ``__init__.py``) define scoring axes.
``JudgeRunner.judge(rubric_name, draft, run_events, avoid_model=...)`` calls
an LLM **different from the generator** and returns a ``JudgeScore``.

Per Anthropic's harness paper: the Generator does not judge itself; an
external evaluator with independent prompts catches mistakes the Generator
would talk itself into accepting.
"""

from __future__ import annotations

from uteki_api.eval.judges.runner import JudgeRunner, JudgeScore, default_judge_runner

__all__ = ["JudgeRunner", "JudgeScore", "default_judge_runner"]
