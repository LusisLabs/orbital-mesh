/**
 * Environment configuration for the Mesh web application.
 *
 * Defines the schema and parsing logic for required environment variables
 * including NODE_ENV, MESH_CONTROL_PLANE_URL, and MESH_OPERATOR_IDENTITY_HEADER.
 *
 * @module
 */

import { z } from "zod";

/** Schema for validating web app environment variables. */
export const MeshWebEnvironmentSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  MESH_CONTROL_PLANE_URL: z.string().url().default("http://127.0.0.1:8000"),
  MESH_OPERATOR_IDENTITY_HEADER: z.string().optional()
});

/** Inferred TypeScript type from environment schema. */
export type MeshWebEnvironment = z.infer<typeof MeshWebEnvironmentSchema>;

/**
 * Parses environment variables against the schema.
 * @param input - Environment variables (defaults to process.env).
 */
export function parseMeshWebEnvironment(
  input: Record<string, string | undefined> = process.env
): MeshWebEnvironment {
  return MeshWebEnvironmentSchema.parse(input);
}

/** Singleton parsed environment configuration. */
export const env = parseMeshWebEnvironment();
