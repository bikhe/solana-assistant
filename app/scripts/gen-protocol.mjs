// Generates protocol/ts/ipc.ts from protocol/ipc.schema.json.
// CI runs it and fails if the committed file is out of date.
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compileFromFile } from "json-schema-to-typescript";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const schema = resolve(root, "protocol/ipc.schema.json");
const output = resolve(root, "protocol/ts/ipc.ts");

const ts = await compileFromFile(schema, {
  cwd: resolve(root, "protocol"),
  bannerComment:
    "/* Generated from protocol/ipc.schema.json by app/scripts/gen-protocol.mjs. Do not edit. */",
  unreachableDefinitions: true,
  additionalProperties: false,
  style: { semi: true, singleQuote: false, printWidth: 100 },
});

await mkdir(dirname(output), { recursive: true });
await writeFile(output, ts.replace(/\r\n/g, "\n"));
console.log(`wrote ${output}`);
