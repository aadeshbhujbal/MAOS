"""Agentic RAG — autonomous retrieval-augmented generation decision logic.

The ``AgenticRAG`` class determines whether an agent should query the Knowledge
Base for a given Sub_Subtask or proceed with its own context. The decision is
based on signal detection in the task description:

- **Domain-specific terminology** — medical protocols, coding standards, platform
  keywords that indicate external knowledge may be required.
- **Documentation references** — explicit mentions of specs, standards, guides,
  or configuration documents.
- **Knowledge-seeking intent** — phrases like "according to", "as defined in",
  "per the standard" that signal the task expects grounding in stored knowledge.

When retrieval is triggered, results are written to the task's Shared Context
so that other agents on the same task can access the retrieved knowledge without
re-querying.

References
----------
- Req 4.1: Assess whether task requires domain knowledge beyond agent context.
- Req 4.2: Invoke Retrieval Tool when external knowledge is needed.
- Req 4.3: Proceed without querying when agent context is sufficient.
- Req 4.4: Decision based on domain terminology, doc references, intent phrases.
- Req 4.5: Incorporate retrieved content into reasoning context.
- Req 4.6: On zero results, proceed with own context and note in metadata.
- Req 4.7: Record retrieval decision and rationale in audit trail.
- Req 9.3: Write retrieval results to task's Shared Context.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from maos.context.models import AgentContext
from maos.contracts.work_units import SubSubtask
from maos.knowledge.models import SearchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision signals — keyword and phrase sets for assessment
# ---------------------------------------------------------------------------

#: Domain-specific terminology that suggests external knowledge is needed.
DOMAIN_TERMINOLOGY: frozenset[str] = frozenset(
    {
        # Medical / healthcare domain
        "hipaa",
        "hl7",
        "fhir",
        "icd-10",
        "cpt",
        "phi",
        "dicom",
        "snomed",
        "loinc",
        "npi",
        "edi",
        "cms",
        # Engineering standards
        "owasp",
        "pci-dss",
        "soc2",
        "iso-27001",
        "gdpr",
        "wcag",
        # Platform-specific
        "kubernetes",
        "terraform",
        "helm",
        "docker",
        "grafana",
        "prometheus",
        "opentelemetry",
        # Architecture patterns
        "microservice",
        "event-driven",
        "cqrs",
        "saga",
        "circuit-breaker",
    }
)

#: Phrases indicating references to documentation or specifications.
DOCUMENTATION_REFERENCES: tuple[str, ...] = (
    "documentation",
    "specification",
    "spec",
    "standard",
    "protocol",
    "guideline",
    "policy",
    "procedure",
    "runbook",
    "playbook",
    "architecture decision record",
    "adr",
    "design doc",
    "rfc",
    "api contract",
    "schema definition",
    "migration guide",
    "configuration reference",
)

#: Intent phrases that signal the task expects grounding in stored knowledge.
KNOWLEDGE_SEEKING_INTENT: tuple[str, ...] = (
    "according to",
    "as defined in",
    "per the standard",
    "based on the",
    "refer to",
    "as documented",
    "following the",
    "in compliance with",
    "as specified by",
    "consistent with",
    "aligned with",
    "as per",
    "what does",
    "how should",
    "what is the recommended",
    "best practice for",
    "what are the requirements for",
)


# ---------------------------------------------------------------------------
# Decision Model
# ---------------------------------------------------------------------------


class AgenticRAGDecision(BaseModel):
    """Result of the Agentic RAG assessment for a Sub_Subtask.

    Attributes
    ----------
    should_query : bool
        Whether the Knowledge Base should be queried.
    rationale : str
        Human-readable explanation of why the decision was made.
    signals : list[str]
        The specific signals detected that influenced the decision.
    """

    should_query: bool
    rationale: str
    signals: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Retrieval Result Wrapper
# ---------------------------------------------------------------------------


class RetrievalOutcome(BaseModel):
    """Outcome of a retrieval operation, including metadata for audit.

    Attributes
    ----------
    decision : AgenticRAGDecision
        The decision that triggered (or skipped) retrieval.
    results : list[SearchResult]
        Retrieved documents (empty if should_query was False or zero results).
    zero_results : bool
        True if retrieval was attempted but returned no results.
    """

    decision: AgenticRAGDecision
    results: list[SearchResult] = Field(default_factory=list)
    zero_results: bool = False


# ---------------------------------------------------------------------------
# AgenticRAG Class
# ---------------------------------------------------------------------------


class AgenticRAG:
    """Agentic RAG decision module for autonomous retrieval decisions.

    Determines whether an agent should query the Knowledge Base for a given
    Sub_Subtask or proceed with its own context, based on signal detection.

    Parameters
    ----------
    knowledge_store :
        The ``KnowledgeStore`` instance used for retrieval queries.
    shared_context_store :
        The ``SharedContextStore`` instance for writing results to task context.
    audit_logger :
        Optional callable for recording decisions to an audit trail.
        Signature: ``(entry: dict) -> None``.
    """

    def __init__(
        self,
        knowledge_store: Any = None,
        shared_context_store: Any = None,
        audit_logger: Any = None,
    ) -> None:
        self._knowledge_store = knowledge_store
        self._shared_context_store = shared_context_store
        self._audit_logger = audit_logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(
        self,
        sub_subtask: SubSubtask,
        agent_context: AgentContext,
    ) -> AgenticRAGDecision:
        """Assess whether a Sub_Subtask requires Knowledge Base retrieval (Req 4.1, 4.4).

        Analyzes the sub_subtask's input_contract and required_skill against
        known decision signals: domain terminology, documentation references,
        and knowledge-seeking intent phrases.

        Parameters
        ----------
        sub_subtask : SubSubtask
            The sub_subtask being processed by the agent.
        agent_context : AgentContext
            The current agent context (relevant files, branches, etc.).

        Returns
        -------
        AgenticRAGDecision
            The retrieval decision with rationale and detected signals.
        """
        # Extract text to analyze from the sub_subtask
        text_to_analyze = self._extract_analysis_text(sub_subtask)
        text_lower = text_to_analyze.lower()

        detected_signals: list[str] = []

        # Signal 1: Domain-specific terminology (Req 4.4)
        for term in DOMAIN_TERMINOLOGY:
            if term in text_lower:
                detected_signals.append(f"domain_term:{term}")

        # Signal 2: Documentation references (Req 4.4)
        for ref in DOCUMENTATION_REFERENCES:
            if ref in text_lower:
                detected_signals.append(f"doc_reference:{ref}")

        # Signal 3: Knowledge-seeking intent phrases (Req 4.4)
        for phrase in KNOWLEDGE_SEEKING_INTENT:
            if phrase in text_lower:
                detected_signals.append(f"intent:{phrase}")

        # Decision logic: query if any signals are detected
        should_query = len(detected_signals) > 0

        if should_query:
            rationale = (
                f"Detected {len(detected_signals)} signal(s) suggesting external "
                f"knowledge is needed: {', '.join(detected_signals[:5])}"
                + (" ..." if len(detected_signals) > 5 else "")
            )
        else:
            rationale = (
                "No domain terminology, documentation references, or "
                "knowledge-seeking intent detected. Agent context is sufficient."
            )

        decision = AgenticRAGDecision(
            should_query=should_query,
            rationale=rationale,
            signals=detected_signals,
        )

        # Record decision in audit trail (Req 4.7)
        self._record_decision(sub_subtask, decision)

        logger.info(
            "agentic_rag_decision",
            extra={
                "sub_subtask_id": sub_subtask.sub_subtask_id,
                "task_id": sub_subtask.task_id,
                "should_query": should_query,
                "signal_count": len(detected_signals),
                "rationale": rationale,
            },
        )

        return decision

    async def retrieve_if_needed(
        self,
        decision: AgenticRAGDecision,
        namespace: tuple[str, ...],
        query: str = "",
        task_id: str = "",
        agent_id: str = "",
        k: int = 5,
    ) -> RetrievalOutcome:
        """Invoke the Retrieval Tool if should_query is True (Req 4.2, 4.3).

        When ``decision.should_query`` is True, performs a vector similarity
        search against the Knowledge Store within the specified namespace.
        Results are written to the task's Shared Context for other agents
        (Req 9.3).

        On zero results, proceeds with own context and notes in metadata
        (Req 4.6).

        Parameters
        ----------
        decision : AgenticRAGDecision
            The assessment decision from ``assess()``.
        namespace : tuple[str, ...]
            The namespace to search within (tenant_id, agent_role).
        query : str
            The search query string. If empty, uses the rationale signals.
        task_id : str
            Task ID for writing results to Shared Context.
        agent_id : str
            Agent ID for Shared Context attribution.
        k : int
            Number of results to retrieve (default 5, range 1-20).

        Returns
        -------
        RetrievalOutcome
            The retrieval outcome including results and metadata.
        """
        if not decision.should_query:
            logger.info(
                "agentic_rag_skip",
                extra={
                    "task_id": task_id,
                    "rationale": decision.rationale,
                },
            )
            return RetrievalOutcome(decision=decision, results=[], zero_results=False)

        # Clamp k to valid range [1, 20]
        k = max(1, min(20, k))

        # Perform retrieval via Knowledge Store (Req 4.2)
        results: list[SearchResult] = []
        if self._knowledge_store is not None:
            try:
                results = await self._knowledge_store.search(
                    namespace=namespace,
                    query=query,
                    k=k,
                )
            except Exception as exc:
                logger.error(
                    "agentic_rag_retrieval_error",
                    extra={
                        "task_id": task_id,
                        "namespace": namespace,
                        "error": str(exc),
                    },
                )
                # On retrieval error, proceed with own context (graceful degradation)
                return RetrievalOutcome(decision=decision, results=[], zero_results=True)

        zero_results = len(results) == 0

        if zero_results:
            # Req 4.6: proceed with own context, note in metadata
            logger.info(
                "agentic_rag_zero_results",
                extra={
                    "task_id": task_id,
                    "namespace": namespace,
                    "query": query,
                },
            )
        else:
            logger.info(
                "agentic_rag_retrieved",
                extra={
                    "task_id": task_id,
                    "namespace": namespace,
                    "result_count": len(results),
                    "top_score": results[0].relevance_score if results else 0.0,
                },
            )

            # Req 9.3: Write retrieval results to task's Shared Context
            await self._write_to_shared_context(
                task_id=task_id,
                agent_id=agent_id,
                results=results,
            )

        outcome = RetrievalOutcome(
            decision=decision,
            results=results,
            zero_results=zero_results,
        )

        # Record retrieval outcome in audit trail (Req 4.7)
        self._record_retrieval_outcome(task_id, outcome)

        return outcome

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_analysis_text(sub_subtask: SubSubtask) -> str:
        """Extract text content from a SubSubtask for signal analysis.

        Combines the required_skill and input_contract fields into a single
        string for keyword and phrase matching.
        """
        parts: list[str] = [sub_subtask.required_skill]

        # Extract description-like fields from input_contract
        input_contract = sub_subtask.input_contract
        if isinstance(input_contract, dict):
            for key in ("description", "task_description", "query", "prompt", "content"):
                value = input_contract.get(key)
                if isinstance(value, str):
                    parts.append(value)

            # Also check nested properties for description
            properties = input_contract.get("properties", {})
            if isinstance(properties, dict):
                for prop_value in properties.values():
                    if isinstance(prop_value, dict):
                        desc = prop_value.get("description", "")
                        if isinstance(desc, str):
                            parts.append(desc)

        return " ".join(parts)

    def _record_decision(
        self,
        sub_subtask: SubSubtask,
        decision: AgenticRAGDecision,
    ) -> None:
        """Record the RAG decision in the task audit trail (Req 4.7).

        Emits a structured audit entry with the decision rationale and signals.
        """
        audit_entry = {
            "action": "agentic_rag_decision",
            "sub_subtask_id": sub_subtask.sub_subtask_id,
            "task_id": sub_subtask.task_id,
            "tenant_id": sub_subtask.tenant_id,
            "should_query": decision.should_query,
            "rationale": decision.rationale,
            "signal_count": len(decision.signals),
            "signals": decision.signals[:10],  # cap for log brevity
        }

        if self._audit_logger is not None:
            try:
                self._audit_logger(audit_entry)
            except Exception as exc:
                logger.warning(
                    "audit_log_failed",
                    extra={"error": str(exc), "entry": audit_entry},
                )
        else:
            logger.info("audit_trail", extra=audit_entry)

    def _record_retrieval_outcome(
        self,
        task_id: str,
        outcome: RetrievalOutcome,
    ) -> None:
        """Record retrieval outcome in the audit trail (Req 4.7)."""
        audit_entry = {
            "action": "agentic_rag_retrieval",
            "task_id": task_id,
            "should_query": outcome.decision.should_query,
            "result_count": len(outcome.results),
            "zero_results": outcome.zero_results,
        }

        if self._audit_logger is not None:
            try:
                self._audit_logger(audit_entry)
            except Exception as exc:
                logger.warning(
                    "audit_log_failed",
                    extra={"error": str(exc), "entry": audit_entry},
                )
        else:
            logger.info("audit_trail", extra=audit_entry)

    async def _write_to_shared_context(
        self,
        task_id: str,
        agent_id: str,
        results: list[SearchResult],
    ) -> None:
        """Write retrieval results to the task's Shared Context (Req 9.3).

        Stores a summary of retrieved documents so other agents on the same
        task can access the knowledge without re-querying.
        """
        if self._shared_context_store is None or not task_id or not agent_id:
            return

        # Build a serializable summary of retrieval results
        results_summary: dict[str, Any] = {
            "retrieved_count": len(results),
            "documents": [
                {
                    "document_id": r.document_id,
                    "content": r.content[:500],  # truncate for context size
                    "relevance_score": r.relevance_score,
                    "source_filename": r.source_filename,
                }
                for r in results
            ],
        }

        try:
            await self._shared_context_store.write(
                task_id=task_id,
                agent_id=agent_id,
                key="knowledge_retrieval_results",
                value=results_summary,
            )
            logger.info(
                "shared_context_write",
                extra={
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "result_count": len(results),
                },
            )
        except Exception as exc:
            # Non-fatal: log but don't fail the retrieval operation
            logger.warning(
                "shared_context_write_failed",
                extra={
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "error": str(exc),
                },
            )
