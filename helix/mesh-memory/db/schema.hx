N::MemoryObservation {
  UNIQUE INDEX observation_id: String,
  INDEX service: String,
  INDEX run_id: String,
  kind: String,
  content: String,
  scope_json: String,
  payload_json: String,
  created_at: String
}

N::MemoryClaim {
  UNIQUE INDEX claim_id: String,
  INDEX state: String,
  INDEX tier: String,
  statement: String,
  confidence: F64,
  freshness: F64,
  entity_refs_json: String,
  supporting_observation_ids_json: String,
  payload_json: String,
  updated_at: String
}

N::MemoryEntity {
  UNIQUE INDEX entity_id: String,
  INDEX entity_type: String,
  payload_json: String
}

N::MemorySupersession {
  UNIQUE INDEX supersession_id: String,
  old_claim_id: String,
  new_claim_id: String,
  payload_json: String,
  created_at: String
}

N::MemoryRetrieval {
  UNIQUE INDEX retrieval_id: String,
  INDEX query: String,
  scope_json: String,
  channels_json: String,
  payload_json: String,
  created_at: String
}

N::MemoryPacket {
  UNIQUE INDEX packet_id: String,
  scope_json: String,
  claim_ids_json: String,
  observation_ids_json: String,
  payload_json: String,
  generated_at: String
}

E::MemoryRelationship UNIQUE {
  From: MemoryEntity,
  To: MemoryEntity,
  Properties: {
    relationship_id: String,
    relationship_type: String,
    scope_json: String,
    payload_json: String,
    created_at: String
  }
}
