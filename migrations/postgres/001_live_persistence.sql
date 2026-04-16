CREATE TABLE IF NOT EXISTS goals (
  goal_id TEXT PRIMARY KEY,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  goal_id TEXT NULL,
  scenario_key TEXT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL,
  event_id TEXT NOT NULL UNIQUE,
  stage TEXT NOT NULL,
  event_type TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL,
  summary JSONB NULL,
  merkle_leaf_hash TEXT NULL,
  artifact_key TEXT NULL,
  integration_name TEXT NULL,
  status TEXT NULL,
  PRIMARY KEY (run_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_id_sequence ON run_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_run_events_type ON run_events(event_type);

CREATE TABLE IF NOT EXISTS run_snapshots (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
  snapshot JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  event_id TEXT NULL,
  approval JSONB NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learning_outcomes (
  outcome_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NULL,
  event_id TEXT NULL,
  decision_type TEXT NOT NULL,
  service TEXT NOT NULL,
  endpoint TEXT NULL,
  outcome TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  world_model_updates JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_learning_outcomes_service ON learning_outcomes(service, endpoint);
CREATE INDEX IF NOT EXISTS idx_learning_outcomes_decision ON learning_outcomes(decision_type, service);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  event_id TEXT NULL,
  artifact_key TEXT NULL,
  uri TEXT NULL,
  path TEXT NULL,
  content_hash TEXT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_items (
  memory_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NULL REFERENCES runs(run_id) ON DELETE SET NULL,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_items_kind ON memory_items(kind);
CREATE INDEX IF NOT EXISTS idx_memory_items_content ON memory_items USING gin(to_tsvector('english', content));

CREATE TABLE IF NOT EXISTS merkle_roots (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  event_id TEXT NULL,
  root_hash TEXT NOT NULL,
  proof JSONB NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_merkle_roots_run_id ON merkle_roots(run_id);
