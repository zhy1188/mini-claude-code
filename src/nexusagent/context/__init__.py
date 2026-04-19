"""Context management package."""

from nexusagent.context.builder import PromptBuilder
from nexusagent.context.manager import ContextManager
from nexusagent.context.project_context import load_hierarchy_context
from nexusagent.context.retriever import ContextRetriever
from nexusagent.context.compaction import CompactionStrategy, CompactionCache

__all__ = [
    "PromptBuilder",
    "ContextManager",
    "load_hierarchy_context",
    "ContextRetriever",
    "CompactionStrategy",
    "CompactionCache",
]