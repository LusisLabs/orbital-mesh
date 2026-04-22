CREATE INDEX IF NOT EXISTS idx_memory_items_scope ON memory_items USING gin(scope);
CREATE INDEX IF NOT EXISTS idx_memory_items_service ON memory_items ((scope->>'service'));
CREATE INDEX IF NOT EXISTS idx_memory_items_reason ON memory_items ((metadata->>'reason'));

CREATE INDEX IF NOT EXISTS idx_run_events_artifact_key ON run_events(artifact_key);
CREATE INDEX IF NOT EXISTS idx_run_events_scenario_analysis
  ON run_events(run_id, sequence)
  WHERE event_type IN (
    'evidence_node_recorded',
    'subdecision_recorded',
    'scenario_analysis_ready',
    'memory_compaction_recorded'
  );
