"""Compatibility shim — `ResearchAgent` now lives in `uteki_api.skills.research`.

Kept as a thin re-export so existing imports continue to work during the
skill-registry migration.
"""

from __future__ import annotations

from uteki_api.skills.research import ResearchAgent  # noqa: F401

__all__ = ["ResearchAgent"]
