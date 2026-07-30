"""Knowledge Graph domain contracts for MAOS.

This module defines the code-entity and relationship models used by the PostgreSQL-backed
Knowledge Graph client and the Code Intelligence subsystem:

- ``NodeType`` — enumeration of recognised code-graph node categories (Req 12.1).
- ``RelationType`` — enumeration of directed edge semantics (Req 12.2).
- ``CodeEntity`` — a node in the knowledge graph representing a code symbol (Req 22.3).
- ``CodeRelationship`` — a directed edge connecting two code entities (Req 22.4).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the Knowledge Graph client and Hypothesis properties can construct and reason
about them deterministically.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class NodeType(StrEnum):
    """Recognised code-graph node categories (Req 12.1)."""

    CONTROLLER = "CONTROLLER"
    SERVICE = "SERVICE"
    REPOSITORY = "REPOSITORY"
    DATABASE_TABLE = "DATABASE_TABLE"
    EXTERNAL_API = "EXTERNAL_API"
    FRONTEND_COMPONENT = "FRONTEND_COMPONENT"
    MOBILE_SCREEN = "MOBILE_SCREEN"
    TEST_SUITE = "TEST_SUITE"
    ADR = "ADR"


class RelationType(StrEnum):
    """Directed edge semantics for code relationships (Req 12.2)."""

    CALLS = "CALLS"
    DEPENDS_ON = "DEPENDS_ON"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    RENDERS = "RENDERS"
    TESTS = "TESTS"
    IMPORTS = "IMPORTS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    CIRCULAR_DEPENDENCY = "CIRCULAR_DEPENDENCY"
    GOVERNS = "GOVERNS"


class CodeEntity(BaseModel):
    """A node in the knowledge graph representing a code symbol (Req 22.3)."""

    entity_id: str
    node_type: NodeType
    file_path: str
    line_number: int
    module: str
    language: str
    last_updated: datetime
    properties: dict[str, str] = {}


class CodeRelationship(BaseModel):
    """A directed edge connecting two code entities (Req 22.4)."""

    source_id: str
    target_id: str
    rel_type: RelationType
    metadata: dict[str, str] = {}
