"""
Work IQ Panel Agents - Multi-agent system for dynamic panel section generation.

Each agent runs independently and in parallel to populate different panel sections:
- SuggestionsAgent: Generates context-aware suggestion chips
- TimelineAgent: Builds chronological event timeline
- NextStepsAgent: Generates follow-up actions
- ProgressAgent: Aggregates session metrics
"""

from .suggestions_agent import SuggestionsAgent
from .timeline_agent import TimelineAgent
from .nextsteps_agent import NextStepsAgent
from .progress_agent import ProgressAgent

__all__ = [
    'SuggestionsAgent',
    'TimelineAgent', 
    'NextStepsAgent',
    'ProgressAgent',
]
