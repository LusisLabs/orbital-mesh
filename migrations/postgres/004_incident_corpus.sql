CREATE TABLE IF NOT EXISTS incident_corpus_rows (
  row_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  collector TEXT NOT NULL,
  session_id TEXT NOT NULL,
  cycle_dir TEXT NOT NULL,
  profile TEXT NULL,
  cycle INTEGER NULL,
  run_id TEXT NULL REFERENCES runs(run_id) ON DELETE SET NULL,
  domain TEXT NOT NULL,
  environment TEXT NOT NULL,
  service TEXT NULL,
  target_class TEXT NULL,
  outcome TEXT NOT NULL,
  decision_type TEXT NULL,
  evaluation_recommendation TEXT NULL,
  execution_status TEXT NULL,
  feedback_outcome TEXT NULL,
  confidence DOUBLE PRECISION NULL,
  risk_level TEXT NULL,
  promotion_candidate BOOLEAN NOT NULL DEFAULT FALSE,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incident_corpus_service_outcome
  ON incident_corpus_rows(service, outcome, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incident_corpus_target_profile
  ON incident_corpus_rows(target_class, profile, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incident_corpus_promotion
  ON incident_corpus_rows(promotion_candidate, target_class, profile);
CREATE INDEX IF NOT EXISTS idx_incident_corpus_payload
  ON incident_corpus_rows USING gin(payload);
CREATE INDEX IF NOT EXISTS idx_incident_corpus_text
  ON incident_corpus_rows USING gin(
    to_tsvector(
      'english',
      coalesce(service, '') || ' ' ||
      coalesce(target_class, '') || ' ' ||
      coalesce(profile, '') || ' ' ||
      coalesce(outcome, '') || ' ' ||
      coalesce(decision_type, '')
    )
  );

CREATE TABLE IF NOT EXISTS incident_corpus_labels (
  row_id TEXT NOT NULL REFERENCES incident_corpus_rows(row_id) ON DELETE CASCADE,
  label_key TEXT NOT NULL,
  label_value TEXT NOT NULL,
  PRIMARY KEY (row_id, label_key, label_value)
);

CREATE INDEX IF NOT EXISTS idx_incident_corpus_labels_lookup
  ON incident_corpus_labels(label_key, label_value);

CREATE TABLE IF NOT EXISTS incident_corpus_artifacts (
  row_id TEXT NOT NULL REFERENCES incident_corpus_rows(row_id) ON DELETE CASCADE,
  artifact_name TEXT NOT NULL,
  PRIMARY KEY (row_id, artifact_name)
);

CREATE TABLE IF NOT EXISTS incident_corpus_memory_projection_records (
  row_id TEXT NOT NULL REFERENCES incident_corpus_rows(row_id) ON DELETE CASCADE,
  observation_id TEXT NOT NULL REFERENCES observation_records(observation_id) ON DELETE CASCADE,
  claim_id TEXT NULL REFERENCES claim_records(claim_id) ON DELETE SET NULL,
  projected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (row_id, observation_id)
);
