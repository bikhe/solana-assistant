import { useEffect } from "react";
import { LanguageContext, translate } from "./i18n";
import { AppContext } from "./lib/appContext";
import { browserNavigate, currentView, inTauri, setWindowTitle, type View } from "./lib/platform";
import type { CoreClient } from "./lib/rpc";
import { useSettings } from "./lib/settings";
import { useCore, useCoreClient } from "./lib/useCore";
import { Chat } from "./views/Chat";
import { Overlay } from "./views/Overlay";
import { Settings } from "./views/Settings";
import { Wizard } from "./views/Wizard";

const screens: Record<View, React.ComponentType> = {
  overlay: Overlay,
  chat: Chat,
  settings: Settings,
  wizard: Wizard,
};

/** Browser-only switcher between the windows, for pnpm dev and screenshots. */
function DevNav({ view }: { view: View }) {
  return (
    <nav className="fixed right-2 bottom-2 z-50 flex gap-1 rounded-full bg-black/60 p-1 text-[11px] opacity-30 ring-1 ring-white/10 transition hover:opacity-100">
      {(Object.keys(screens) as View[]).map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => browserNavigate(v)}
          className={`rounded-full px-2 py-0.5 ${v === view ? "bg-white/20" : "hover:bg-white/10"}`}
        >
          {v}
        </button>
      ))}
    </nav>
  );
}

export function App({ client: given, view: forced }: { client?: CoreClient; view?: View }) {
  const { client, noCore } = useCoreClient(given);
  const { view: core, dispatch } = useCore(client);
  const settings = useSettings(client, core.status === "connected");
  const lang = settings.settings?.general.language ?? "ru";
  const view = forced ?? currentView();
  const Screen = screens[view];

  useEffect(() => {
    const titles = {
      overlay: "Solana",
      chat: "Solana",
      settings: translate(lang, "tray.settings"),
      wizard: "Solana",
    };
    setWindowTitle(
      view === "chat" || view === "overlay" ? titles[view] : `Solana · ${titles[view]}`,
    ).catch(() => undefined);
  }, [lang, view]);

  return (
    <LanguageContext.Provider value={lang}>
      <AppContext.Provider value={{ client, core, dispatch, settings, noCore }}>
        <Screen />
        {!inTauri() && !forced && <DevNav view={view} />}
      </AppContext.Provider>
    </LanguageContext.Provider>
  );
}
