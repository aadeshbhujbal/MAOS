-- Add task_id to the approval table for traceability (Req 11.7, 11.8).
ALTER TABLE approval ADD COLUMN IF NOT EXISTS task_id TEXT;
