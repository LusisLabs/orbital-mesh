# Mesh High-Resolution Metrics Engine Plan

## Decision

Build a Mesh-native high-resolution metrics engine as the hot metric substrate
for Orbital Mesh. Postgres remains authoritative for runs, run events, memory,
approvals, audit records, Merkle roots, and artifact metadata. The new engine
owns high-cardinality metric samples, sub-second trend reads, rollups, anomaly
flags, and RCA/feedback evidence windows.

The engine is not a general TSDB replacement. It is designed to outperform
Netdata DBENGINE for Orbital Mesh's sub-second RCA, feedback, and
operator-control-plane workloads, where the critical path is: ingest recent
metrics, correlate them with a run/decision/action, answer bounded local
queries before a decision deadline, and preserve evidence provenance.

## Current Baseline

Existing metric history is `services.signal_history.SignalHistoryStore`:

- in-memory ring buffer per `target_id`;
- JSONL append under `<state_dir>/signal_history/<target_id>/events.jsonl`;
- second-resolution retention windows driven by Python `datetime`;
- generic JSON-path trend extraction;
- no WAL/fsync contract before flush;
- no series label index;
- no columnar blocks, extents, compression tiers, or vectorized scans;
- no native distribution sketches, counter reset tracking, anomaly scores, or
  provenance-aware rollups.

Existing OTLP support in `shared/mesh_runtime/otel.py` parses OTLP
`timeUnixNano`, but the current signal path in `services/ingest/otel_signal.py`
selects one representative metric and flattens histograms to a mean before
emitting `otel_metric_regression`. That is acceptable for coarse action
selection, but insufficient for sub-second RCA and feedback.

## Non-Goals

- Do not move control-plane state out of Postgres.
- Do not build a full remote-query TSDB, dashboard backend, or Prometheus
  replacement.
- Do not support arbitrary SQL over metric samples in v1.
- Do not make engine durability stronger than the configured mode. `ram` is
  explicitly volatile and `none` disables sample storage.
- Do not claim universal superiority over Netdata DBENGINE. The advantage claim
  is limited to Mesh RCA, feedback, and operator-control-plane query patterns.

## Operating Modes

### `dbengine`

Default for staging, pilot, and production. Samples write to a local durable
WAL before becoming visible as committed data. Hot data lives in memory-backed
pages and flushes to append-only datafiles as compressed extents.

### `ram`

Development and test mode. Same APIs, page formats, indexes, anomaly logic, and
query planner, but no durable WAL or datafiles. Retention is memory-size bound.
Use this for fast local tests and ephemeral demos.

### `none`

Metric sample storage disabled. OTLP/Prometheus signals continue through the
existing coarse signal path. RCA/feedback APIs return `metric_store_disabled`
evidence markers instead of silently falling back to stale data.

## Data Model

### Series

`SeriesKey`:

- `tenant_id`: defaults to `local`;
- `source`: `otlp_push`, `prometheus_pull`, `watcher`, `feedback_probe`,
  `synthetic_test`, or future source;
- `metric_name`;
- `metric_kind`: `gauge`, `sum`, `histogram`, `exponential_histogram`,
  `summary`, `counter`, `state`, or `unknown`;
- `unit`;
- canonical labels:
  - `service.name`;
  - `deployment.environment`;
  - `k8s.cluster.name`;
  - `k8s.namespace.name`;
  - `k8s.deployment.name`;
  - `host.name`;
  - `endpoint`;
  - `region`;
  - `customer_tier`;
  - `run_id` when a sample is emitted by Mesh feedback or controlled probes;
- arbitrary labels preserved in a string-interned label dictionary.

`series_id = blake3(canonical_series_json)` truncated to 128 bits. The first
implementation can use SHA-256 from stdlib truncated to 128 bits if adding
BLAKE3 is not accepted.

### Samples

`MetricSample`:

- `series_id`;
- `timestamp_ns`: signed 64-bit Unix epoch nanoseconds;
- `value`: float64 for scalar gauges/sums/counters;
- `raw_int`: optional int64 when the OTLP value is integral;
- `flags`: bitset:
  - `stale`;
  - `counter_reset`;
  - `anomaly_candidate`;
  - `rollup_derived`;
  - `provenance_gap`;
  - `source_clock_skew`;
