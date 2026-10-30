// Finds where solana-core listens.
// In Tauri the Rust side starts the core and hands us its port and token.
// In a plain browser (pnpm dev) pass them in the page URL: ?port=8765&token=dev
import { invoke, isTauri } from "@tauri-apps/api/core";

export interface CoreInfo {
  port: number;
  token: string;
}

export function coreUrl(info: CoreInfo): string {
  return `ws://127.0.0.1:${info.port}/?token=${encodeURIComponent(info.token)}`;
}

export function infoFromSearch(search: string): CoreInfo | null {
  const params = new URLSearchParams(search);
  const port = Number(params.get("port"));
  const token = params.get("token");
  return port > 0 && token ? { port, token } : null;
}

async function waitForTauriCore(pollMs = 200): Promise<CoreInfo> {
  for (;;) {
    const info = await invoke<CoreInfo | null>("core_info");
    if (info) return info;
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
}

export async function resolveCoreInfo(): Promise<CoreInfo | null> {
  if (isTauri()) return waitForTauriCore();
  return (
    infoFromSearch(window.location.search) ??
    infoFromSearch(
      `?port=${import.meta.env.VITE_CORE_PORT ?? ""}&token=${import.meta.env.VITE_CORE_TOKEN ?? ""}`,
    )
  );
}
