CREATE TABLE IF NOT EXISTS benchmark_records (
  benchmark_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  scenario_id TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  score DOUBLE PRECISION NOT NULL,
  passed BOOLEAN NOT NULL,
  payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_benchmark_records_scenario ON benchmark_records(scenario_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_benchmark_records_run ON benchmark_records(run_id);
