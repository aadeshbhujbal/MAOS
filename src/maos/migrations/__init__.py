"""Database migrations for MAOS.

Migration files are applied in lexicographic order:
  001_initial_schema.sql  — Full Postgres schema (tables, indexes, constraints)
  002_audit_grants.sql    — Append-only grant policy on audit_log
  003_approval_task_id.sql — Approval task ID column addition

Runner:
  python -m maos.migrations.run   — Applies pending migrations via the runner script.
"""
