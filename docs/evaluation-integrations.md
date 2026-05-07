# Native Evaluation Integrations

Mesh keeps native evaluation authoritative. Third-party evaluation frameworks are
modeled as advisory lanes inside the native evaluator so their outputs can be
exported, compared, or mirrored without bypassing Mesh policy, trajectory,
verifier, evidence, or remediation-safety gates.

## Authority Boundary

`EvaluationService.evaluate()` writes `stage_results.evaluation_stack` with:

- `authority: mesh_native`
- `external_authority: disabled`
- `native_gates`: schema, policy, contract, trajectory, verifier, evidence, and remediation-safety gates
- `integrations`: advisory framework metadata and the Mesh artifacts each lane maps to
- `integrations[].account_connection`: redacted account-binding state for existing vendor accounts

The native gates determine `passed`, `final_recommendation`, and
`blocking_reasons`. Advisory integrations never approve execution by
themselves.

## Included Lanes

| Lane | Native role | Mesh artifacts |
|------|-------------|----------------|
| Promptfoo | Contract assertion lane | `contract_checks`, `trajectory_quality`, `task_trace.mesh_eval.promptfoo_role` |
| LangSmith | Trace and experiment projection lane | `task_trace`, `run_events`, `sre_judgment` |
| DeepEval / Confident AI | Code-defined metric lane | `contract_checks`, `trajectory_quality`, `behavioral_scores` |
| RAGAS | Retrieval quality lane | `task_trace.context.evidence_pack`, `task_trace.context.reasoning_bank_packet`, `evidence_sufficiency` |
| TruLens | Feedback-function lane | `evidence_sufficiency`, `verifier`, `task_trace.context` |
| Braintrust | Governance export lane | `evaluation_id`, `decision_id`, `stage_results`, `blocker_analysis` |
| Opik | Open trace export lane | `task_trace`, `phoenix_spans`, `trajectory_quality` |
| Weave | Dashboard export lane | `trajectory_quality`, `behavioral_scores`, `verifier` |
| Maxim AI | Simulation and prompt-workflow lane | `task_trace.context.scenario_analysis`, `trajectory_quality`, `verifier` |
| ZenML | Pipeline lineage lane | `task_trace`, `stage_results`, `mesh_eval` |
| Arize Phoenix | Span and RAG-debug lane | `phoenix_spans`, `task_trace.context.evidence_pack`, `verifier` |

## Configuration

All lanes are enabled in the native evaluator by default. To narrow the emitted
stack metadata, set:

```bash
MESH_EVAL_INTEGRATION_LANES=promptfoo,ragas,arize_phoenix
```

Use `all`, `*`, or an unset value to emit every lane.
Lane aliases are normalized for common names: `confident-ai` maps to
`deepeval`, `maxim` maps to `maxim_ai`, and `phoenix` or `arize` maps to
`arize_phoenix`.

Existing tool-specific configuration remains separate. For example,
`MESH_PROMPTFOO_COMMAND` can still point to a Promptfoo bridge command for
legacy readiness and compatibility checks, but Promptfoo does not replace
Mesh-native pass/fail evaluation.

## Account Binding

Mesh can bind any advisory lane to an existing account through environment
variables. Account binding is redacted: the evaluator records whether a
credential, endpoint, account, project, or command is configured, but it never
writes credential values into run artifacts.

Outbound export is disabled unless explicitly enabled. Set the global flag:

```bash
MESH_EVAL_EXPORT_ENABLED=true
```

Or enable a single lane:

```bash
MESH_EVAL_LANGSMITH_EXPORT_ENABLED=true
```

The exporter flag is recorded as `outbound_export_enabled`. This patch only
records connection state; it does not send evaluation artifacts to external
services.

