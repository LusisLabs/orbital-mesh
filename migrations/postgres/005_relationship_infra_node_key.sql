-- Bridge between mesh's memory graph (RelationshipRecord) and its
-- typed K8s topology graph (InfraGraph).
--
-- ``RelationshipRecord.infra_node_key`` carries the canonical
-- InfraGraph node key (e.g. ``service:boutique:emailservice``,
-- ``node:_cluster:worker-01``) for the ``from_id`` side of the edge.
-- Memory retrieval uses this field for metapath traversal: from a
-- seed claim's infra_node_key, walk InfraGraph edges to find
-- topologically-adjacent resources, then surface claims about those
-- adjacent resources by looking them up via this index.
--
-- The field lives inside the JSONB ``payload`` column (no schema
-- change needed — payload was already JSONB). This migration adds
-- only the partial index that makes the lookup O(log N) instead of
-- O(N) scan. Partial-on-non-null because rows written before the
-- bridge landed have ``infra_node_key=None`` and would otherwise
-- bloat the index with nulls that are never queried.

CREATE INDEX IF NOT EXISTS idx_relationship_records_infra_node_key
  ON relationship_records ((payload->>'infra_node_key'))
  WHERE payload ? 'infra_node_key' AND payload->>'infra_node_key' IS NOT NULL;
