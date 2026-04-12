import {
  CheckCircle,
  Clock,
  Code,
  Copy,
  ExternalLink,
  FileText,
  FolderGit2,
  Hash,
  Search,
  Shield,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatDuration, formatTimestamp, humanize, riskColor, truncateHash } from "../lib/format";
import type { InspectorTab, MerkleProof, ResearchIntelligence, ResearchSessionDetail, RunDetail, VaultTreeEntry } from "../types";

interface InspectorProps {
  tab: InspectorTab;
  run: RunDetail | null;
  researchDetail: ResearchSessionDetail | null;
  vaultDocument: string;
  vaultTree: VaultTreeEntry[] | null;
  merkleProof: MerkleProof | null;
  gitnexusInfo: Record<string, unknown> | null;
  gitnexusProcesses: Record<string, unknown> | null;
  gitnexusSearch: string;
  gitnexusSearchResult: Record<string, unknown> | null;
  onGitnexusSearchChange: (value: string) => void;
  onGitnexusSearch: () => void;
  onVaultSelect: (path: string) => void;
}

export function Inspector(props: InspectorProps) {
  const { tab, run } = props;

  if (tab === "research") {
    if (!props.researchDetail) {
      return (
        <div className="inspector-empty">
          <FileText size={32} strokeWidth={1.2} />
          <p>
            Select a session under <strong>Research (MiniMax)</strong> in the left rail. These sessions are produced by{" "}
            <code>run_minimax_research.py</code> and are <strong>not</strong> Mesh pipeline runs, so they do not appear
            in the Run Queue.
          </p>
        </div>
      );
    }
    return <ResearchTab detail={props.researchDetail} />;
  }

  if (!run) {
    return (
      <div className="inspector-empty">
        <FileText size={32} strokeWidth={1.2} />
        <p>Select or launch a run to inspect.</p>
      </div>
    );
  }

  switch (tab) {
    case "overview":
      return <OverviewTab run={run} />;
    case "evidence":
      return <EvidenceTab run={run} />;
    case "policy":
      return <PolicyTab run={run} />;
    case "execution":
      return <ExecutionTab run={run} />;
    case "feedback":
      return <FeedbackTab run={run} />;
    case "vault":
      return <VaultTab {...props} />;
    case "merkle":
      return <MerkleTab run={run} merkleProof={props.merkleProof} />;
    case "code":
      return <CodeTab {...props} />;
    default:
      return null;
  }
}

function ResearchTab({ detail }: { detail: ResearchSessionDetail }) {
  const m = detail.manifest;
  const q = typeof m.question === "string" ? m.question : "";
  const status = typeof m.status === "string" ? m.status : "";
  const route = typeof m.minimax_route === "string" ? m.minimax_route : "";
  const model = typeof m.minimax_model === "string" ? m.minimax_model : "";
  const intelligence = detail.research_intelligence;
  return (
    <div className="inspector-scroll research-inspector">
      <div className="inspector-field">
        <span className="inspector-label">Session</span>
        <span className="inspector-value mono">{detail.session_id}</span>
      </div>
      {q ? (
        <div className="inspector-field">
          <span className="inspector-label">Question</span>
          <span className="inspector-value">{q}</span>
        </div>
      ) : null}
      <div className="inspector-field-row">
        {status ? <Badge label={status} color="#41d6b1" /> : null}
        {route ? <Badge label={`route: ${route}`} color="#8b9bb4" /> : null}
        {model ? <Badge label={model} color="#6b8cae" /> : null}
      </div>
      {intelligence ? <ResearchIntelligencePanel intelligence={intelligence} /> : null}
      {detail.final_report_markdown ? (
        <MarkdownDocument className="research-markdown markdown-document" content={detail.final_report_markdown} />
      ) : (
        <p className="muted">No synthesis/final-report.md yet.</p>
      )}
    </div>
  );
}

