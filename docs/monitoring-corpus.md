# Monitoring Corpus Strategy

Mesh Intelligence should not compete as another dashboard. The edge is an
internal corpus for production and development nodes: normalized telemetry,
diagnostic evidence, decisions, actions, and verified outcomes.

Public datasets seed parsers and evaluation. They do not replace private node
telemetry.

## Public Dataset Map

Use these sources as bootstrap and regression material:

| Source | Domain | Useful planes | Mesh use | Limit |
| --- | --- | --- | --- | --- |
| [Loghub](https://github.com/logpai/loghub) | Web2/infrastructure | Logs | Log parsing, anomaly fixtures | Not crypto-node specific. |
| [AIOps Challenge 2020](https://github.com/NetManAIOps/AIOps-Challenge-2020-Data) | Web2/infrastructure | Metrics, traces, failure events | Multimodal RCA fixtures | License and domain differ from node operators. |
| [Train Ticket anomaly datasets](https://zenodo.org/records/6979726) | Web2 | Logs, Prometheus KPI data, Jaeger traces | Microservice anomaly/RCA testing | Benchmark traffic. |
| [Eadro datasets](https://zenodo.org/records/7615394) | Web2 | Logs, metrics, traces | Multi-source troubleshooting tests | Benchmark-scoped. |
| [LO2v2](https://zenodo.org/records/18937117) | Web2 | Logs, metrics, failure events | Large-scale microservice anomaly and RCA tests | Full dataset is hundreds of GB and not trace-complete. |
| [OpenTelemetry Astronomy Shop demo](https://github.com/open-telemetry/opentelemetry-demo) | Web2/infrastructure | Logs, metrics, traces, events | OTLP parser, collector, and retrieval regression harness | Generates synthetic demo telemetry. |
| [OpenTelemetry telemetrygen](https://github.com/open-telemetry/opentelemetry-collector-contrib) | Web2/infrastructure | Logs, metrics, traces, events | Synthetic OTLP signal generation and collector pipeline tests | Signal generator, not labeled incident corpus. |
| [Google Borg cluster traces](https://github.com/google/cluster-data) | Infrastructure | Workload events, resource traces | Fleet-scale scheduling and resource baselines | Not app logs or node semantics. |
| [Alibaba Cluster Trace Program](https://github.com/alibaba/clusterdata) | Infrastructure/Web2 | Cluster metrics, events, microservice traces | Capacity and noisy-neighbor tests | Cluster-management schema. |
| [DeathStarBench](https://github.com/delimitrou/DeathStarBench) | Web2 | Generated logs, metrics, traces | Fault injection harness | A harness, not a standing production corpus. |
| [Ethereum ETL](https://ethereum-etl.readthedocs.io/) | Crypto | On-chain events, logs, traces, graphs | Chain truth, reorg and indexer baselines | Not execution/consensus runtime logs. |
| [Elliptic Bitcoin dataset](https://www.kaggle.com/datasets/ellipticco/elliptic-data-set/data) | Crypto | Transaction graph | Graph anomaly evaluation | Fraud graph, not node health. |
| [EthStaker monitoring at scale](https://docs.ethstaker.org/scaled-node-operators/monitoring-at-scale/) and [Gnosis node monitoring](https://docs.gnosischain.com/node/management/monitoring-node/) | Crypto | Metrics vocabulary, runbooks | Validator and client signal vocabulary | Guidance, not anomaly-labeled data. |

Crypto has useful public chain datasets and monitoring runbooks, but public
runtime logs for Reth, Geth, Lighthouse, Prysm, validator clients, rollup
nodes, RPC gateways, and indexers are sparse. That gap is the product opening.

## Internal Corpus Requirements

Collect these target classes in production, testnet, and development:

| Target class | Required signals | Why |
| --- | --- | --- |
| Ethereum execution clients: Reth, Geth, Nethermind, Besu, Erigon | Peer count, head block, sync state, block lag, RPC error rate, disk pressure, client version | Detect peer starvation, stalled sync, RPC degradation, disk pressure, bad releases. |
| Consensus and validator clients: Lighthouse, Prysm, Teku, Nimbus, Lodestar | Slot lag, missed attestations, missed proposals, finalized epoch, balance delta, beacon peers | Validator duty misses and consensus lag are revenue and safety failures. |
| Rollup and appchain nodes | Sequencer liveness, batch submission lag, derivation lag, safe-head lag, bridge event lag | Cross-layer faults require local/L1 correlation. |
| RPC gateways and indexers | Request rate, p95 latency, error rate, upstream health, cache hit rate, indexing lag | User-facing Web2 symptoms often originate in crypto-node state. |
| Kubernetes services | Restarts, deployment generation, p95 latency, error rate, CPU/memory pressure | Common substrate for APIs, operators, indexers, and control plane. |
| Stateful dependencies | Disk use, write latency, replication lag, connection saturation, backup state | Databases, queues, and object stores create second-order incidents. |
| Devnets and Kurtosis enclaves | Service state, fault overlay, expected failure mode, recovery time, post-action probe result | Development generates the labeled crypto faults public datasets lack. |

The code catalog for this map is
[`shared/mesh_runtime/monitoring_corpus.py`](../shared/mesh_runtime/monitoring_corpus.py).
The offline public-source fixture is
[`fixtures/monitoring_corpus/public_sources.json`](../fixtures/monitoring_corpus/public_sources.json).

## Mesh Intelligence Implementation

The operating loop:

1. Ingest public datasets only into offline fixtures. Use them to train parsers,
   check anomaly detectors, and prevent regressions.
2. Instrument internal prod/dev targets with OpenTelemetry, Prometheus,
   client JSON-RPC probes, Kubernetes watches, and run-event capture.
3. Normalize every incident into the same evidence envelope: inbound signal,
   current probe pack, topology context, decision, evaluation, action, feedback.
4. Store outcomes as training facts: false positive, human hold, executed,
   successful, failed, worsened, recovered without action.
5. Promote only verified patterns into policies, trigger rules, and hypothesis
   templates.

Public data answers: "can Mesh parse and reason over common telemetry?"

Internal data answers: "does Mesh know how this fleet fails, how it recovers,
and which action is actually safe?"

## Memory Partitioning

Corpus rows are partitioned across memory tiers in one run transaction:

| Memory tier | Corpus material | Write policy |
| --- | --- | --- |
| `working` | Current signal, evidence pack, active run events, and agent-task packet | Run-scoped and replaceable. It can be rebuilt from artifacts. |
| `episodic` | Immutable `mesh.incident_corpus.v1` row, source refs, run id, artifact list, and outcome | Append-only. This is the canonical incident memory for replay and audit. |
| `semantic` | Verified claims extracted from repeated outcomes, supported hypotheses, and contradicted assumptions | Promotion requires source references and confidence factors; contradictions suppress rather than erase prior claims. |
| `procedural` | Reusable rule, runbook, or policy candidates derived from successful repeated rows | Promotion requires `promotion_candidate=true`, successful feedback, passing evaluation, and action success. |

The partition is concurrent from the operator's perspective: the same completed
cycle refreshes the per-cycle row, session JSONL/report, active memory
projection, and downstream memory-crystallization artifacts. Public benchmark
fixtures stay offline bootstrap material and do not enter procedural memory
without internal corroboration.

## First Slice

Use the existing Reth/Kurtosis path as the controlled corpus generator:

1. Run `scripts/run_reth_kurtosis_full_loop.py` continuously against a local
   enclave.
2. Archive healthy, peer-starved, disk-pressure, RPC-degraded, and restart
   recovery cycles under `.mesh-runtime-state/reth-kurtosis-loop/`.
3. Convert each cycle into a labeled corpus row:
   - signal payload
   - scenario analysis
   - decision
   - evaluation result
   - execution record
   - post-action observations
   - final feedback outcome
4. Mirror the same shape for live production nodes, without autonomous action
   unless policy gates already permit it.

That gives Mesh a private node-operations dataset with causal evidence and
action outcomes. Loghub-like data becomes bootstrap; Mesh-owned telemetry
becomes the moat.

## Implemented Artifacts

The first slice writes normalized training rows from the Reth/Kurtosis archive:

- Per cycle: `corpus_row.json`
- Per session: `corpus.jsonl`
- Per session: `corpus_report.json`
- Local query database: `.mesh-runtime-state/corpus/incident_corpus.sqlite`

Each row uses schema `mesh.incident_corpus.v1` and contains:

- `source`: internal collector, session, profile, cycle, run id
- `evidence_envelope`: inbound signal, current probe pack, topology context,
  scenario analysis, decision, evaluation, action, feedback, post-action
  observations
- `training_fact`: normalized outcome, decision/evaluation/action status,
  confidence, risk, promotion-candidate status
- `audit`: signal collection, evidence graph, Merkle artifact, event count,
  artifact file list

The outcome taxonomy is intentionally finite:

- `false_positive`
- `human_hold`
- `executed`
- `successful`
- `failed`
- `worsened`
- `recovered_without_action`
- `skipped`
- `unknown`

The live loop calls the exporter after each cycle. Existing archives can be
rebuilt without running Kurtosis:

```bash
python3 scripts/export_monitoring_corpus.py
```

Export a single session:

```bash
python3 scripts/export_monitoring_corpus.py --session session_20260426T193540Z
```

The exporter also imports one non-promotable bootstrap row per public source
from the catalog into the SQLite database. These rows make Loghub, AIOps
Challenge 2020, Google Borg traces, Alibaba clusterdata, DeathStarBench,
Ethereum ETL, EthStaker/Gnosis monitoring references, and adjacent benchmark
sources, OpenTelemetry demo/tooling data, and adjacent benchmark sources
queryable by the same corpus APIs used for internal incidents. They are
marked with `source.kind` values such as `public_dataset` or `public_tooling`,
`training_fact.outcome=skipped`, and
`training_fact.promotion_candidate=false`.

Rebuild only internal rows while still refreshing the public fixture:

```bash
python3 scripts/export_monitoring_corpus.py --skip-public-bootstrap
```

Download raw public bootstrap artifacts into ignored runtime state:

```bash
python3 scripts/download_public_monitoring_corpus.py
```

The downloader writes source directories under
`.mesh-runtime-state/monitoring-corpus/raw/` and a manifest at
`.mesh-runtime-state/monitoring-corpus/raw_manifest.json`. GitHub and Zenodo
sources are fetched directly when anonymously available. Kaggle-gated datasets
and cloud-query datasets are manifested with their upstream URL and license
notes instead of bypassing authentication or usage terms. Very large Zenodo
datasets such as LO2v2 are metadata-only by default so a routine corpus refresh
does not silently pull hundreds of GB. Use `--source <slug>` to download one
source and `--max-bytes <n>` to enforce a per-file ceiling.
When `scripts/export_monitoring_corpus.py` sees that raw manifest, public
bootstrap rows include `source.raw_artifact_paths` and audit refs back to the
downloaded files.

Clean raw artifacts into runtime-safe indexes:

```bash
python3 scripts/clean_public_monitoring_corpus.py
python3 scripts/export_monitoring_corpus.py
```

The cleaner writes `.mesh-runtime-state/monitoring-corpus/clean/public_sources.clean.jsonl`
and `.mesh-runtime-state/monitoring-corpus/clean/clean_manifest.json`. It records
artifact existence, byte counts, SHA-256 values from acquisition, zip entry
counts, bounded zip samples, Zenodo metadata, telemetry planes, and allowed
agent uses. The exporter attaches these clean refs to the public corpus rows so
the running system can retrieve cleaned source cards without opening large raw
archives during an incident loop.

Promotion candidates are deliberately strict. A row is eligible only when the
feedback outcome is successful, evaluation passed with `execute`, the action
succeeded, and confidence is at least `0.75` when present. Human holds and
policy-held escalations stay as training data; they do not become automatic
policy changes.

## Corpus Database

The local corpus database is SQLite-backed for replay and CI. It is written by
both the live Reth/Kurtosis harness and the offline exporter.

Tables:

- `corpus_rows`: canonical row metadata plus full JSON payload.
- `corpus_labels`: normalized label key/value pairs such as fault profile,
  outcome, decision type, and derived error signatures.
- `corpus_artifacts`: artifact file refs for replay and audit.
- `corpus_rows_fts`: full-text index over service, target class, profile,
  outcome, decision, and signatures.
- `memory_projection_records`: reserved ledger for row-to-memory projection
  refs.

The production Postgres shape is in
[`migrations/postgres/004_incident_corpus.sql`](../migrations/postgres/004_incident_corpus.sql).

The importer is idempotent by `row_id`. Re-exporting a session refreshes rows
instead of duplicating them. Database summaries expose counts by outcome,
environment, source kind, service, target class, collector, coverage label, and
promotion pattern.

Public bootstrap rows are idempotent by `public_monitoring_source:<source-slug>`
and are present for parser, search, and evaluation coverage. They do not satisfy
Breakthrough gates, because Breakthrough filters to `internal_corpus` rows from
production, development, or testnet.

## Breakthrough Threshold

Breakthrough is now a measured corpus state, not a narrative claim. The runtime
utility
[`breakthrough_threshold_report`](../shared/mesh_runtime/breakthrough.py)
scores normalized corpus rows against five gates:

| Gate | Minimum |
| --- | --- |
| Incident volume | `100` rows, with `1000` as the scale target. |
| Operational reduction | At least one row with measured false-positive, diagnosis-time, or unsafe-action reduction. |
| Repeated promotion | At least three promotion candidates and at least one repeated target/profile/action pattern. |
| Cross-client coverage | Evidence for Reth, Geth, Lighthouse, validators, RPC gateways, indexers, and Kubernetes services. Prefer explicit `labels.coverage`; legacy text scanning remains a fallback. |
| Retrieval lift | At least one live/internal row where retrieval or memory context improved the decision. |

Only `internal_corpus` rows from `production`, `development`, or `testnet`
environments count toward these gates. Public/bootstrap rows remain useful for
offline evaluation but cannot satisfy Breakthrough.

The SQLite store exposes this through
`IncidentCorpusDatabase.breakthrough_report()` and includes the same payload
under `IncidentCorpusDatabase.summary()["breakthrough"]`.

Use `python3 scripts/verify_corpus_breakthrough.py --json` to verify the local
SQLite store as a release gate. The utility reads
`.mesh-runtime-state/corpus/incident_corpus.sqlite` by default, emits
`mesh.corpus_breakthrough_verification.v1`, and exits non-zero until every
measured Breakthrough threshold passes.

Corpus rows preserve run measurements under
`training_fact.quality_measurements`. Live runs should record concrete fields
such as `false_positive_reduction_pct`,
`time_to_diagnosis_reduction_seconds`, `unsafe_actions_prevented`, and
`retrieval_improved_decision=true` when the evidence supports them. The exporter
also records `training_fact.quality_measurements.evidence_refs` naming which
run artifact supplied each measured reduction or retrieval-impact field.

Explicit coverage labels use these normalized names:

```json
{
  "labels": {
    "coverage": [
      "reth",
      "geth",
      "lighthouse",
      "validator",
      "rpc_gateway",
      "indexer",
      "kubernetes_service"
    ]
  }
}
```

Promotion-pattern summaries are keyed as
`target_class:fault_profile:decision_type`. The repeated-promotion gate passes
only when at least three promotion candidates exist and at least one such key
appears twice.

## Memory E2E

Corpus rows project into canonical memory as follows:

1. Every row becomes an episodic `ObservationRecord` with source refs back to
   `row_id`, session, and cycle.
2. Public dataset/tooling rows create semantic advisory claims for parser,
   retrieval, benchmark, and OTLP-pipeline grounding.
3. `human_hold` and `successful` internal rows create semantic claims.
4. Promotion-candidate internal rows create procedural claims.
4. Claims are linked to observations with `supports` relationships.
5. Retrieval uses the existing lexical and graph channels.
6. Retrieved packets can be projected into active memory with
   `ActiveMemoryStore.project_packet`.

This preserves the separation between audit memory and reusable operational
knowledge. Public data is visible to ReasoningBank as semantic advisory
context, but it cannot become procedural memory, action policy, or Breakthrough
evidence without internal corpus corroboration.
