// Chat window: typing as an alternative to the voice, plus the history of both.
import { AnimatePresence, motion } from "motion/react";
import {
  CircleAlert,
  Check,
  Loader2,
  Mic,
  MicOff,
  SendHorizontal,
  Settings,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useReducer, useRef, useState, type FormEvent } from "react";
import { ConfirmCard } from "../components/ConfirmCard";
import { Orb } from "../components/Orb";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/ui";
import { useT } from "../i18n";
import { replyConfirm, setMuted, useApp } from "../lib/appContext";
import { chatReducer, loadHistory, saveHistory, type ChatItem } from "../lib/chatHistory";
import { isUnavailable } from "../lib/pending";
import { showWindow } from "../lib/platform";

let localSeq = 0;
function stamp() {
  return { id: `local-${++localSeq}-${Date.now()}`, time: Date.now() };
}

function Message({ item }: { item: ChatItem }) {
  const { t } = useT();
  switch (item.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div className="max-w-[80%] rounded-2xl rounded-br-md bg-gradient-to-br from-amber-300 to-orange-500 px-3.5 py-2 text-[15px] text-slate-950 shadow-lg shadow-orange-500/10">
            {item.via === "voice" && (
              <Mic className="mr-1 inline size-3.5 -translate-y-px opacity-60" />
            )}
            {item.text}
          </div>
        </div>
      );
    case "assistant":
      return (
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-white/[0.06] px-3.5 py-2 text-[15px] whitespace-pre-wrap text-slate-100 ring-1 ring-white/[0.06]">
            {item.text}
            {!item.done && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-orange-300 align-middle" />
            )}
            {item.interrupted && (
              <span className="ml-1 text-xs text-slate-500">{t("chat.interrupted")}</span>
            )}
          </div>
        </div>
      );
    case "tool": {
      const Icon = item.status === "running" ? Loader2 : item.status === "ok" ? Check : X;
      return (
        <div className="flex justify-start pl-1">
          <div className="flex items-center gap-1.5 rounded-full bg-white/[0.04] px-2.5 py-1 text-xs text-slate-400 ring-1 ring-white/[0.06]">
            <Wrench className="size-3" />
            <code>{item.tool}</code>
            {item.summary && <span className="text-slate-300">· {item.summary}</span>}
            <Icon
              className={`size-3.5 ${item.status === "running" ? "animate-spin" : item.status === "ok" ? "text-emerald-400" : "text-rose-400"}`}
            />
          </div>
        </div>
      );
    }
    case "error":
      return (
        <div className="flex items-center justify-center gap-1.5 text-xs text-rose-300">
          <CircleAlert className="size-3.5" />
          {item.message}
        </div>
      );
  }
}

export function Chat() {
  const app = useApp();
  const { client, core } = app;
  const { t, lang } = useT();
  const [items, dispatch] = useReducer(chatReducer, undefined, () => loadHistory());
  const [draft, setDraft] = useState("");
  const listEnd = useRef<HTMLDivElement>(null);
  const connected = core.status === "connected";
  const muted = core.state === "muted";

  useEffect(() => {
    if (!client) return;
    return client.onAny((event, params) =>
      dispatch({ type: "event", event, params, time: Date.now() }),
    );
  }, [client]);

  useEffect(() => {
    saveHistory(items);
  }, [items]);
  useEffect(() => {
    listEnd.current?.scrollIntoView?.({ block: "end" });
  }, [items, core.confirm]);

  const send = (text: string) => {
    const clean = text.trim();
    if (!clean || !client) return;
    const { id, time } = stamp();
    dispatch({ type: "sent", id, text: clean, time });
    setDraft("");
    client.request("chat.send", { text: clean, language: lang }).catch((e: unknown) =>
      dispatch({
        type: "failed",
        id,
        message: isUnavailable(e) ? t("chat.unavailable") : t("chat.failed"),
        time: Date.now(),
      }),
    );
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(draft);
  };

  const suggestions = [t("chat.suggest1"), t("chat.suggest2"), t("chat.suggest3")];

  return (
    <main className="flex h-full flex-col bg-[radial-gradient(ellipse_at_top,_#1e1b4b_0%,_#020617_65%)]">
      <header className="flex items-center gap-2 border-b border-white/5 px-3 py-2">
        <Orb state={core.state} size="sm" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 font-semibold tracking-tight">Solana</div>
          <div className="truncate text-xs text-slate-400" data-testid="assistant-state">
            {t(`state.${core.state}`)}
          </div>
        </div>
        <StatusPill />
        <Button
          variant="subtle"
          className="!px-2"
          title={t("chat.clear")}
          aria-label={t("chat.clear")}
          onClick={() => dispatch({ type: "clear" })}
          disabled={items.length === 0}
        >
          <Trash2 className="size-4" />
        </Button>
        <Button
          variant="subtle"
          className="!px-2"
          title={t("tray.settings")}
          aria-label={t("tray.settings")}
          onClick={() => showWindow("settings").catch(() => undefined)}
        >
          <Settings className="size-4" />
        </Button>
      </header>

      <section
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4"
        data-testid="chat-list"
      >
        {items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <Orb state={core.state} size="md" />
            <div>
              <p className="text-lg font-medium">{t("chat.emptyTitle")}</p>
              <p className="mt-1 text-sm text-slate-400">{t("chat.emptyHint")}</p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  disabled={!connected}
                  onClick={() => send(s)}
                  className="rounded-full bg-white/5 px-3 py-1.5 text-sm text-slate-200 ring-1 ring-white/10 transition hover:bg-white/10 disabled:opacity-40"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {items.map((item) => (
              <motion.div
                key={`${item.kind}-${item.id}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <Message item={item} />
              </motion.div>
            ))}
          </AnimatePresence>
        )}
        {core.confirm && (
          <ConfirmCard
            confirm={core.confirm}
            since={core.confirmSince}
            onReply={(approved, always) =>
              core.confirm && replyConfirm(app, core.confirm, approved, always)
            }
          />
        )}
        <div ref={listEnd} />
      </section>

      <form onSubmit={onSubmit} className="flex items-center gap-2 border-t border-white/5 p-3">
        <Button
          variant={muted ? "danger" : "ghost"}
          className="!rounded-full !p-2.5"
          disabled={!connected}
          title={muted ? t("tray.unmute") : t("tray.mute")}
          aria-label={muted ? t("tray.unmute") : t("tray.mute")}
          onClick={() => setMuted(client, !muted)}
        >
          {muted ? <MicOff className="size-4" /> : <Mic className="size-4" />}
        </Button>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("chat.placeholder")}
          aria-label={t("chat.placeholder")}
          className="min-w-0 flex-1 rounded-full bg-slate-900/80 px-4 py-2.5 text-[15px] ring-1 ring-white/10 outline-none placeholder:text-slate-500 focus:ring-2 focus:ring-amber-400/60"
        />
        <Button
          type="submit"
          variant="primary"
          className="!rounded-full !p-2.5"
          disabled={!connected || !draft.trim()}
          aria-label={t("chat.send")}
        >
          <SendHorizontal className="size-4" />
        </Button>
      </form>
    </main>
  );
}
