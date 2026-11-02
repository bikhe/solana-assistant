// MCP tab helpers: ready-made servers, parsing what the user types or pastes, importing.
import type { McpServerConfig, McpServerInfo } from "@protocol/ipc";
import type { MessageKey } from "../i18n";
import type { CoreClient } from "./rpc";

export interface McpPreset {
  name: string;
  title: MessageKey;
  hint: MessageKey;
  config: McpServerConfig;
  /** What must be installed on the PC; remote servers need nothing. */
  needs?: "node" | "uv";
}

/** Servers that work without an account or API key. Checked on CI by test_mcp_live.py. */
export const MCP_PRESETS: McpPreset[] = [
  {
    name: "filesystem",
    title: "mcp.preset.filesystem",
    hint: "mcp.preset.filesystem.hint",
    config: { command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "~"] },
    needs: "node",
  },
  {
    name: "time",
    title: "mcp.preset.time",
    hint: "mcp.preset.time.hint",
    config: { command: "uvx", args: ["mcp-server-time"] },
    needs: "uv",
  },
  {
    name: "fetch",
    title: "mcp.preset.fetch",
    hint: "mcp.preset.fetch.hint",
    config: { command: "uvx", args: ["mcp-server-fetch"] },
    needs: "uv",
  },
  {
    name: "mslearn",
    title: "mcp.preset.mslearn",
    hint: "mcp.preset.mslearn.hint",
    config: { url: "https://learn.microsoft.com/api/mcp" },
  },
  {
    name: "deepwiki",
    title: "mcp.preset.deepwiki",
    hint: "mcp.preset.deepwiki.hint",
    config: { url: "https://mcp.deepwiki.com/mcp" },
  },
  {
    name: "context7",
    title: "mcp.preset.context7",
    hint: "mcp.preset.context7.hint",
    config: { url: "https://mcp.context7.com/mcp" },
  },
];

/** Server names become part of tool names, so the core accepts only [A-Za-z0-9_-]. */
export function slug(name: string): string {
  return (
    name
      .replace(/[^A-Za-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "server"
  );
}

/** Split a command line like a shell would: spaces separate, quotes group. */
export function splitArgs(line: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  for (const m of line.matchAll(re)) out.push(m[1] ?? m[2] ?? m[3] ?? "");
  return out;
}

/** "https://…" is a remote server, anything else is a command to start. */
export function parseCommandLine(line: string): McpServerConfig | null {
  const text = line.trim();
  if (!text) return null;
  if (/^https?:\/\//i.test(text)) return { url: text };
  const [command, ...args] = splitArgs(text);
  return command ? { command, args } : null;
}

/** A readable default name: the host for URLs, the package for npx/uvx commands. */
export function suggestName(config: McpServerConfig): string {
  if (config.url) {
    try {
      const host = new URL(config.url).hostname.split(".");
      const main = host.length > 2 && ["mcp", "api", "www"].includes(host[0]!) ? host[1] : host[0];
      return slug(main ?? "server");
    } catch {
      return "server";
    }
  }
  const args = (config.args ?? []).filter((a) => !a.startsWith("-"));
  const pkg = args.find((a) => a.startsWith("@") || /mcp|server/i.test(a)) ?? args[0];
  const base = (pkg ?? config.command ?? "server").split(/[\\/]/).pop() ?? "server";
  return slug(base.replace(/^(mcp-)?server-|-mcp(-server)?$|^mcp-/g, ""));
}

export function describeConfig(config: McpServerConfig): string {
  return config.url ?? [config.command, ...(config.args ?? [])].join(" ");
}

export interface ImportedServer {
  name: string;
  config: McpServerConfig;
  enabled: boolean;
}

/**
 * Read the `mcpServers` block of Claude Desktop, Cursor or Claude Code config files,
 * or a bare `{name: {...}}` map. Entries without a command or URL are skipped.
 */
export function parseMcpJson(text: string): ImportedServer[] {
  const data: unknown = JSON.parse(text);
  if (!data || typeof data !== "object") throw new Error("not an object");
  const root = data as Record<string, unknown>;
  const servers = (root.mcpServers ?? root) as Record<string, unknown>;
  if (!servers || typeof servers !== "object") throw new Error("mcpServers is not an object");
  const strMap = (v: unknown) =>
    v && typeof v === "object"
      ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, String(x)]))
      : undefined;
  const out: ImportedServer[] = [];
  for (const [name, raw] of Object.entries(servers)) {
    if (!raw || typeof raw !== "object") continue;
    const e = raw as Record<string, unknown>;
    const url =
      typeof e.url === "string" ? e.url : typeof e.serverUrl === "string" ? e.serverUrl : null;
    let config: McpServerConfig;
    if (url) {
      config = { url };
      const headers = strMap(e.headers);
      if (headers && Object.keys(headers).length) config.headers = headers;
    } else if (typeof e.command === "string" && e.command) {
      config = { command: e.command };
      if (Array.isArray(e.args)) config.args = e.args.map(String);
      const env = strMap(e.env);
      if (env && Object.keys(env).length) config.env = env;
    } else continue;
    out.push({ name: slug(name), config, enabled: e.disabled !== true });
  }
  return out;
}

export interface ImportReport {
  added: string[];
  skipped: string[];
  failed: string[];
}

/** Add every server the core does not have yet; never overwrite the user's own entries. */
export async function importServers(
  client: CoreClient,
  servers: ImportedServer[],
  existing: McpServerInfo[],
): Promise<ImportReport> {
  const have = new Set(existing.map((s) => s.name));
  const report: ImportReport = { added: [], skipped: [], failed: [] };
  for (const srv of servers) {
    if (have.has(srv.name)) {
      report.skipped.push(srv.name);
      continue;
    }
    try {
      await client.request("mcp.add", { name: srv.name, config: srv.config });
      if (!srv.enabled) await client.request("mcp.set_enabled", { name: srv.name, enabled: false });
      have.add(srv.name);
      report.added.push(srv.name);
    } catch {
      report.failed.push(srv.name);
    }
  }
  return report;
}