function ResearchIntelligencePanel({ intelligence }: { intelligence: ResearchIntelligence }) {
  return (
    <Section title="Research Intelligence">
      <div className="inspector-field-row">
        <Badge label={humanize(intelligence.classification)} color={researchClassificationColor(intelligence.classification)} />
        <Badge label={`repo ${intelligence.repo_grounding_score}`} color="#7fcf9f" />
        <Badge label={`drift ${intelligence.off_domain_score}`} color="#d7a95e" />
      </div>
      {intelligence.flags.length > 0 ? (
        <div className="inspector-field-row">
          {intelligence.flags.map((flag) => (
            <Badge key={flag} label={humanize(flag)} color="#d76c75" />
          ))}
        </div>
      ) : null}
      {intelligence.anchors.length > 0 ? (
        <MiniList title="Grounded anchors" items={intelligence.anchors.slice(0, 4).map((anchor) => anchor.label)} />
      ) : null}
      {intelligence.extracted_actions && intelligence.extracted_actions.length > 0 ? (
        <MiniList title="Next actions" items={intelligence.extracted_actions.slice(0, 4)} />
      ) : null}
      {intelligence.off_domain_terms && intelligence.off_domain_terms.length > 0 ? (
        <MiniList title="Drift terms" items={intelligence.off_domain_terms.slice(0, 8)} inline />
      ) : null}
    </Section>
  );
}

