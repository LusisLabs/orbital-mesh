import type { LoaderFunctionArgs } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";

import { Badge } from "../components/primitives/Badge";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";
import { loadMeshResource, type DashboardSection } from "../mesh-dashboard.server";

const MESH_VAULT_STATE_SLICE = "mesh.operator_ui.vault";

interface VaultTreePayload {
  tree?: VaultDocument[];
  documents?: VaultDocument[];
}

type VaultDocument = Record<string, unknown>;

export async function loader({ request }: LoaderFunctionArgs) {
  const vaultTree = await loadMeshResource<VaultTreePayload>(
    request,
    "/resources/mesh/vault/tree",
    { tree: [] },
    (payload) => vaultDocuments(payload).length > 0 ? "ready" : "empty"
  );

  return {
    stateSlice: MESH_VAULT_STATE_SLICE,
    vaultTree: { ...vaultTree, data: vaultDocuments(vaultTree.data) } satisfies DashboardSection<VaultDocument[]>
  };
}

export default function VaultRoute() {
  const workspace = useLoaderData<typeof loader>();

  return (
    <section className="page-stack">
      <PageHeader eyebrow={workspace.stateSlice} title="Vault" />
      <DataTable>
        <thead>
          <tr>
            <th>Document</th>
            <th>Run</th>
            <th>Integrity</th>
          </tr>
        </thead>
        <tbody>
          {workspace.vaultTree.data.length > 0 ? (
            workspace.vaultTree.data.map((document, index) => (
              <tr key={vaultDocumentKey(document, index)}>
                <td>{stringValue(document.path) || stringValue(document.document_id) || stringValue(document.id) || `document-${index + 1}`}</td>
                <td>{stringValue(document.run_id) || stringValue(document.runId) || "—"}</td>
                <td><Badge tone={stringValue(document.merkle_root) || stringValue(document.hash) ? "good" : "neutral"}>{stringValue(document.integrity) || (stringValue(document.merkle_root) || stringValue(document.hash) ? "rooted" : workspace.vaultTree.state)}</Badge></td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={3}>{workspace.vaultTree.error ? `${workspace.vaultTree.state}: ${workspace.vaultTree.error}` : "No Mesh vault documents reported."}</td>
            </tr>
          )}
        </tbody>
      </DataTable>
    </section>
  );
}

function vaultDocuments(payload: VaultTreePayload): VaultDocument[] {
  if (Array.isArray(payload.tree)) return payload.tree;
  if (Array.isArray(payload.documents)) return payload.documents;
  return [];
}

function vaultDocumentKey(document: VaultDocument, index: number): string {
  return stringValue(document.path) || stringValue(document.document_id) || stringValue(document.id) || `vault-document-${index}`;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
