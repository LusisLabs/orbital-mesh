CREATE TABLE IF NOT EXISTS helix_memory_projection_outbox (
  event_id TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  record JSONB NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  applied_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_helix_memory_projection_outbox_status
  ON helix_memory_projection_outbox(status, created_at ASC);
