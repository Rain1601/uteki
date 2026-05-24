"""Evolution package — skill version history + changelog computation."""

from __future__ import annotations

from uteki_api.evolution.store import (
    EvolutionStore,
    InMemoryEvolutionStore,
    default_evolution_store,
)
from uteki_api.evolution.versions import SkillVersion, compute_changelog

__all__ = [
    "SkillVersion",
    "EvolutionStore",
    "InMemoryEvolutionStore",
    "default_evolution_store",
    "compute_changelog",
]
