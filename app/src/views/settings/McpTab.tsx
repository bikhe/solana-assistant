// MCP tab: connected servers with their tools, ready-made servers, adding and importing.
import type { McpServerInfo, ToolInfo } from "@protocol/ipc";
import { ChevronDown, Download, Plus, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Row, Section, TextField, Toggle } from "../../components/ui";
import { useT } from "../../i18n";
import { useApp } from "../../lib/appContext";
import {
  MCP_PRESETS,
  describeConfig,
  importServers,
  parseCommandLine,
  parseMcpJson,
  suggestName,
  type ImportReport,
  type ImportedServer,
} from "../../lib/mcp";
import { inTauri, readClaudeDesktopConfig } from "../../lib/platform";
import { RpcError } from "../../lib/rpc";

const tone = {
  connected: "good",
  connecting: "warn",
  disconnected: "neutral",
  error: "bad",
} as const;

/** How often the list refreshes while the tab is open: statuses change in the background. */
const POLL_MS = 1500;

function errorText(err: unknown): string {
  return err instanceof RpcError || err instanceof Error ? err.message : String(err);
}

export function McpTab() {
  const { client, core } = useApp();
  const { t } = useT();
  const [servers, setServers] = useState<McpServerInfo[] | null>(null);
  const connected = core.status === "connected";

  const reload = useCallback(async () => {
    if (!client) return;
    try {
      setServers((await client.request("mcp.list")).servers);
    } catch {
      setServers((prev) => prev ?? []);
    }
  }, [client]);

  useEffect(() => {
    if (!connected) return;
    const first = setTimeout(() => void reload(), 0);
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [connected, reload]);

  const replace = (info: McpServerInfo) =>
    setServers((list) => (list ?? []).map((s) => (s.name === info.name ? info : s)));

  const add = async (name: string, config: ImportedServer["config"]) => {
    if (!client) return;
    const info = await client.request("mcp.add", { name, config });
    setServers((list) => [...(list ?? []), info]);
  };

  const names = new Set((servers ?? []).map((s) => s.name));

  return (
    <>
      <p className="mb-4 text-sm text-slate-400">{t("mcp.intro")}</p>
      <Section title={t("mcp.mine")}>
        {servers === null ? (
          <Empty text={t("common.loading")} />
        ) : servers.length === 0 ? (
          <Empty text={t("mcp.none")} />
        ) : (
          servers.map((srv) => (
            <ServerRow
              key={srv.name}
              server={srv}
              onToggle={(enabled) =>
                client
                  ?.request("mcp.set_enabled", { name: srv.name, enabled })
                  .then(replace)
                  .catch(() => undefined)
              }
              onRemove={() =>
                client
                  ?.request("mcp.remove", { name: srv.name })
                  .then(() => setServers((list) => (list ?? []).filter((s) => s.name !== srv.name)))
                  .catch(() => undefined)
              }
              onToolToggle={(tool, enabled) =>
                client
                  ?.request("tools.set_enabled", { name: tool, enabled })
                  .then((info) =>
                    replace({
                      ...srv,
                      tools: srv.tools.map((x) => (x.name === tool ? info : x)),
                    }),
                  )
                  .catch(() => undefined)
              }
            />
          ))
        )}
      </Section>

      <Section title={t("mcp.presets")}>
        <p className="pt-3 text-xs text-slate-400">{t("mcp.presets.hint")}</p>
        <div className="grid grid-cols-1 gap-2 py-3 sm:grid-cols-2">
          {MCP_PRESETS.map((preset) => (
            <div
              key={preset.name}
              className="flex items-start justify-between gap-3 rounded-xl bg-white/[0.03] p-3 ring-1 ring-white/[0.06]"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-100">{t(preset.title)}</div>
                <div className="mt-0.5 text-xs text-slate-400">{t(preset.hint)}</div>
                {preset.needs && (
                  <div className="mt-1 text-[11px] text-amber-300/80">
                    {t(`mcp.needs.${preset.needs}`)}
                  </div>
                )}
              </div>
              <Button
                variant="ghost"
                className="shrink-0 px-3 py-1.5"
                disabled={!connected || names.has(preset.name)}
                aria-label={`${t("mcp.add")}: ${t(preset.title)}`}
                onClick={() => void add(preset.name, preset.config).catch(() => undefined)}
              >
                {names.has(preset.name) ? t("mcp.added") : <Plus className="size-4" />}
              </Button>
            </div>
          ))}
        </div>
      </Section>

      <AddForm disabled={!connected} taken={names} onAdd={add} />
      <ImportBox
        disabled={!connected}
        onImport={async (list) => {
          if (!client) return { added: [], skipped: [], failed: [] };
          const report = await importServers(client, list, servers ?? []);
          await reload();
          return report;
        }}
      />
    </>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="py-4 text-sm text-slate-400">{text}</p>;
}

function ServerRow({
  server: srv,
  onToggle,
  onRemove,
  onToolToggle,
}: {
  server: McpServerInfo;
  onToggle: (enabled: boolean) => void;
  onRemove: () => void;
  onToolToggle: (tool: string, enabled: boolean) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-white/5 last:border-0" data-testid={`mcp-${srv.name}`}>
      <Row
        label={
          <span className="flex flex-wrap items-center gap-2">
            {srv.name}
            <Badge tone={tone[srv.status]}>{t(`mcp.status.${srv.status}`)}</Badge>
            {srv.tools.length > 0 && <Badge>{t("mcp.tools", { n: srv.tools.length })}</Badge>}
          </span>
        }
        hint={
          <>
            <code className="break-all">{describeConfig(srv.config)}</code>
            {srv.error && <div className="mt-1 text-rose-300">{srv.error}</div>}
          </>
        }
      >
        {srv.tools.length > 0 && (
          <Button
            variant="subtle"
            className="px-2"
            aria-expanded={open}
            aria-label={t("mcp.showTools")}
            onClick={() => setOpen(!open)}
          >
            <ChevronDown className={`size-4 transition ${open ? "rotate-180" : ""}`} />
          </Button>
        )}
        <Button
          variant="subtle"
          className="px-2"
          aria-label={t("common.remove")}
          onClick={onRemove}
        >
          <X className="size-4" />
        </Button>
        <Toggle label={srv.name} checked={srv.enabled} onChange={onToggle} />
      </Row>
      {open && (
        <ul className="mb-3 ml-2 border-l border-white/10 pl-4">
          {srv.tools.map((tool: ToolInfo) => (
            <li key={tool.name} className="flex items-center justify-between gap-4 py-1.5">
              <div className="min-w-0">
                <code className="text-xs text-slate-200">{tool.name}</code>
                <div className="truncate text-[11px] text-slate-500">{tool.description}</div>
              </div>
              <Toggle
                label={tool.name}
                checked={tool.enabled}
                onChange={(on) => onToolToggle(tool.name, on)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AddForm({
  disabled,
  taken,
  onAdd,
}: {
  disabled: boolean;
  taken: Set<string>;
  onAdd: (name: string, config: ImportedServer["config"]) => Promise<void>;
}) {
  const { t } = useT();
  const [line, setLine] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const config = parseCommandLine(line);
  const finalName = name.trim() || (config ? suggestName(config) : "");

  const submit = async () => {
    if (!config) return;
    if (taken.has(finalName)) {
      setError(t("mcp.nameTaken", { name: finalName }));
      return;
    }
    try {
      await onAdd(finalName, config);
      setLine("");
      setName("");
      setError(null);
    } catch (err) {
      setError(errorText(err));
    }
  };

  return (
    <Section title={t("mcp.custom")}>
      <div className="flex flex-col gap-2 py-3">
        <TextField
          aria-label={t("mcp.commandOrUrl")}
          placeholder="npx -y @modelcontextprotocol/server-memory  ·  https://example.com/mcp"
          value={line}
          disabled={disabled}
          onChange={(e) => setLine(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
        />
        <div className="flex gap-2">
          <TextField
            className="flex-1"
            aria-label={t("mcp.name")}
            placeholder={config ? suggestName(config) : t("mcp.name")}
            value={name}
            disabled={disabled}
            onChange={(e) => setName(e.target.value)}
          />
          <Button variant="primary" disabled={disabled || !config} onClick={() => void submit()}>
            <Plus className="size-4" />
            {t("mcp.add")}
          </Button>
        </div>
        {error && <p className="text-xs text-rose-300">{error}</p>}
      </div>
    </Section>
  );
}

function ImportBox({
  disabled,
  onImport,
}: {
  disabled: boolean;
  onImport: (servers: ImportedServer[]) => Promise<ImportReport>;
}) {
  const { t } = useT();
  const [json, setJson] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const run = async (text: string | null) => {
    if (text === null) {
      setMessage({ ok: false, text: t("mcp.import.noClaude") });
      return;
    }
    let list: ImportedServer[];
    try {
      list = parseMcpJson(text);
    } catch {
      setMessage({ ok: false, text: t("mcp.import.badJson") });
      return;
    }
    if (list.length === 0) {
      setMessage({ ok: false, text: t("mcp.import.empty") });
      return;
    }
    const report = await onImport(list);
    const parts = [
      report.added.length && t("mcp.import.added", { names: report.added.join(", ") }),
      report.skipped.length && t("mcp.import.skipped", { names: report.skipped.join(", ") }),
      report.failed.length && t("mcp.import.failed", { names: report.failed.join(", ") }),
    ].filter(Boolean);
    setMessage({ ok: report.failed.length === 0, text: parts.join(" ") });
    if (report.added.length) setJson("");
  };

  return (
    <Section title={t("mcp.import")}>
      <div className="flex flex-col gap-2 py-3">
        {inTauri() && (
          <Button
            disabled={disabled}
            className="self-start"
            onClick={() => void readClaudeDesktopConfig().then(run)}
          >
            <Download className="size-4" />
            {t("mcp.import.claude")}
          </Button>
        )}
        <textarea
          aria-label={t("mcp.import.json")}
          placeholder={
            '{ "mcpServers": { "memory": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"] } } }'
          }
          value={json}
          disabled={disabled}
          onChange={(e) => setJson(e.target.value)}
          rows={4}
          className="rounded-xl bg-slate-900/80 px-3 py-2 font-mono text-xs text-slate-100 ring-1 ring-white/10 transition outline-none focus:ring-2 focus:ring-amber-400/60 disabled:opacity-50"
        />
        <Button
          className="self-start"
          disabled={disabled || !json.trim()}
          onClick={() => void run(json)}
        >
          {t("mcp.import.run")}
        </Button>
        {message && (
          <p className={`text-xs ${message.ok ? "text-emerald-300" : "text-rose-300"}`}>
            {message.text}
          </p>
        )}
      </div>
    </Section>
  );
}
