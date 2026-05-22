import type { LoaderFunctionArgs } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";

import { Badge } from "../components/primitives/Badge";
import { DataTable } from "../components/primitives/Table";
import { DetailCell } from "../components/primitives/DetailCell";
import { PageHeader } from "../components/primitives/PageHeader";
import { loadRunDetailWorkspace, type RunEventPreview } from "../mesh-runs.server";
import type { DashboardSection } from "../mesh-dashboard.server";

export function loader({ params, request }: LoaderFunctionArgs) {
  const runId = params.runId;
  if (!runId) {
    throw new Response("Missing Mesh run id for mesh.operator_ui.run_detail", { status: 400 });
  }
  return loadRunDetailWorkspace(request, runId);
}

export default function RunDetailRoute() {
  const workspace = useLoaderData<typeof loader>();
  const runStatus = stringValue(workspace.run.data.status) || workspace.run.state;
  const runStage = stringValue(workspace.run.data.stage) || "unknown";

  return (
    <section className="page-stack">
      <PageHeader eyebrow={workspace.stateSlice} title={workspace.runId} />
      <dl className="detail-grid">
        <DetailCell label="Run state" value={<Badge tone={runStatus === "failed" ? "bad" : runStatus === "paused" ? "warn" : "neutral"}>{runStatus}</Badge>} />
        <DetailCell label="Stage" value={runStage} />
        <DetailCell label="Merkle" value={<SectionBadge section={workspace.merkle} />} />
        <DetailCell label="Timeline proof" value={<SectionBadge section={workspace.timelineProof} />} />
        <DetailCell label="Evidence graph" value={<SectionBadge section={workspace.evidenceGraph} />} />
        <DetailCell label="Vault preview" value={`${workspace.vaultTree.data.length} document(s)`} />
      </dl>

      <DataTable>
        <thead>
          <tr>
            <th>Event</th>
            <th>Seq</th>
            <th>Stage</th>
            <th>Type</th>
            <th>Merkle leaf</th>
          </tr>
        </thead>
        <tbody>
          {workspace.events.data.length > 0 ? (
            workspace.events.data.map((event) => <EventRow event={event} key={event.event_id} />)
          ) : (
            <tr>
              <td colSpan={5}>{workspace.events.error ? `${workspace.events.state}: ${workspace.events.error}` : "No event timeline reported."}</td>
            </tr>
          )}
        </tbody>
      </DataTable>

      <DataTable>
        <thead>
          <tr>
            <th>Proof area</th>
            <th>Resource</th>
            <th>State</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          <ProofRow label="Timeline proof" resource={`/resources/mesh/runs/${encodeURIComponent(workspace.runId)}/timeline-proof`} section={workspace.timelineProof} />
          <ProofRow label="Evidence graph" resource={`/resources/mesh/runs/${encodeURIComponent(workspace.runId)}/evidence-graph`} section={workspace.evidenceGraph} />
          <ProofRow label="Merkle snapshot" resource={`/resources/mesh/runs/${encodeURIComponent(workspace.runId)}/merkle`} section={workspace.merkle} />
          <ProofRow label="Vault tree" resource="/resources/mesh/vault/tree" section={workspace.vaultTree} />
        </tbody>
      </DataTable>
    </section>
  );
}

function EventRow({ event }: { event: RunEventPreview }) {
  return (
    <tr>
      <td>{event.event_id}</td>
      <td>{event.sequence ?? "—"}</td>
      <td>{event.stage || "—"}</td>
      <td>{event.event_type || event.status || "—"}</td>
      <td>{event.merkle_leaf_hash ? "present" : "pending"}</td>
    </tr>
  );
}

function ProofRow({ label, resource, section }: { label: string; resource: string; section: DashboardSection<unknown> }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{resource}</td>
      <td><SectionBadge section={section} /></td>
      <td>{section.error || section.state}</td>
    </tr>
  );
}

function SectionBadge({ section }: { section: DashboardSection<unknown> }) {
  const tone = section.state === "ready" ? "good" : section.state === "blocked" || section.state === "degraded" ? "warn" : section.state === "empty" ? "neutral" : "bad";
  return <Badge tone={tone}>{section.state}</Badge>;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}