- `anomaly_score`: float32, default 0;
- `provenance_ref`: compact id pointing to source receiver, run, feedback
  observation, watcher tick, or Prometheus query;
- `trace_ref`: optional OTLP trace/span link when provided.

### Distribution Samples

Histograms and summaries are not flattened in the new engine.

`DistributionSample`:

- same identity and timestamp fields as `MetricSample`;
- `count`, `sum`, `min`, `max` when present;
- bucket boundaries and counts for explicit histograms;
- scale, zero count, positive buckets, and negative buckets for exponential
  histograms;
- summary quantiles when present;
- `sketch`: DDSketch-compatible compact sketch for rollups and percentile
  queries.

The scalar value path may still materialize `mean`, `p95`, or `p99` virtual
series for compatibility, but the original distribution remains queryable.

### Provenance

`ProvenanceRecord` is stored in the metrics engine metadata area and linked to
Postgres run/event ids by value, not by foreign key:

- `provenance_id`;
- `source`;
- `received_at_ns`;
- `source_timestamp_ns_min`;
- `source_timestamp_ns_max`;
- `run_id`;
- `run_event_id`;
- `decision_id`;
- `execution_id`;
- `feedback_id`;
- `watcher_name`;
- `prometheus_query`;
- `otlp_resource_hash`;
- `content_hash`.

Postgres stores run/event/audit state. The metrics engine stores enough compact
provenance to answer evidence queries without joining hot sample scans against
Postgres.

## Storage Layout

Root: `<state_dir>/metrics_engine/`.

```
metrics_engine/
  CURRENT
  MANIFEST-000001
  wal/
    wal-000001.log
  index/
    series.manifest
    labels.sstable
    postings/
  data/
    tier0/
      extent-000000000001.meshx
    tier1/
    tier2/
  snapshots/
```

### WAL

Every committed ingest batch is appended to WAL before page mutation is
acknowledged in `dbengine` mode.

WAL record types:

- `series_define`;
- `sample_batch`;
- `distribution_batch`;
- `provenance_define`;
- `page_flush_intent`;
- `page_flush_commit`;
- `rollup_commit`;
- `retention_delete_marker`;
- `checkpoint`.

WAL rules:

- append CRC32C or SHA-256 checksum per record;
- fsync on batch boundary when `MESH_METRICS_WAL_SYNC=always`;
- group commit up to `MESH_METRICS_WAL_GROUP_COMMIT_MS`;
- recovery replays committed sample batches and ignores incomplete trailing
  records;
- page flushes are idempotent because `page_flush_commit` records include
  extent id, page id, min/max timestamp, and content hash.

### Pages

A page is the write and cache unit. Target uncompressed size: 64 KiB.

Page states:

- `hot`: open for appends;
- `dirty`: sealed in memory, WAL committed, not yet flushed to an extent;
- `clean`: flushed and cached;
- `cold`: evicted from page cache but addressable through extent metadata.

Two page encodings are supported:

1. `fixed_step_page`
   - selected when timestamps for a series are regular enough;
   - header stores `start_ns`, `step_ns`, count, null bitmap;
   - values are columnar and delta-of-delta encoded;
   - preserves Netdata's fixed-step compression advantage where it fits.

2. `delta_timestamp_page`
   - selected when samples are sub-second, jittery, bursty, or sparse;
   - header stores `base_ns`;
   - timestamp column stores varint delta from previous timestamp;
   - values remain columnar;
   - removes Netdata's fixed-step limitation for Mesh workloads.

Adaptive selection uses the first N samples in a page. If timestamp jitter stays
below `MESH_METRICS_FIXED_STEP_JITTER_NS`, the page stays fixed-step. Otherwise
it switches to delta timestamps before seal.

### Columnar Blocks

Each page is organized as columnar blocks:

- timestamp block;
- value block;
- integer-value block when present;
- flag block;
- anomaly-score block;
- provenance-id block;
- distribution block for histograms/sketches.

