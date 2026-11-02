// Tools, MCP and skills tabs. MCP and skills are read-and-toggle only until WP7 and WP8.
import type { McpServerInfo, Risk, SkillInfo, ToolInfo } from "@protocol/ipc";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { KeyList } from "../../components/KeyList";
import { Badge, Button, Notice, Row, Section, Toggle } from "../../components/ui";
import { useT } from "../../i18n";
import { useApp } from "../../lib/appContext";
import type { TabProps } from "./tabs";

const riskTone: Record<Risk, "good" | "warn" | "bad"> = {
  safe: "good",
  confirm: "warn",
  dangerous: "bad",
};

/** Loads a list from the core once connected. */
function useList<T>(load: () => Promise<T[]> | undefined): [T[] | null, (items: T[]) => void] {
  const { core } = useApp();
  const [items, setItems] = useState<T[] | null>(null);
  const connected = core.status === "connected";
  useEffect(() => {
    if (!connected) return;
    load()
      ?.then(setItems)
      .catch(() => setItems([]));
    // load is recreated each render; reload only on reconnect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);
  return [items, setItems];
}

function Empty({ text }: { text: string }) {
  return <p className="py-4 text-sm text-slate-400">{text}</p>;
}

export function KeysTab() {
  const { t } = useT();
  return (
    <>
      <p className="mb-4 text-sm text-slate-400">{t("keys.intro")}</p>
      <Section>
        <KeyList />
      </Section>
    </>
  );
}

export function ToolsTab({ settings: s, update }: TabProps) {
  const { client } = useApp();
  const { t } = useT();
  const [tools, setTools] = useList<ToolInfo>(() =>
    client?.request("tools.list").then((r) => r.tools),
  );

  const toggle = (name: string, enabled: boolean) =>
    client
      ?.request("tools.set_enabled", { name, enabled })
      .then((info) => setTools((tools ?? []).map((x) => (x.name === name ? info : x))))
      .catch(() => undefined);

  return (
    <>
      <Section title={t("tools.list")}>
        {tools === null ? (
          <Empty text={t("common.loading")} />
        ) : tools.length === 0 ? (
          <Empty text={t("tools.none")} />
        ) : (
          tools.map((tool) => (
            <Row
              key={tool.name}
              label={
                <span className="flex items-center gap-2">
                  <code>{tool.name}</code>
                  <Badge tone={riskTone[tool.risk]}>{t(`risk.${tool.risk}`)}</Badge>
                  <Badge>{t(`source.${tool.source}`)}</Badge>
                </span>
              }
              hint={tool.description}
            >
              <Toggle
                label={tool.name}
                checked={tool.enabled}
                onChange={(on) => toggle(tool.name, on)}
              />
            </Row>
          ))
        )}
      </Section>
      <Section title={t("tools.alwaysAllow")}>
        {s.tools.always_allow.length === 0 ? (
          <Empty text={t("tools.alwaysAllowNone")} />
        ) : (
          s.tools.always_allow.map((name) => (
            <Row key={name} label={<code>{name}</code>}>
              <Button
                variant="subtle"
                aria-label={t("common.remove")}
                onClick={() =>
                  update({
                    tools: { always_allow: s.tools.always_allow.filter((n) => n !== name) },
                  })
                }
              >
                <X className="size-4" />
              </Button>
            </Row>
          ))
        )}
      </Section>
    </>
  );
}

const mcpTone = {
  connected: "good",
  connecting: "warn",
  disconnected: "neutral",
  error: "bad",
} as const;

export function McpTab() {
  const { client } = useApp();
  const { t } = useT();
  const [servers, setServers] = useList<McpServerInfo>(() =>
    client?.request("mcp.list").then((r) => r.servers),
  );
  const toggle = (name: string, enabled: boolean) =>
    client
      ?.request("mcp.set_enabled", { name, enabled })
      .then((info) => setServers((servers ?? []).map((x) => (x.name === name ? info : x))))
      .catch(() => undefined);
  return (
    <>
      <Notice>{t("mcp.soon")}</Notice>
      <Section>
        {servers === null ? (
          <Empty text={t("common.loading")} />
        ) : servers.length === 0 ? (
          <Empty text={t("mcp.none")} />
        ) : (
          servers.map((srv) => (
            <Row
              key={srv.name}
              label={
                <span className="flex items-center gap-2">
                  {srv.name}
                  <Badge tone={mcpTone[srv.status]}>{t(`mcp.status.${srv.status}`)}</Badge>
                  {srv.tools.length > 0 && <Badge>{t("mcp.tools", { n: srv.tools.length })}</Badge>}
                </span>
              }
              hint={
                <code>
                  {srv.config.url ?? [srv.config.command, ...(srv.config.args ?? [])].join(" ")}
                </code>
              }
            >
              <Toggle
                label={srv.name}
                checked={srv.enabled}
                onChange={(on) => toggle(srv.name, on)}
              />
            </Row>
          ))
        )}
      </Section>
    </>
  );
}

export function SkillsTab() {
  const { client } = useApp();
  const { t } = useT();
  const [skills, setSkills] = useList<SkillInfo>(() =>
    client?.request("skills.list").then((r) => r.skills),
  );
  const toggle = (id: string, enabled: boolean) =>
    client
      ?.request("skills.set_enabled", { id, enabled })
      .then((info) => setSkills((skills ?? []).map((x) => (x.id === id ? info : x))))
      .catch(() => undefined);
  return (
    <>
      <Notice>{t("skills.soon")}</Notice>
      <Section>
        {skills === null ? (
          <Empty text={t("common.loading")} />
        ) : skills.length === 0 ? (
          <Empty text={t("skills.none")} />
        ) : (
          skills.map((skill) => (
            <Row
              key={skill.id}
              label={
                <span className="flex items-center gap-2">
                  {skill.name}
                  {skill.builtin && <Badge>{t("skills.builtin")}</Badge>}
                  {skill.languages.map((l) => (
                    <Badge key={l}>{l}</Badge>
                  ))}
                </span>
              }
              hint={skill.description}
            >
              <Toggle
                label={skill.name}
                checked={skill.enabled}
                onChange={(on) => toggle(skill.id, on)}
              />
            </Row>
          ))
        )}
      </Section>
    </>
  );
}
