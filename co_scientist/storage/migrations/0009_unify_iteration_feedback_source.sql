-- Repair databases that already applied migration 0008 before the source name
-- was aligned with the public Iteration Orchestrator identity.
UPDATE system_feedback
   SET source = 'iteration_orchestrator'
 WHERE source = 'iteration_synthesis';
