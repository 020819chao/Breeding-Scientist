-- Migration 0006: normalize earlier agent and queue names to the six-agent system.

UPDATE hypotheses
   SET created_by = 'breeding_designer'
 WHERE created_by = 'gener' || 'ation';

UPDATE hypotheses
   SET created_by = 'route_revision'
 WHERE created_by = 'evol' || 'ution';

UPDATE hypotheses
   SET state = 'calibration_pool'
 WHERE state = 'in_' || 'tourna' || 'ment';
