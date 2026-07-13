CREATE TABLE IF NOT EXISTS repo_patch_authority_records (
  authority_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  nonce TEXT NOT NULL UNIQUE,
  action_binding_digest TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('issued', 'leased', 'dispatched', 'terminal')),
  version BIGINT NOT NULL CHECK (version > 0),
  event_sequence BIGINT NOT NULL CHECK (event_sequence > 0),
  latest_event_digest TEXT NOT NULL,
  record JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_repo_patch_authority_records_state
  ON repo_patch_authority_records(state, updated_at);

CREATE TABLE IF NOT EXISTS repo_patch_authority_events (
  authority_id TEXT NOT NULL REFERENCES repo_patch_authority_records(authority_id),
  sequence BIGINT NOT NULL CHECK (sequence > 0),
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  state_version BIGINT NOT NULL CHECK (state_version > 0),
  previous_event_digest TEXT NOT NULL,
  event_digest TEXT NOT NULL UNIQUE,
  recorded_at TIMESTAMPTZ NOT NULL,
  receipt JSONB NOT NULL,
  PRIMARY KEY (authority_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_repo_patch_authority_events_recorded_at
  ON repo_patch_authority_events(authority_id, recorded_at);

CREATE OR REPLACE FUNCTION reject_repo_patch_authority_event_mutation()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'repo_patch_authority_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS repo_patch_authority_events_append_only
  ON repo_patch_authority_events;

CREATE TRIGGER repo_patch_authority_events_append_only
BEFORE UPDATE OR DELETE ON repo_patch_authority_events
FOR EACH ROW EXECUTE FUNCTION reject_repo_patch_authority_event_mutation();
