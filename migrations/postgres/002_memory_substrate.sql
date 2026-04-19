CREATE TABLE IF NOT EXISTS observation_records (
  observation_id TEXT PRIMARY KEY,
  service TEXT NULL,
  run_id TEXT NULL REFERENCES runs(run_id) ON DELETE SET NULL,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_observation_records_service ON observation_records(service, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_observation_records_content ON observation_records USING gin(to_tsvector('english', content));

CREATE TABLE IF NOT EXISTS claim_records (
  claim_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  tier TEXT NOT NULL,
  statement TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL,
  payload JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claim_records_state_tier ON claim_records(state, tier, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_claim_records_statement ON claim_records USING gin(to_tsvector('english', statement));

CREATE TABLE IF NOT EXISTS relationship_records (
  relationship_id TEXT PRIMARY KEY,
  from_id TEXT NOT NULL,
  to_id TEXT NOT NULL,
  relationship_type TEXT NOT NULL,
  payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_relationship_records_from_to ON relationship_records(from_id, to_id);
CREATE INDEX IF NOT EXISTS idx_relationship_records_type ON relationship_records(relationship_type);

CREATE TABLE IF NOT EXISTS supersession_records (
  supersession_id TEXT PRIMARY KEY,
  old_claim_id TEXT NOT NULL,
  new_claim_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supersession_records_old_claim ON supersession_records(old_claim_id, created_at DESC);

CREATE TABLE IF NOT EXISTS retrieval_records (
  retrieval_id TEXT PRIMARY KEY,
  query TEXT NOT NULL,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  channels TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_records_created_at ON retrieval_records(created_at DESC);

CREATE TABLE IF NOT EXISTS memory_packets (
  packet_id TEXT PRIMARY KEY,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload JSONB NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_packets_generated_at ON memory_packets(generated_at DESC);
