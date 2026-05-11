QUERY mesh_upsert_observation(
  observation_id: String,
  service: String,
  run_id: String,
  kind: String,
  content: String,
  scope_json: String,
  payload_json: String,
  created_at: String
) =>
  existing <- N<MemoryObservation>::WHERE(_::{observation_id}::EQ(observation_id))
  observation <- existing::UpsertN({
    observation_id: observation_id,
    service: service,
    run_id: run_id,
    kind: kind,
    content: content,
    scope_json: scope_json,
    payload_json: payload_json,
    created_at: created_at
  })
  entity_existing <- N<MemoryEntity>::WHERE(_::{entity_id}::EQ(observation_id))
  entity <- entity_existing::UpsertN({
    entity_id: observation_id,
    entity_type: "observation",
    payload_json: payload_json
  })
  RETURN observation, entity

QUERY mesh_upsert_claim(
  claim_id: String,
  state: String,
  tier: String,
  statement: String,
  confidence: F64,
  freshness: F64,
  entity_refs_json: String,
  supporting_observation_ids_json: String,
  payload_json: String,
  updated_at: String
) =>
  existing <- N<MemoryClaim>::WHERE(_::{claim_id}::EQ(claim_id))
  claim <- existing::UpsertN({
    claim_id: claim_id,
    state: state,
    tier: tier,
    statement: statement,
    confidence: confidence,
    freshness: freshness,
    entity_refs_json: entity_refs_json,
    supporting_observation_ids_json: supporting_observation_ids_json,
    payload_json: payload_json,
    updated_at: updated_at
  })
  entity_existing <- N<MemoryEntity>::WHERE(_::{entity_id}::EQ(claim_id))
  entity <- entity_existing::UpsertN({
    entity_id: claim_id,
    entity_type: "claim",
    payload_json: payload_json
  })
  RETURN claim, entity

QUERY mesh_upsert_relationship(
  relationship_id: String,
  from_id: String,
  to_id: String,
  relationship_type: String,
  scope_json: String,
  payload_json: String,
  created_at: String
) =>
  from_existing <- N<MemoryEntity>::WHERE(_::{entity_id}::EQ(from_id))
  from_node <- from_existing::UpsertN({
    entity_id: from_id,
    entity_type: "entity",
    payload_json: "{}"
  })
  to_existing <- N<MemoryEntity>::WHERE(_::{entity_id}::EQ(to_id))
  to_node <- to_existing::UpsertN({
    entity_id: to_id,
    entity_type: "entity",
    payload_json: "{}"
  })
  existing <- E<MemoryRelationship>
  relationship <- existing::UpsertE({
    relationship_id: relationship_id,
    relationship_type: relationship_type,
    scope_json: scope_json,
    payload_json: payload_json,
    created_at: created_at
  })::From(from_node)::To(to_node)
  RETURN relationship

QUERY mesh_upsert_supersession(
  supersession_id: String,
  old_claim_id: String,
  new_claim_id: String,
  payload_json: String,
  created_at: String
) =>
  existing <- N<MemorySupersession>::WHERE(_::{supersession_id}::EQ(supersession_id))
  supersession <- existing::UpsertN({
    supersession_id: supersession_id,
    old_claim_id: old_claim_id,
    new_claim_id: new_claim_id,
    payload_json: payload_json,
    created_at: created_at
  })
  old_existing <- N<MemoryEntity>::WHERE(_::{entity_id}::EQ(old_claim_id))
  old_node <- old_existing::UpsertN({
    entity_id: old_claim_id,
    entity_type: "claim",
    payload_json: "{}"
  })
  new_existing <- N<MemoryEntity>::WHERE(_::{entity_id}::EQ(new_claim_id))
  new_node <- new_existing::UpsertN({
    entity_id: new_claim_id,
    entity_type: "claim",
    payload_json: "{}"
  })
  existing_relationship <- E<MemoryRelationship>
  relationship <- existing_relationship::UpsertE({
    relationship_id: supersession_id,
    relationship_type: "supersedes",
    scope_json: "{}",
    payload_json: payload_json,
    created_at: created_at
  })::From(new_node)::To(old_node)
  RETURN supersession, relationship

QUERY mesh_record_retrieval(
  retrieval_id: String,
  query: String,
  scope_json: String,
  channels_json: String,
  payload_json: String,
  created_at: String
) =>
  existing <- N<MemoryRetrieval>::WHERE(_::{retrieval_id}::EQ(retrieval_id))
  retrieval <- existing::UpsertN({
    retrieval_id: retrieval_id,
    query: query,
    scope_json: scope_json,
    channels_json: channels_json,
    payload_json: payload_json,
    created_at: created_at
  })
  RETURN retrieval

QUERY mesh_upsert_memory_packet(
  packet_id: String,
  scope_json: String,
  claim_ids_json: String,
  observation_ids_json: String,
  payload_json: String,
  generated_at: String
) =>
  existing <- N<MemoryPacket>::WHERE(_::{packet_id}::EQ(packet_id))
  packet <- existing::UpsertN({
    packet_id: packet_id,
    scope_json: scope_json,
    claim_ids_json: claim_ids_json,
    observation_ids_json: observation_ids_json,
    payload_json: payload_json,
    generated_at: generated_at
  })
  RETURN packet
