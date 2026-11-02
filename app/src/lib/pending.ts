// Methods the app needs that protocol/ipc.schema.json does not have yet. They are proposed in
// the WP4 PR (secrets.* match the WP3 proposal in PR #4); until the protocol PR lands, the core answers -32601 and the UI says so.
// Delete this file once the methods are in the schema and use client.request directly.
import { RpcError, type CoreClient } from "./rpc";

export interface PendingMethods {
  /** Which secret keys are set (values never leave the core). */
  "secrets.status": { params: { names: string[] }; result: { set: Record<string, boolean> } };
  /** Stores a secret in the OS keyring; an empty value deletes it. */
  "secrets.set": { params: { name: string; value: string }; result: { ok: boolean } };
  /** Push-to-talk: start (active=true) or finish (false) listening without the wake word. */
  "voice.listen": { params: { active: boolean }; result: { ok: boolean } };
}

const METHOD_NOT_FOUND = -32601;
const NOT_IMPLEMENTED = -32001;

/** True when the core does not support the method yet. */
export function isUnavailable(error: unknown): boolean {
  return (
    error instanceof RpcError && (error.code === METHOD_NOT_FOUND || error.code === NOT_IMPLEMENTED)
  );
}

export function requestPending<M extends keyof PendingMethods>(
  client: CoreClient,
  method: M,
  params: PendingMethods[M]["params"],
): Promise<PendingMethods[M]["result"]> {
  const untyped = client.request as unknown as (m: string, p: unknown) => Promise<unknown>;
  return untyped.call(client, method, params) as Promise<PendingMethods[M]["result"]>;
}
