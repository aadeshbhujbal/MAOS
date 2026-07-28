-- 002_audit_grants.sql
-- Enforce append-only behavior on audit_log via DB grants (Req 10.3).
-- The application role (maos_app) may only INSERT and SELECT — no UPDATE or DELETE.

GRANT INSERT, SELECT ON audit_log TO maos_app;
