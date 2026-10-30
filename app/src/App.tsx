import { useEffect, useState } from "react";
import { Orb } from "./components/Orb";
import { coreUrl, resolveCoreInfo } from "./lib/connection";
import { stateLabels, statusLabels } from "./lib/labels";
import { CoreClient } from "./lib/rpc";
import { useCore } from "./lib/useCore";

const statusDot = {
  connected: "bg-emerald-400",
  connecting: "bg-amber-400 animate-pulse",
  disconnected: "bg-rose-500",
};

export function App({ client: given }: { client?: CoreClient }) {
  const [client, setClient] = useState<CoreClient | null>(given ?? null);
  const [noCore, setNoCore] = useState(false);

  useEffect(() => {
    if (given) return;
    let created: CoreClient | null = null;
    let cancelled = false;
    resolveCoreInfo().then((info) => {
      if (cancelled) return;
      if (!info) {
        setNoCore(true);
        return;
      }
      created = new CoreClient(coreUrl(info));
      created.connect();
      setClient(created);
    });
    return () => {
      cancelled = true;
      created?.close();
    };
  }, [given]);

  const view = useCore(client);
  const muted = view.state === "muted";

  const reply = (approved: boolean) => {
    if (!client || !view.confirm) return;
    client
      .request("confirm.reply", { request_id: view.confirm.request_id, approved })
      .catch(() => undefined);
  };

  return (
    <main className="flex h-full flex-col overflow-hidden bg-[radial-gradient(ellipse_at_top,_#1e1b4b_0%,_#020617_60%)]">
      <header className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          Solana
          {view.fake && (
            <span className="rounded-full bg-fuchsia-500/20 px-2 py-0.5 text-xs font-medium text-fuchsia-300">
              fake
            </span>
          )}
        </div>
        <div
          className="flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-sm text-slate-300"
          data-testid="core-status"
        >
          <span className={`size-2 rounded-full ${statusDot[view.status]}`} />
          core: {noCore ? "не найден" : statusLabels[view.status]}
        </div>
      </header>

      <section className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 overflow-y-auto px-6">
        <Orb state={view.state} />
        <p className="text-xl font-medium" data-testid="assistant-state">
          {stateLabels[view.state]}
        </p>
        <div className="min-h-16 max-w-xl text-center">
          {view.transcript && <p className="text-slate-400">«{view.transcript}»</p>}
          {view.answer && <p className="mt-2 text-lg text-slate-100">{view.answer}</p>}
        </div>

        {view.confirm && (
          <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-white/5 p-4 shadow-xl backdrop-blur">
            <p className="font-medium">{view.confirm.title}</p>
            <p className="mt-1 text-xs text-slate-400">{view.confirm.tool}</p>
            <div className="mt-3 flex gap-2">
              <button
                className="flex-1 rounded-xl bg-emerald-500 px-3 py-2 font-medium text-slate-950 hover:bg-emerald-400"
                onClick={() => reply(true)}
              >
                Да
              </button>
              <button
                className="flex-1 rounded-xl bg-white/10 px-3 py-2 font-medium hover:bg-white/20"
                onClick={() => reply(false)}
              >
                Нет
              </button>
            </div>
          </div>
        )}

        <button
          className="rounded-full bg-white/10 px-4 py-2 text-sm hover:bg-white/20 disabled:opacity-40"
          disabled={view.status !== "connected"}
          onClick={() => client?.request("voice.mute", { muted: !muted }).catch(() => undefined)}
        >
          {muted ? "Включить микрофон" : "Выключить микрофон"}
        </button>
      </section>

      <details className="border-t border-white/5 px-6 py-3 text-xs text-slate-400">
        <summary className="cursor-pointer select-none">События ({view.log.length})</summary>
        <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto font-mono">
          {view.log.map((entry) => (
            <li key={entry.id} className="truncate">
              <span className="text-slate-500">{new Date(entry.time).toLocaleTimeString()}</span>{" "}
              <span className="text-sky-300">{entry.event}</span> {JSON.stringify(entry.params)}
            </li>
          ))}
        </ul>
      </details>
    </main>
  );
}
