import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { compileFromFile } from "json-schema-to-typescript";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(packageRoot, "..", "..");
const checkOnly = process.argv.includes("--check");

const targets = [
  {
    name: "ControlPlaneSchema",
    schema: path.join(repoRoot, "shared", "mesh_runtime", "schemas", "control-plane.schema.json"),
    output: path.join(packageRoot, "src", "generated", "control-plane.ts")
  },
  {
    name: "OperatorProductSchema",
    schema: path.join(repoRoot, "shared", "mesh_runtime", "schemas", "operator-product.schema.json"),
    output: path.join(packageRoot, "src", "generated", "operator-product.ts")
  }
];

const bannerComment = [
  "/* eslint-disable */",
  "// Generated from Mesh JSON Schemas. Do not edit by hand.",
  "// Source of truth: shared/mesh_runtime/schemas/."
].join("\n");

let changed = false;

for (const target of targets) {
  const generated = await compileFromFile(target.schema, {
    bannerComment,
    cwd: repoRoot,
    declareExternallyReferenced: true,
    enableConstEnums: false,
    style: {
      semi: true,
      singleQuote: false,
      trailingComma: "none"
    },
    typeName: target.name,
    unknownAny: false
  });
  const normalized = generated.endsWith("\n") ? generated : `${generated}\n`;
  let current = null;
  try {
    current = await readFile(target.output, "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") {
      throw error;
    }
  }
  if (current !== normalized) {
    changed = true;
    if (checkOnly) {
      console.error(`${path.relative(repoRoot, target.output)} is out of date`);
    } else {
      await mkdir(path.dirname(target.output), { recursive: true });
      await writeFile(target.output, normalized, "utf8");
    }
  }
}

if (checkOnly && changed) {
  process.exit(1);
}
