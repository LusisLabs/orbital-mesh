import {
  dashboardRecordState,
  loadMeshResource,
  type DashboardSection,
  type OverviewRun
} from "./mesh-dashboard.server";
import { encodeControlPlaneSegment } from "./mesh-control-plane.server";

export const MESH_RUN_DETAIL_STATE_SLICE = "mesh.operator_ui.run_detail";

export interface RunEventPreview {
  event_id: string;
  sequence?: number;
  stage?: string;
  event_type?: string;
  status?: string | null;
  recorded_at?: string;
  merkle_leaf_hash?: string | null;
}

export interface RunWorkspaceData {
  stateSlice: typeof MESH_RUN_DETAIL_STATE_SLICE;
  loadedAt: string;
  runs: DashboardSection<OverviewRun[]>;
}

export interface RunDetailWorkspaceData {
  stateSlice: typeof MESH_RUN_DETAIL_STATE_SLICE;
  runId: string;
  loadedAt: string;
  run: DashboardSection<Record<string, unknown>>;
  events: DashboardSection<RunEventPreview[]>;
  evidenceGraph: DashboardSection<Record<string, unknown>>;
  merkle: DashboardSection<Record<string, unknown>>;
  timelineProof: DashboardSection<Record<string, unknown>>;
  vaultTree: DashboardSection<Array<Record<string, unknown>>>;
}

export async function loadRunsWorkspace(request: Request): Promise<RunWorkspaceData> {
  const runs = await loadMeshResource<{ runs?: OverviewRun[] }>(
    request,
    "/resources/mesh/runs?summary=1",
    { runs: [] },
    (payload) => (Array.isArray(payload.runs) && payload.runs.length > 0 ? "ready" : "empty")
  );

  return {
    stateSlice: MESH_RUN_DETAIL_STATE_SLICE,
    loadedAt: new Date().toISOString(),
    runs: { ...runs, data: Array.isArray(runs.data.runs) ? runs.data.runs : [] }
  };
}

export async function loadRunDetailWorkspace(request: Request, runId: string): Promise<RunDetailWorkspaceData> {
  const encodedRunId = encodeControlPlaneSegment(runId);
  const [run, events, evidenceGraph, merkle, timelineProof, vaultTree] = await Promise.all([
    loadMeshResource<Record<string, unknown>>(
      request,
      `/resources/mesh/runs/${encodedRunId}`,
      {},
      dashboardRecordState
    ),
    loadMeshResource<{ events?: RunEventPreview[] }>(
      request,
      `/resources/mesh/runs/${encodedRunId}/events`,
      { events: [] },
      (payload) => (Array.isArray(payload.events) && payload.events.length > 0 ? "ready" : "empty")
    ),
    loadMeshResource<Record<string, unknown>>(
      request,
      `/resources/mesh/runs/${encodedRunId}/evidence-graph`,
      {},
      dashboardRecordState
    ),
    loadMeshResource<Record<string, unknown>>(
      request,
      `/resources/mesh/runs/${encodedRunId}/merkle`,
      {},
      dashboardRecordState
    ),
    loadMeshResource<Record<string, unknown>>(
      request,
      `/resources/mesh/runs/${encodedRunId}/timeline-proof`,
      {},
      dashboardRecordState
    ),
    loadMeshResource<{ tree?: Array<Record<string, unknown>> }>(
      request,
      "/resources/mesh/vault/tree",
      { tree: [] },
      (payload) => (Array.isArray(payload.tree) && payload.tree.length > 0 ? "ready" : "empty")
    )
  ]);

  return {
    stateSlice: MESH_RUN_DETAIL_STATE_SLICE,
    runId,
    loadedAt: new Date().toISOString(),
    run,
    events: { ...events, data: Array.isArray(events.data.events) ? events.data.events : [] },
    evidenceGraph,
    merkle,
    timelineProof,
    vaultTree: { ...vaultTree, data: Array.isArray(vaultTree.data.tree) ? vaultTree.data.tree : [] }
  };
}
