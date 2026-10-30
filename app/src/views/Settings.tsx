// Settings window: tabs on the left, auto-saving fields on the right.
import {
  Blocks,
  Brain,
  KeyRound,
  Mic,
  Plug,
  SlidersHorizontal,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useState, type ComponentType } from "react";
import { StatusPill } from "../components/StatusPill";
import { useT, type MessageKey } from "../i18n";
import { useApp } from "../lib/appContext";
import { GeneralTab } from "./settings/GeneralTab";
import { KeysTab, McpTab, SkillsTab, ToolsTab } from "./settings/ListTabs";
import { ModelsTab } from "./settings/ModelsTab";
import type { TabProps } from "./settings/tabs";
import { VoiceTab } from "./settings/VoiceTab";

type TabId = "general" | "voice" | "models" | "keys" | "tools" | "mcp" | "skills";

const tabs: { id: TabId; icon: LucideIcon; component: ComponentType<TabProps> }[] = [
  { id: "general", icon: SlidersHorizontal, component: GeneralTab },
  { id: "voice", icon: Mic, component: VoiceTab },
  { id: "models", icon: Brain, component: ModelsTab },
  { id: "keys", icon: KeyRound, component: KeysTab },
  { id: "tools", icon: Wrench, component: ToolsTab },
  { id: "mcp", icon: Plug, component: McpTab },
  { id: "skills", icon: Blocks, component: SkillsTab },
];

export function Settings({ initialTab = "general" }: { initialTab?: TabId }) {
  const { settings } = useApp();
  const { t } = useT();
  const [active, setActive] = useState<TabId>(initialTab);
  const tab = tabs.find((x) => x.id === active) ?? tabs[0]!;
  const Tab = tab.component;
  const title = (id: TabId) => t(`settings.${id}` as MessageKey);

  return (
    <main className="flex h-full bg-slate-950">
      <nav
        className="flex w-52 shrink-0 flex-col gap-0.5 border-r border-white/5 bg-white/[0.02] p-3"
        aria-label={t("tray.settings")}
      >
        <div className="mb-3 px-2 pt-1 text-lg font-semibold tracking-tight">
          {t("tray.settings")}
        </div>
        {tabs.map(({ id, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active === id}
            onClick={() => setActive(id)}
            className={`flex items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm transition ${
              active === id
                ? "bg-gradient-to-r from-amber-400/15 to-transparent text-amber-200 ring-1 ring-amber-300/20"
                : "text-slate-300 hover:bg-white/5"
            }`}
          >
            <Icon className="size-4" />
            {title(id)}
          </button>
        ))}
        <div className="mt-auto px-1">
          <StatusPill />
        </div>
      </nav>
      <section
        className="min-w-0 flex-1 overflow-y-auto px-8 py-6"
        role="tabpanel"
        data-testid={`tab-${active}`}
      >
        <h2 className="mb-5 text-xl font-semibold tracking-tight">{title(active)}</h2>
        {settings.error && (
          <div className="mb-4 rounded-xl bg-rose-500/10 px-3 py-2 text-xs text-rose-200 ring-1 ring-rose-400/20">
            {t("settings.saveFailed")}: {settings.error}
          </div>
        )}
        {settings.settings ? (
          <Tab settings={settings.settings} update={settings.update} />
        ) : (
          <p className="text-sm text-slate-400">{t("settings.waiting")}</p>
        )}
      </section>
    </main>
  );
}