Columnar blocks allow vectorized min/max/predicate scans without decoding full
sample structs. Blocks carry min/max timestamp, min/max value, flag summary,
anomaly-score max, and provenance-id range for pruning.

### Extents

An extent is the append-only persisted unit. Target compressed size: 8-32 MiB.

Extent metadata:

- `extent_id`;
- `tier`;
- `created_at_ns`;
- `min_timestamp_ns`;
- `max_timestamp_ns`;
- `series_id_min/max` plus exact series bloom filter;
- label locality key;
- RCA locality key;
- page table offsets;
- compression codec;
- content hash.

Extents are append-only. Retention deletes whole extents when possible and uses
delete markers for partial expiry until compaction rewrites surviving pages into
a new extent.

### RCA-Locality Extents

Mesh differs from Netdata by optimizing for evidence windows around a run. Tier0
extents are clustered by:

1. `run_id` when samples are associated with a Mesh run or feedback probe;
2. `service.name + endpoint` for OTLP/Prometheus service metrics;
3. `cluster + namespace + deployment` for watcher/kubernetes metrics;
4. fallback `source + metric_name`.

This layout makes queries like "show all latency/error/restart metrics around
decision X" hit a small number of extents instead of scanning by metric name
alone.

### Compression

Compression defaults:

- page block integer and timestamp columns: delta, delta-of-delta, zigzag,
  varint;
- float values: Gorilla-style XOR encoding;
- flags and nulls: bitpacking;
- label dictionaries: front-coded sorted strings;
- extents: Zstd when dependency is accepted, else stdlib zlib in v1.

The plan allows Zstd as the production codec because metric extents are not on
the Python stdlib critical path after the engine boundary is isolated. If
dependency minimization wins, zlib is acceptable for the first milestone with a
codec interface.

## Tiers and Retention

Defaults target RCA and feedback, not long-term observability.

| Tier | Resolution | Default Time | Default Size | Purpose |
|------|------------|--------------|--------------|---------|
| tier0 | raw nanosecond samples | 6 hours | 8 GiB | active RCA, feedback, operator queries |
| tier1 | 1 second rollups | 7 days | 16 GiB | incident review and short-term learning |
| tier2 | 1 minute rollups | 45 days | 16 GiB | trend context and benchmark replay |
| tier3 | 15 minute rollups | 180 days | 8 GiB | coarse historical priors |

Retention policy is `min(time_limit, size_limit)` per tier. Protected evidence
windows referenced by Postgres run artifacts can pin raw tier0 pages for an
extra `MESH_METRICS_EVIDENCE_PIN_TTL_HOURS`, default 72 hours, subject to a hard
global cap.

Rollup rows preserve:

- count;
- min/max/mean;
- first/last;
- p50/p90/p95/p99 from sketches;
- sum;
- positive/negative delta for counters;
- reset count;
- anomaly max and anomaly count;
- provenance set summary;
- source gap count.

Provenance-aware rollups never merge samples from different sources without
recording the source set and gap markers.

## Caches

### Page Cache

Bounded by `MESH_METRICS_PAGE_CACHE_BYTES`, default 512 MiB in production and
64 MiB in local mode.

Lists:

- hot pages, keyed by open series shard;
- dirty pages, ordered by oldest WAL sequence;
- clean pages, LRU by extent/page id.

Eviction order:

1. clean pages;
2. sealed dirty pages after flush;
3. hot pages only by forcing seal and opening a replacement page.

### Extent Cache

Bounded by `MESH_METRICS_EXTENT_CACHE_BYTES`, default 256 MiB. Stores page
tables, extent metadata, bloom filters, and compressed block handles. This is
separate from page data so query planning can prune without loading samples.

### Label Index Cache

Caches hot postings lists for labels used by Mesh queries:

- service;
- endpoint;
- environment;
- cluster;
- namespace;
- deployment;
- run_id;
- decision_id;
- feedback_id;
- watcher_name.

## Label-Aware Series Index

The index maps:

- canonical label pair -> postings list of `series_id`;
- metric name -> postings list;
- source -> postings list;
- RCA locality key -> extent ids;
- run/decision/feedback ids -> extent ids and provenance ids.

Index updates are WAL-backed. In `dbengine` mode, a series is visible only after
its `series_define` WAL record is durable.

