// Floating strip at the top of the screen. Transparent and click-through while idle.
import { AnimatePresence, motion } from "motion/react";
import { MicOff, TriangleAlert, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { ConfirmCard } from "../components/ConfirmCard";
import { Orb } from "../components/Orb";
import { useT } from "../i18n";
import { replyConfirm, useApp } from "../lib/appContext";
import { inTauri, setClickThrough } from "../lib/platform";
import { useShellDuties } from "./useShellDuties";

/** How long the muted / error strip stays before it hides itself. */
const FLASH_MS = 2500;

/** Equalizer bars shown while the assistant speaks. */
function Bars() {
  return (
    <div className="flex h-4 items-end gap-0.5" aria-hidden>
      {[0, 0.15, 0.3, 0.1].map((delay, i) => (
        <span
          key={i}
          className="animate-bar h-full w-0.5 origin-bottom rounded-full bg-orange-300"
          style={{ animationDelay: `${delay}s` }}
        />
      ))}
    </div>
  );
}

export function Overlay() {
  const app = useApp();
  const { core } = app;
  const { t } = useT();
  useShellDuties(app);

  // The real window is transparent; a browser preview keeps the dark page behind it.
  useEffect(() => {
    if (!inTauri()) return;
    document.documentElement.classList.add("overlay");
    return () => document.documentElement.classList.remove("overlay");
  }, []);

  // Muted and error show briefly, then the strip gets out of the way.
  const [flash, setFlash] = useState(false);
  const [seen, setSeen] = useState({ state: core.state, error: core.error });
  if (seen.state !== core.state || seen.error !== core.error) {
    setSeen({ state: core.state, error: core.error });
    setFlash(core.state === "muted" || core.error !== null);
  }
  useEffect(() => {
    if (!flash) return;
    const timer = setTimeout(() => setFlash(false), FLASH_MS);
    return () => clearTimeout(timer);
  }, [flash, seen]);

  const active = core.state !== "idle" && core.state !== "muted" && core.state !== "error";
  const showStrip = active || flash;
  const confirm = core.confirm;

  // Only the confirmation card needs the mouse; otherwise clicks go to the windows below.
  useEffect(() => {
    setClickThrough(!confirm).catch(() => undefined);
  }, [confirm]);

  let text: string;
  let dim = false;
  if (core.error && (core.state === "error" || flash)) text = core.error.message;
  else if (core.state === "muted") text = t("state.muted");
  else if (core.state === "speaking" && core.answer) text = core.answer;
  else if ((core.state === "listening" || core.state === "thinking") && core.transcript) {
    text = core.transcript;
    dim = core.state === "thinking";
  } else text = t(`state.${core.state}`);

  return (
    <main
      className="flex h-full flex-col items-center gap-2 px-5 pt-1 select-none"
      data-testid="overlay"
    >
      <AnimatePresence>
        {(showStrip || confirm) && (
          <motion.div
            key="strip"
            initial={{ opacity: 0, y: -24, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -24, scale: 0.92 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
            className="flex max-w-full min-w-64 items-center gap-3 rounded-full bg-slate-950/85 py-1.5 pr-5 pl-1.5 shadow-2xl ring-1 ring-white/10 backdrop-blur-xl"
            data-testid="overlay-strip"
          >
            <Orb state={core.state} size="sm" />
            {core.state === "muted" && <MicOff className="size-4 shrink-0 text-slate-400" />}
            {core.error && core.state === "error" && (
              <TriangleAlert className="size-4 shrink-0 text-rose-300" />
            )}
            <motion.p
              key={core.state}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className={`line-clamp-2 min-w-0 text-[15px] leading-snug ${dim ? "text-slate-400" : "text-slate-50"}`}
              data-testid="overlay-text"
            >
              {text}
            </motion.p>
            {core.tool && (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">
                <Wrench className="size-3" />
                {core.tool.tool}
              </span>
            )}
            {core.state === "speaking" && <Bars />}
          </motion.div>
        )}
        {confirm && (
          <motion.div
            key={confirm.request_id}
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            className="w-full max-w-md"
          >
            <ConfirmCard
              confirm={confirm}
              since={core.confirmSince}
              onReply={(approved, always) => replyConfirm(app, confirm, approved, always)}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
