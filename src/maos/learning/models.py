"""Continuous Learning domain contracts for MAOS.

This module defines the models used by the post-task learning pipeline to
track extracted patterns, conventions, and learning history:

- ``LearnedPattern`` — a reusable pattern extracted from completed tasks (Req 16.1).
- ``Convention`` — a team coding convention detected across multiple tasks (Req 16.4).
- ``LearningRecord`` — an audit record of what was learned from a single task (Req 16.6).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the Learning System and Hypothesis correctness properties can construct and
reason about them deterministically.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LearnedPattern(BaseModel):
    """A reusable pattern extracted from completed tasks (Req 16.1, 16.2)."""

    pattern_id: str
    pattern_type: str
    description: str
    source_task_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    applicable_domains: list[str] = []


class Convention(BaseModel):
    """A team coding convention detected across multiple tasks (Req 16.4)."""

    convention_id: str
    category: str
    pattern: str
    examples: list[str] = []
    frequency: int = Field(ge=0)
    conflicts_with: list[str] = []


class LearningRecord(BaseModel):
    """Audit record of what was learned from a single completed task (Req 16.6)."""

    record_id: str
    task_id: str
    learned_at: datetime
    patterns: list[LearnedPattern] = []
    conventions_updated: list[str] = []
    graph_nodes_added: int = Field(ge=0, default=0)
    embeddings_updated: int = Field(ge=0, default=0)