Prometheus-compatible label matchers are supported for equality, inequality,
regex, and negative regex. Query planning intersects postings before touching
extent metadata.

## Query Engine

### Execution Model

Queries compile to a small physical plan:

1. normalize label matchers;
2. intersect postings lists;
3. prune extents by time range, series bloom, label locality, RCA locality,
   and block min/max metadata;
4. scan columnar blocks in timestamp order;
5. evaluate predicates vectorized over decoded arrays;
6. aggregate, roll up, or return samples;
7. stop or degrade when the deadline requires it.

Vectorization in Python v1 can use `array`, `memoryview`, and batch loops behind
a narrow interface. If profiling proves Python is insufficient, move block
scan kernels to Rust without changing the public query API.

### Deadline-Aware Planning

Every query accepts `deadline_ms` and `accuracy`:

- `exact`: fail with `deadline_exceeded` rather than downsample;
- `bounded`: prefer raw tier, then rollup tier if deadline pressure is high;
- `best_effort`: return partial with `partial=true` and skipped extents listed.

Operator-control-plane defaults:

- RCA evidence query: 300 ms, `bounded`;
- feedback verification query: 500 ms, `exact` for the current run window;
- UI sparkline query: 100 ms, `best_effort`;
- anomaly search: 750 ms, `bounded`.

### Public Python API

New package: `services.metrics_engine`.

```python
class MetricsEngine:
    def ingest_otlp(self, payload: dict, provenance: ProvenanceInput) -> IngestResult: ...
    def ingest_prometheus_samples(self, samples: list[PromSample], provenance: ProvenanceInput) -> IngestResult: ...
    def ingest_watcher_sample(self, sample: MetricSampleInput, provenance: ProvenanceInput) -> IngestResult: ...
    def query_range(self, query: MetricRangeQuery) -> MetricQueryResult: ...
    def query_rollup(self, query: MetricRollupQuery) -> MetricRollupResult: ...
    def query_anomalies(self, query: MetricAnomalyQuery) -> MetricAnomalyResult: ...
    def query_rca_evidence(self, query: RcaMetricEvidenceQuery) -> RcaMetricEvidenceResult: ...
    def query_feedback_window(self, query: FeedbackMetricWindowQuery) -> FeedbackMetricWindowResult: ...
    def close(self) -> None: ...
```

Core query dataclasses:

- `MetricRangeQuery(metric, labels, start_ns, end_ns, step_ns=None,
  deadline_ms=300, accuracy="bounded")`;
- `MetricRollupQuery(metric, labels, start_ns, end_ns, functions, group_by,
  tier_hint=None)`;
- `MetricAnomalyQuery(labels, start_ns, end_ns, min_score, include_context)`;
- `RcaMetricEvidenceQuery(run_id, decision_id=None, service=None,
  endpoint=None, start_ns=None, end_ns=None, metrics=None, deadline_ms=300)`;
- `FeedbackMetricWindowQuery(decision_id, execution_id, feedback_id=None,
  before_ns, after_ns, metrics, exact=True)`.

### HTTP API

Add control-plane endpoints after the Python API is stable:

- `GET /api/metrics/series`;
- `POST /api/metrics/query-range`;
- `POST /api/metrics/query-rollup`;
- `POST /api/metrics/anomalies`;
- `POST /api/runs/{run_id}/metric-evidence`;
- `POST /api/feedback/{feedback_id}/metric-window`.

Run export includes metric evidence summaries and pinned extent refs, not raw
bulk samples by default.

## Anomaly Flags and Scores

Anomaly scoring runs at ingest and rollup time. V1 uses deterministic local
baselines:

- median absolute deviation for gauges;
- EWMA residual for latency/error-rate gauges;
- rate-of-change thresholds for counters;
- distribution drift against recent DDSketch quantiles;
- Kubernetes restart/status state transitions;
- source-clock skew and sample gap detection.

Scores are floats in `[0, 1]`. Flags are set when:

- score >= `MESH_METRICS_ANOMALY_FLAG_THRESHOLD`, default 0.80;
- counter reset detected;
- source gap exceeds expected cadence;
- distribution p95/p99 exceeds learned baseline by configured ratio.

