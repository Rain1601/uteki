from uteki_api.memory.base import Memory
from uteki_api.memory.in_memory import InMemoryStore

default_memory: Memory = InMemoryStore()

__all__ = ["Memory", "InMemoryStore", "default_memory"]
