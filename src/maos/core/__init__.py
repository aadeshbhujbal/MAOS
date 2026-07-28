"""Pure, framework-agnostic orchestration core.

Houses side-effect-free logic (validation, decomposition, deterministic
selection, the work-unit state machine, aggregation, budget accounting, scope
checks, reassignment) wrapped later by LangGraph nodes and FastAPI handlers.
"""