The decision service consumes anomaly evidence as additional findings. It does
not execute actions solely because the metrics engine assigned a high score.

## Counter Reset Handling

Counter series maintain per-series state:

- last raw value;
- last timestamp;
- reset count;
- monotonicity violations;
- last provenance id.

Rate queries split segments at resets. Rollups store reset count and positive
delta separately from negative/reset delta. Feedback and RCA APIs expose reset
markers so a post-action "drop" is not misread as recovery.

## Integration Points

### OTLP Push

`POST /v1/metrics` continues to accept OTLP/HTTP JSON when
`MESH_OTEL_RECEIVER_ENABLED=1`.

New behavior in shadow phase:

1. parse OTLP payload;
2. write every supported metric data point to `MetricsEngine`;
3. continue building the existing coarse `otel_metric_regression` signal for
   the pipeline;
4. attach `metrics_engine_refs` to the normalized event once available.

The new engine keeps nanosecond timestamps from `timeUnixNano`. If absent, it
uses receiver time and sets `source_clock_skew` or `provenance_gap` flags where
appropriate.

### Prometheus Pull

Prometheus remains a source and compatibility bridge. Pull results are written
to the metrics engine with provenance containing the query string, URL hash,
window, and receiver timestamp. Existing feedback observers keep working while
the new `query_feedback_window` API is introduced.

Prometheus remote-write ingestion is not a v1 requirement. Add it only after
OTLP push, Prometheus pull, and Mesh watcher samples are stable.

### Watchers

Kubernetes watcher ticks emit structured status metrics into the engine:

- desired replicas;
- ready replicas;
- unavailable replicas;
- restart count;
- rollout status as state metric;
- pod-level restart deltas where labels are bounded.

Watcher metrics are keyed by watcher name, cluster, namespace, deployment, and
run id when the watcher creates a run.

### Decision

`DecisionService` replaces `SignalHistoryStore.trend(...)` calls with
`MetricsEngine.query_rca_evidence(...)` for supported signal types. The result
returns:

- compact trend summaries;
- anomaly flags;
- counter reset markers;
- relevant raw sample snippets;
- rollup summaries;
- provenance refs;
- deadline and partial-result status.

During migration, decision reads both stores in shadow mode and records
divergence in evidence metadata without changing the selected action.

### Feedback

`FeedbackService` uses `query_feedback_window(...)` for:

- pre-action baseline;
- post-action recovery window;
- side-effect metrics;
- counter reset disambiguation;
- source-gap detection.

Feedback records keep their current public shape, with added
`metrics_engine_evidence` under `metric_comparison` or `quality_measurements`.

### RCA Evidence

`InvestigationService` and `build_rca_report` receive a metrics evidence
adapter. RCA evidence packs include:

- local metric windows around trigger, decision, execution, and feedback;
- anomaly-ranked series;
- distribution percentile movement;
- counter reset notes;
- missing-data gaps;
- provenance links to run events and source payload hashes.

## Migration From `SignalHistoryStore`

Phase 0: design and fixtures.

- Add this document.
- Add format fixtures for scalar, counter, histogram, and watcher state samples.
- Keep `SignalHistoryStore` unchanged.

Phase 1: engine skeleton in `ram` mode.

- Add `services/metrics_engine` dataclasses and in-memory page/index model.
- Add tests for nanosecond ordering, label matching, adaptive page encoding,
  counter reset flags, and distribution sketch retention.
- No runtime behavior change by default.

Phase 2: shadow ingest.

- Add `MESH_METRICS_ENGINE_MODE=ram|dbengine|none`, default `none` for local
  compatibility until tests are stable.
- OTLP, Prometheus pull, watcher, and feedback probes write to the engine when
  mode is not `none`.
- Existing `SignalHistoryStore` remains the decision source.

Phase 3: durable dbengine mode.

- Add WAL, recovery, append-only extents, page flush, extent cache, and
  retention sweeper.
- Default staging/pilot configs to `dbengine`.
- Add crash-recovery tests that replay WAL and verify no acknowledged samples
  are lost.

Phase 4: decision and feedback read cutover.