function MiniList({ title, items, inline }: { title: string; items: string[]; inline?: boolean }) {
  return (
    <div className="mini-list">
      <span className="inspector-label">{title}</span>
      {inline ? (
        <p className="muted">{items.join(", ")}</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function researchClassificationColor(classification: ResearchIntelligence["classification"]) {
  switch (classification) {
    case "repo_grounded":
      return "#7fcf9f";
    case "mixed":
      return "#d7a95e";
    case "off_domain":
      return "#d76c75";
    default:
      return "#8b9bb4";
  }
}

/* ─── Shared helpers ─── */

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="inspector-field">
      <span className="inspector-label">{label}</span>
      <span className={mono ? "inspector-value mono" : "inspector-value"}>{value ?? "—"}</span>
    </div>
  );
}

function Badge({
  label,
  color,
  icon,
}: {
  label: string;
  color: string;
  icon?: React.ReactNode;
}) {
  return (
    <span className="inspector-badge" style={{ borderColor: color, color }}>
      {icon}
      {label}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy-btn"
      title="Copy to clipboard"
      onClick={() => {
        void navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <CheckCircle size={12} /> : <Copy size={12} />}
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="inspector-section">
      <h4 className="inspector-section-title">{title}</h4>
      {children}
    </div>
  );
}

function JsonBlock({ data }: { data: unknown }) {
  const text = JSON.stringify(data, null, 2);
  return (
    <div className="inspector-json-wrap">
      <CopyButton text={text} />
      <pre className="inspector-json">{text}</pre>
    </div>
  );
}

function MarkdownDocument({ content, className }: { content: string; className?: string }) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function PassFail({ passed }: { passed: boolean }) {
  return passed ? (
    <Badge label="Passed" color="var(--accent-good)" icon={<CheckCircle size={12} />} />
  ) : (
    <Badge label="Failed" color="var(--accent-danger)" icon={<XCircle size={12} />} />
  );
}

/* ─── Overview ─── */

function OverviewTab({ run }: { run: RunDetail }) {
  return (
    <div className="inspector-scroll">
      <Section title="Run Identity">
        <Field
          label="Run ID"
          value={
            <span className="inline-flex">
              <code>{run.run_id}</code>
              <CopyButton text={run.run_id} />
            </span>
          }
        />
        <Field label="Stage" value={<Badge label={humanize(run.stage)} color={stageColor(run.stage)} />} />
        <Field label="Status" value={humanize(run.status)} />
        <Field label="Scenario" value={run.scenario_key ?? "Manual signal"} />
      </Section>

      <Section title="Configuration">
        <Field label="Steering Mode" value={humanize(run.steering_mode)} />
        <Field label="Auto Mode" value={run.auto_mode ? "Enabled" : "Disabled"} />
        <Field label="Evaluation" value={humanize(run.evaluation_mode)} />
        <Field label="Orchestration" value={humanize(run.orchestration_mode)} />
        {run.pause_points.length > 0 && (
          <Field label="Pause Points" value={run.pause_points.map(humanize).join(", ")} />
        )}
      </Section>

      <Section title="Timing">
        <Field label="Created" value={formatTimestamp(run.created_at)} />
        <Field label="Updated" value={formatTimestamp(run.updated_at)} />
        <Field label="Duration" value={formatDuration(run.created_at, run.updated_at)} />
      </Section>

      <Section title="Event Ledger">
        <Field label="Events" value={`${run.events.length} recorded`} />
        <Field label="Latest Sequence" value={String(run.latest_event_sequence)} />
        <Field
          label="Merkle Root"
          value={
            run.latest_merkle_root ? (
              <span className="inline-flex">
                <code>{truncateHash(run.latest_merkle_root, 20)}</code>
                <CopyButton text={run.latest_merkle_root} />
              </span>
            ) : (
              "—"
            )
          }
        />
      </Section>

      {run.operator_notes.length > 0 && (
        <Section title="Operator Notes">
          <ul className="inspector-notes">
            {run.operator_notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </Section>
      )}

      {run.error && (
        <Section title="Error">
          <div className="inspector-alert danger">{run.error}</div>
        </Section>
      )}
    </div>
  );
}

/* ─── Evidence ─── */

function EvidenceTab({ run }: { run: RunDetail }) {
  const trigger = run.artifacts.trigger;
  const decision = run.artifacts.decision;

  return (
    <div className="inspector-scroll">
      <Section title="Trigger Signal">
        {trigger ? (
          <>
            <Field label="Trigger ID" value={<code>{trigger.trigger_id}</code>} />
            {trigger.segment && <Field label="Segment" value={String(trigger.segment)} />}
            {trigger.signal_type && <Field label="Type" value={humanize(String(trigger.signal_type))} />}
            <JsonBlock data={trigger} />
          </>
        ) : (
          <p className="inspector-muted">No trigger signal recorded.</p>
        )}
      </Section>

      <Section title="Decision">
        {decision ? (
          <>
            <Field label="Decision ID" value={<code>{decision.decision_id}</code>} />
            <Field
              label="Type"
              value={<Badge label={humanize(String(decision.decision_type ?? "—"))} color="var(--accent)" />}
            />
            {decision.confidence != null && (
              <Field
                label="Confidence"
                value={
                  <span className="confidence-bar-wrap">
                    <span className="confidence-bar" style={{ width: `${Number(decision.confidence) * 100}%` }} />
                    <span>{(Number(decision.confidence) * 100).toFixed(0)}%</span>
                  </span>
                }
              />
            )}
            {decision.risk && (
              <Field
                label="Risk"
                value={
                  <Badge
                    label={humanize(String(decision.risk.level ?? "unknown"))}
                    color={riskColor(String(decision.risk.level))}
                  />
                }
              />
            )}
            {decision.summary && (
              <Field label="Summary" value={String(decision.summary)} />
            )}
            {decision.reasoning && (
              <div className="inspector-reasoning">
                <span className="inspector-label">Reasoning</span>
                <p>{String(decision.reasoning)}</p>
              </div>
            )}
            {decision.execution_plan && (
              <>
                <h5 className="inspector-subheading">Execution Plan</h5>
                <JsonBlock data={decision.execution_plan} />
              </>
            )}
          </>
        ) : (
          <p className="inspector-muted">No decision recorded yet.</p>
        )}
      </Section>
    </div>
  );
}

/* ─── Policy ─── */

function PolicyTab({ run }: { run: RunDetail }) {
  const evaluation = run.artifacts.evaluation;
  if (!evaluation) {
    return <p className="inspector-muted" style={{ padding: "1rem" }}>No evaluation recorded yet.</p>;
  }

  const stageResults: Record<string, unknown> = evaluation.stage_results ?? {};
  const blocking: string[] = evaluation.blocking_reasons ?? [];
  const recommendation = String(evaluation.final_recommendation ?? "—");

  return (
    <div className="inspector-scroll">
      <Section title="Evaluation Result">
        <Field
          label="Passed"
          value={<PassFail passed={Boolean(evaluation.passed)} />}
        />
        <Field
          label="Recommendation"
          value={
            <Badge
              label={humanize(recommendation)}
              color={recommendation === "execute" ? "var(--accent-good)" : recommendation === "reject" ? "var(--accent-danger)" : "var(--accent-warm)"}
            />
          }
        />
        {evaluation.evaluation_id && (
          <Field label="Evaluation ID" value={<code>{String(evaluation.evaluation_id)}</code>} />
        )}
      </Section>

      <Section title="Gate Results">
        <div className="gate-results">
          {Object.entries(stageResults).map(([gate, result]) => {
            const r = result as Record<string, unknown> | undefined;
            const passed = r?.passed !== false;
            return (
              <div key={gate} className="gate-row">
                <span className="gate-indicator" data-passed={String(passed)}>
                  {passed ? <CheckCircle size={14} /> : <XCircle size={14} />}
                </span>
                <span className="gate-name">{humanize(gate)}</span>
                {r?.detail != null && <span className="gate-detail">{String(r.detail)}</span>}
              </div>
            );
          })}
        </div>
      </Section>

      {blocking.length > 0 && (
        <Section title="Blocking Reasons">
          <div className="blocking-list">
            {blocking.map((reason, i) => (
              <div key={i} className="inspector-alert danger">
                <XCircle size={14} />
                <span>{reason}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section title="Raw Evaluation">
        <JsonBlock data={evaluation} />
      </Section>
    </div>
  );
}

/* ─── Execution ─── */

function ExecutionTab({ run }: { run: RunDetail }) {
  const exec = run.artifacts.execution;
  if (!exec) {
    return <p className="inspector-muted" style={{ padding: "1rem" }}>No execution recorded yet.</p>;
  }

  return (
    <div className="inspector-scroll">
      <Section title="Execution Record">
        <Field label="Execution ID" value={<code>{String(exec.execution_id ?? "—")}</code>} />
        <Field
          label="Status"
          value={
            <Badge
              label={humanize(String(exec.status ?? "—"))}
              color={exec.status === "success" ? "var(--accent-good)" : exec.status === "rejected" ? "var(--accent-danger)" : "var(--accent-warm)"}
            />
          }
        />
        <Field label="Executor" value={humanize(String(exec.executor ?? "—"))} />
        {exec.idempotency_key && (
          <Field label="Idempotency Key" value={<code>{String(exec.idempotency_key)}</code>} />
        )}
      </Section>

      {exec.applied_action && (
        <Section title="Applied Action">
          <JsonBlock data={exec.applied_action} />
        </Section>
      )}

      {exec.external_refs && Object.keys(exec.external_refs).length > 0 && (
        <Section title="External References">
          {Object.entries(exec.external_refs as Record<string, string>).map(([key, value]) => (
            <Field key={key} label={humanize(key)} value={<span className="inline-flex"><ExternalLink size={12} />{String(value)}</span>} />
          ))}
        </Section>
      )}

      {exec.failure && (
        <Section title="Failure">
          <div className="inspector-alert danger">
            <JsonBlock data={exec.failure} />
          </div>
        </Section>
      )}

      {(exec.started_at || exec.completed_at) && (
        <Section title="Timing">
          {exec.started_at && <Field label="Started" value={formatTimestamp(String(exec.started_at))} />}
          {exec.completed_at && <Field label="Completed" value={formatTimestamp(String(exec.completed_at))} />}
          {exec.started_at && exec.completed_at && (
            <Field label="Duration" value={formatDuration(String(exec.started_at), String(exec.completed_at))} />
          )}
        </Section>
      )}
    </div>
  );
}

/* ─── Feedback ─── */

function FeedbackTab({ run }: { run: RunDetail }) {
  const feedback = run.artifacts.feedback;
  if (!feedback) {
    return <p className="inspector-muted" style={{ padding: "1rem" }}>No feedback recorded yet.</p>;
  }

  return (
    <div className="inspector-scroll">
      <Section title="Feedback">
        {feedback.feedback_id && <Field label="Feedback ID" value={<code>{String(feedback.feedback_id)}</code>} />}
        {feedback.outcome && (
          <Field
            label="Outcome"
            value={
              <Badge
                label={humanize(String(feedback.outcome))}
                color={feedback.outcome === "success" ? "var(--accent-good)" : "var(--accent-danger)"}
              />
            }
          />
        )}
        {feedback.metrics && (
          <Section title="Metrics">
            <JsonBlock data={feedback.metrics} />
          </Section>
        )}
        {feedback.observations && (
          <Section title="Observations">
            {Array.isArray(feedback.observations) ? (
              <ul className="inspector-notes">
                {(feedback.observations as string[]).map((obs, i) => (
                  <li key={i}>{obs}</li>
                ))}
              </ul>
            ) : (
              <JsonBlock data={feedback.observations} />
            )}
          </Section>
        )}
      </Section>

      <Section title="Raw Feedback">
        <JsonBlock data={feedback} />
      </Section>
    </div>
  );
}

/* ─── Vault ─── */

function VaultTab(props: InspectorProps) {
  const { vaultDocument, vaultTree, onVaultSelect } = props;
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());

  function toggleDir(path: string) {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  }

  function renderTreeEntry(entry: VaultTreeEntry, depth = 0) {
    const isDir = entry.type === "directory";
    const isOpen = expandedDirs.has(entry.path);
    return (
      <div key={entry.path}>
        <button
          className="vault-tree-item"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => (isDir ? toggleDir(entry.path) : onVaultSelect(entry.path))}
        >
          <span className="vault-tree-icon">{isDir ? (isOpen ? "▾" : "▸") : "◇"}</span>
          <span>{entry.name}</span>
        </button>
        {isDir && isOpen && entry.children?.map((child) => renderTreeEntry(child, depth + 1))}
      </div>
    );
  }

  return (
    <div className="inspector-scroll">
      {vaultTree && vaultTree.length > 0 && (
        <Section title="Vault Browser">
          <div className="vault-tree">
            {vaultTree.map((entry) => renderTreeEntry(entry))}
          </div>
        </Section>
      )}
      <Section title="Document">
        {vaultDocument ? (
          <MarkdownDocument className="vault-content markdown-document" content={vaultDocument} />
        ) : (
          <p className="inspector-muted">No vault document loaded.</p>
        )}
      </Section>
    </div>
  );
}

/* ─── Merkle ─── */

function MerkleTab({ run, merkleProof }: { run: RunDetail; merkleProof: MerkleProof | null }) {
  const proofNodes = merkleProof ? buildProofNodes(merkleProof) : [];
  return (
    <div className="inspector-scroll">
      <Section title="Merkle Snapshot">
        <Field
          label="Root Hash"
          value={
            run.merkle?.root_hash ? (
              <span className="inline-flex">
                <code>{truncateHash(run.merkle.root_hash, 24)}</code>
                <CopyButton text={run.merkle.root_hash} />
              </span>
            ) : (
              "—"
            )
          }
        />
        <Field label="Leaf Count" value={String(run.merkle?.leaf_count ?? 0)} />
        <Field label="Event IDs" value={`${run.merkle?.event_ids?.length ?? 0} tracked`} />
      </Section>

      {merkleProof && (
        <Section title="Inclusion Proof">
          <Field
            label="Valid"
            value={
              merkleProof.valid ? (
                <Badge label="Valid" color="var(--accent-good)" icon={<Shield size={12} />} />
              ) : (
                <Badge label="Invalid" color="var(--accent-danger)" icon={<XCircle size={12} />} />
              )
            }
          />
          <Field label="Event" value={<code>{merkleProof.event_id}</code>} />
          <Field label="Leaf Hash" value={<code>{truncateHash(merkleProof.leaf_hash, 20)}</code>} />
          <Field label="Root Hash" value={<code>{truncateHash(merkleProof.root_hash, 20)}</code>} />

          {proofNodes.length > 0 && (
            <div className="merkle-proof-ladder">
              <h5 className="inspector-subheading">Verification Path</h5>
              {proofNodes.map((node, i) => (
                <div key={`${node.kind}-${i}`} className={`merkle-proof-node ${node.kind}`}>
                  <span className="merkle-proof-node-label">{node.label}</span>
                  <code>{truncateHash(node.hash, 18)}</code>
                </div>
              ))}
            </div>
          )}

          {merkleProof.proof.length > 0 && (
            <div className="merkle-chain">
              <h5 className="inspector-subheading">Proof Chain</h5>
              {merkleProof.proof.map((step, i) => (
                <div key={i} className="merkle-step">
                  <Badge
                    label={step.position}
                    color={step.position === "left" ? "var(--accent)" : "var(--accent-warm)"}
                  />
                  <code>{truncateHash(step.hash, 16)}</code>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      <Section title="Raw Snapshot">
        <JsonBlock data={{ snapshot: run.merkle, proof: merkleProof }} />
      </Section>
    </div>
  );
}

/* ─── Code (GitNexus) ─── */

function CodeTab(props: InspectorProps) {
  const { gitnexusInfo, gitnexusProcesses, gitnexusSearch, gitnexusSearchResult, onGitnexusSearchChange, onGitnexusSearch } = props;

  return (
    <div className="inspector-scroll">
      <Section title="GitNexus Search">
        <div className="gitnexus-search-bar">
          <Search size={14} />
          <input
            value={gitnexusSearch}
            onChange={(e) => onGitnexusSearchChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onGitnexusSearch()}
            placeholder="Search code intelligence…"
          />
          <button className="action-button compact" onClick={onGitnexusSearch}>
            <FolderGit2 size={14} />
            Query
          </button>
        </div>
        {gitnexusSearchResult && <JsonBlock data={gitnexusSearchResult} />}
      </Section>

      {gitnexusInfo && (
        <Section title="Repository Info">
          <JsonBlock data={gitnexusInfo} />
        </Section>
      )}

      {gitnexusProcesses && (
        <Section title="Execution Flows">
          <JsonBlock data={gitnexusProcesses} />
        </Section>
      )}

      {!gitnexusInfo && !gitnexusProcesses && (
        <div className="inspector-empty compact">
          <Code size={24} strokeWidth={1.2} />
          <p>GitNexus sidecar not connected.</p>
        </div>
      )}
    </div>
  );
}

/* ─── Utils ─── */

function stageColor(stage: string): string {
  if (stage === "completed") return "var(--accent-good)";
  if (stage === "failed" || stage === "cancelled") return "var(--accent-danger)";
  if (stage === "awaiting_operator") return "var(--accent-warm)";
  if (stage === "executing") return "var(--accent)";
  return "var(--muted)";
}

function buildProofNodes(proof: MerkleProof): Array<{ kind: "leaf" | "sibling" | "root"; label: string; hash: string }> {
  const nodes: Array<{ kind: "leaf" | "sibling" | "root"; label: string; hash: string }> = [
    { kind: "leaf", label: "Leaf", hash: proof.leaf_hash },
  ];
  proof.proof.forEach((step, index) => {
    nodes.push({
      kind: "sibling",
      label: `Step ${index + 1} ${step.position}`,
      hash: step.hash,
    });
  });
  nodes.push({ kind: "root", label: "Root", hash: proof.root_hash });
  return nodes;
}
