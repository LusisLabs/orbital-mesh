import { z } from "zod";

export const MeshWebEnvironmentSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  MESH_CONTROL_PLANE_URL: z.string().url().default("http://127.0.0.1:8000"),
  MESH_OPERATOR_IDENTITY_HEADER: z.string().optional()
});

export type MeshWebEnvironment = z.infer<typeof MeshWebEnvironmentSchema>;

export function parseMeshWebEnvironment(
  input: Record<string, string | undefined> = process.env
): MeshWebEnvironment {
  return MeshWebEnvironmentSchema.parse(input);
}

export const env = parseMeshWebEnvironment();