- Add `MESH_METRICS_ENGINE_READ_MODE=off|shadow|primary`, default `shadow`.
- Compare `SignalHistoryStore` trend outputs with metrics-engine evidence.
- Move decision and feedback to primary after parity tests pass.

Phase 5: retire JSONL history for metric trends.

- Keep `SignalHistoryStore` only for non-metric envelope history or remove it if
  all callers have migrated.
- Provide a one-time importer that replays recent JSONL records into the engine
  as coarse provenance-marked samples.

## Configuration Flags

Add to `RuntimeConfig`:

- `metrics_engine_mode`: env `MESH_METRICS_ENGINE_MODE`, values
  `none|ram|dbengine`, default `none` until rollout, then `dbengine` for pilot;
- `metrics_engine_read_mode`: env `MESH_METRICS_ENGINE_READ_MODE`, values
  `off|shadow|primary`, default `off`, then `shadow`;
- `metrics_engine_directory`: env `MESH_METRICS_ENGINE_DIRECTORY`, default
  `<state_dir>/metrics_engine`;
- `metrics_wal_sync`: env `MESH_METRICS_WAL_SYNC`, values
  `always|group|checkpoint`, default `group`;
- `metrics_wal_group_commit_ms`: default 10;
- `metrics_page_cache_bytes`: default local 64 MiB, production 512 MiB;
- `metrics_extent_cache_bytes`: default local 64 MiB, production 256 MiB;
- `metrics_tier0_retention_hours`: default 6;
- `metrics_tier1_retention_days`: default 7;
- `metrics_tier2_retention_days`: default 45;
- `metrics_tier3_retention_days`: default 180;
- `metrics_max_disk_bytes`: default 48 GiB;
- `metrics_evidence_pin_ttl_hours`: default 72;
- `metrics_fixed_step_jitter_ns`: default 1_000_000;
- `metrics_query_default_deadline_ms`: default 300;
- `metrics_anomaly_flag_threshold`: default 0.80;
- `metrics_prometheus_shadow_ingest_enabled`: default false until explicit
  deployment wiring.

Readiness gates:

- pilot profile requires `dbengine` when high-resolution feedback is declared
  required;
- `dbengine` mode requires writable metrics directory and WAL recovery check;
- `primary` read mode is rejected unless the engine mode is not `none`.

## Tests

Unit tests:

- series key canonicalization and label hashing;
- nanosecond timestamp ordering and duplicate timestamp handling;
- fixed-step page selection under low jitter;
- delta-timestamp page selection under bursty samples;
- columnar block min/max pruning;
- WAL record checksum and incomplete-tail recovery;
- hot/dirty/clean page transitions;
- page flush idempotence;
- extent metadata and bloom/postings pruning;
- label matcher equality, inequality, regex, and negative regex;
- counter reset detection and rate segmentation;
- histogram and exponential histogram sketch rollup;
- anomaly score flags for gauges, counters, and distributions;
- provenance-aware rollup source-set preservation;
- retention time limit, size limit, and evidence pin behavior;
- `ram` mode parity for query results;
- `none` mode explicit disabled evidence markers.

Integration tests:

- OTLP push writes all metric data points to the engine while preserving the
  existing `otel_metric_regression` signal;
- Prometheus pull writes query results with query provenance;
- Kubernetes watcher writes bounded deployment metrics;
- decision shadow mode records metrics-engine evidence without changing action;
- feedback shadow mode compares old Prometheus observer results with
  `query_feedback_window`;
- restart recovery replays WAL and restores series index;
- run export includes metric evidence refs without bulk sample leakage.

Migration tests:

- import recent `SignalHistoryStore` JSONL into metrics engine;
- compare trend summaries for existing Reth, Kubernetes, and OTLP fixtures;
- verify missing paths produce explicit no-data evidence, not false zeros.

## Benchmarks

Add `benchmarks/metrics_engine/` with reproducible workloads:

- sub-second OTLP burst ingest: 100k, 1M, and 10M samples;
- high-cardinality label fanout: service, endpoint, pod, region, customer tier;
- RCA evidence query: all relevant series for one run in +/- 5 minutes;
- feedback exact query: pre/post action windows around one execution;
- anomaly search: top anomalous series in a 15 minute window;
- rollup query: p95 latency and error rate over 7 days;
- recovery benchmark: WAL replay after forced process stop;
- retention benchmark: delete/compact under tier size pressure.

Primary success metrics:

- acknowledged sample loss after crash: zero in `dbengine` mode;
- p95 RCA evidence query latency under 300 ms for target pilot cardinality;
- p95 feedback query latency under 500 ms exact for one run window;
- ingest p95 latency below watcher/receiver backpressure budget;
- bounded memory under configured page and extent cache caps;
- query partial/degraded markers are correct under forced deadlines.

Netdata comparison benchmarks should use the same workload shape where possible,
but the conclusion must be scoped: Orbital Mesh should win on run-local RCA and
feedback evidence reads with nanosecond and provenance requirements. Netdata may
remain better for its own agent-local monitoring and broad dashboard use cases.

## Documentation

Required docs when implementation starts:

- update `docs/architecture/api-and-runtime-map.md` with metrics-engine write
  and read paths;
- add operator config docs for `MESH_METRICS_*`;
- update `docs/postgres-persistence.md` to state that Postgres remains control
  plane state and does not store high-cardinality samples;
- add migration notes from `SignalHistoryStore`;
- add benchmark README with workload definitions and result interpretation;
- add run-export documentation for metric evidence refs and retention pins.

## Netdata Comparison

Preserved from Netdata DBENGINE:

- dbengine/ram/none operating modes;
- multi-tier retention;
- page and extent caches;
- hot, dirty, and clean page lifecycle;
- compressed extents;
- append-only datafiles;
- rollups;
- time and size retention limits;
- locality-aware storage.

Mesh-specific improvements:

- nanosecond timestamps rather than fixed-step-only storage;
- adaptive fixed-step and delta-timestamp pages;
- durable WAL before flush in `dbengine` mode;
- columnar page blocks for vectorized scans;
- label-aware series indexing;
- RCA-locality extents keyed by run, decision, feedback, service, endpoint,
  and deployment;
- anomaly flags and scores as first-class sample metadata;
- counter reset handling in rates and feedback evidence;
- distribution sketches and native histogram retention;
- provenance-aware rollups that preserve source and run context;
- deadline-aware query planning for operator-control-plane latency budgets;
- first-class RCA and feedback query APIs.

Honest superiority claim:

Orbital Mesh can outperform Netdata DBENGINE for sub-second RCA, feedback, and
operator-control-plane workloads because it stores and plans around Mesh run
provenance, labels, decision deadlines, nanosecond samples, and evidence
windows. It should not claim to be a better universal TSDB, monitoring agent,
or dashboard backend.

## Implementation Order

1. Add `services/metrics_engine/contracts.py` with public dataclasses and
   disabled/ram implementations.
2. Add canonical series and label index logic.
3. Add in-memory page model with fixed-step and delta-timestamp encodings.
4. Add query planner over in-memory pages and label postings.
5. Wire shadow ingest for OTLP, Prometheus pull, watcher, and feedback probes.
6. Add WAL and recovery.
7. Add extent writer/reader, compression interface, page cache, extent cache.
8. Add tiered rollups, retention sweeper, and evidence pins.
9. Add RCA and feedback query adapters.
10. Add shadow read comparison against `SignalHistoryStore`.
11. Cut decision/feedback reads to primary behind config.
12. Retire or narrow `SignalHistoryStore`.

## Completion Criteria

- All explicit requirements in this document have source files, tests, and docs
  mapped in the implementation PR.
- `dbengine` mode survives forced process death without losing acknowledged
  samples.
- `ram` and `dbengine` return equivalent query results for the same data.
- `none` mode fails visibly with disabled evidence markers.
- OTLP nanosecond timestamps are preserved end to end.
- Histograms remain distributions, not only flattened means.
- RCA evidence and feedback window APIs are used by decision and feedback in
  primary mode.
- Postgres remains authoritative for control-plane state and stores only metric
  metadata refs, not bulk samples.
- Benchmarks demonstrate the scoped advantage claim against the Mesh workload.