| Lane | Mesh-owned variables | Existing account variable fallbacks |
|------|----------------------|-------------------------------------|
| Promptfoo | `MESH_EVAL_PROMPTFOO_API_KEY`, `MESH_EVAL_PROMPTFOO_ENDPOINT`, `MESH_EVAL_PROMPTFOO_PROJECT`, `MESH_EVAL_PROMPTFOO_ACCOUNT` | `PROMPTFOO_API_KEY`, `PROMPTFOO_REMOTE_API_BASE_URL`, `MESH_PROMPTFOO_COMMAND` |
| LangSmith | `MESH_EVAL_LANGSMITH_API_KEY`, `MESH_EVAL_LANGSMITH_ENDPOINT`, `MESH_EVAL_LANGSMITH_PROJECT`, `MESH_EVAL_LANGSMITH_ACCOUNT` | `LANGSMITH_API_KEY`, `LANGCHAIN_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`, `LANGCHAIN_PROJECT` |
| DeepEval / Confident AI | `MESH_EVAL_DEEPEVAL_API_KEY`, `MESH_EVAL_DEEPEVAL_ENDPOINT`, `MESH_EVAL_DEEPEVAL_PROJECT`, `MESH_EVAL_DEEPEVAL_ACCOUNT` | `DEEPEVAL_API_KEY`, `CONFIDENT_API_KEY`, `CONFIDENT_AI_API_KEY`, `CONFIDENT_API_BASE_URL`, `CONFIDENT_PROJECT`, `PYTEST_ADDOPTS` |
| RAGAS | `MESH_EVAL_RAGAS_API_KEY`, `MESH_EVAL_RAGAS_ENDPOINT`, `MESH_EVAL_RAGAS_PROJECT`, `MESH_EVAL_RAGAS_ACCOUNT` | `RAGAS_API_KEY`, `RAGAS_ENDPOINT` |
| TruLens | `MESH_EVAL_TRULENS_API_KEY`, `MESH_EVAL_TRULENS_ENDPOINT`, `MESH_EVAL_TRULENS_PROJECT`, `MESH_EVAL_TRULENS_ACCOUNT` | `TRULENS_API_KEY`, `TRULENS_ENDPOINT` |
| Braintrust | `MESH_EVAL_BRAINTRUST_API_KEY`, `MESH_EVAL_BRAINTRUST_ENDPOINT`, `MESH_EVAL_BRAINTRUST_PROJECT`, `MESH_EVAL_BRAINTRUST_ACCOUNT` | `BRAINTRUST_API_KEY`, `BRAINTRUST_API_URL`, `BRAINTRUST_PROJECT`, `BRAINTRUST_ORG_NAME` |
| Opik | `MESH_EVAL_OPIK_API_KEY`, `MESH_EVAL_OPIK_ENDPOINT`, `MESH_EVAL_OPIK_PROJECT`, `MESH_EVAL_OPIK_ACCOUNT` | `OPIK_API_KEY`, `OPIK_URL`, `OPIK_PROJECT_NAME`, `OPIK_WORKSPACE` |
| Weave | `MESH_EVAL_WEAVE_API_KEY`, `MESH_EVAL_WEAVE_ENDPOINT`, `MESH_EVAL_WEAVE_PROJECT`, `MESH_EVAL_WEAVE_ACCOUNT` | `WEAVE_API_KEY`, `WANDB_API_KEY`, `WANDB_BASE_URL`, `WANDB_PROJECT`, `WANDB_ENTITY` |
| Maxim AI | `MESH_EVAL_MAXIM_AI_API_KEY`, `MESH_EVAL_MAXIM_AI_ENDPOINT`, `MESH_EVAL_MAXIM_AI_PROJECT`, `MESH_EVAL_MAXIM_AI_ACCOUNT` | `MAXIM_API_KEY`, `MAXIM_AI_API_KEY`, `MAXIM_API_BASE_URL`, `MAXIM_PROJECT` |
| ZenML | `MESH_EVAL_ZENML_API_KEY`, `MESH_EVAL_ZENML_ENDPOINT`, `MESH_EVAL_ZENML_PROJECT`, `MESH_EVAL_ZENML_ACCOUNT` | `ZENML_STORE_API_KEY`, `ZENML_STORE_URL` |
| Arize Phoenix | `MESH_EVAL_ARIZE_PHOENIX_API_KEY`, `MESH_EVAL_ARIZE_PHOENIX_ENDPOINT`, `MESH_EVAL_ARIZE_PHOENIX_PROJECT`, `MESH_EVAL_ARIZE_PHOENIX_ACCOUNT` | `PHOENIX_API_KEY`, `ARIZE_API_KEY`, `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_ENDPOINT`, `PHOENIX_PROJECT_NAME`, `ARIZE_SPACE_KEY`, `ARIZE_ORG_KEY` |
