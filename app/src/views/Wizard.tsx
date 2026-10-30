// First-run wizard: language, microphone, brain mode, keys or models, wake word check.
import { STEPS } from "../lib/options";
import type { Language } from "@protocol/ipc";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronLeft, MicOff } from "lucide-react";
import { useEffect, useState } from "react";
import { KeyList } from "../components/KeyList";
import { ModeCards } from "../components/ModeCards";
import { ModelList } from "../components/ModelList";
import { Orb } from "../components/Orb";
import { Button } from "../components/ui";
import { useT } from "../i18n";
import { useApp } from "../lib/appContext";
import { watchMicLevel } from "../lib/audio";
import { hideWindow } from "../lib/platform";

function LanguageStep() {
  const { settings } = useApp();
  const current = settings.settings?.general.language ?? "ru";
  const options: { id: Language; label: string; hello: string }[] = [
    { id: "ru", label: "Русский", hello: "Привет! Я Солана." },
    { id: "en", label: "English", hello: "Hi! I'm Solana." },
  ];
  return (
    <div className="grid grid-cols-2 gap-3">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={current === o.id}
          onClick={() => settings.update({ general: { language: o.id } })}
          className={`rounded-2xl p-5 text-left transition ${
            current === o.id
              ? "bg-gradient-to-br from-amber-300/20 to-orange-500/10 ring-2 ring-amber-400/70"
              : "bg-white/[0.03] ring-1 ring-white/10 hover:bg-white/[0.06]"
          }`}
        >
          <div className="text-lg font-semibold">{o.label}</div>
          <div className="mt-1 text-sm text-slate-400">{o.hello}</div>
        </button>
      ))}
    </div>
  );
}

function MicStep() {
  const { t } = useT();
  const [level, setLevel] = useState(0);
  const [failed, setFailed] = useState(false);
  const [heard, setHeard] = useState(false);
  useEffect(() => {
    let stop: (() => void) | null = null;
    let cancelled = false;
    watchMicLevel((l) => {
      setLevel(l);
      if (l > 0.2) setHeard(true);
    })
      .then((s) => (cancelled ? s() : (stop = s)))
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      stop?.();
    };
  }, []);

  if (failed) {
    return (
      <div className="flex flex-col items-center gap-3 py-6 text-center">
        <MicOff className="size-8 text-slate-400" />
        <p className="max-w-sm text-sm text-slate-400">{t("wizard.micUnavailable")}</p>
      </div>
    );
  }
  const bars = 24;
  return (
    <div className="flex flex-col items-center gap-5 py-4">
      <div className="flex h-20 items-end gap-1" data-testid="mic-meter">
        {Array.from({ length: bars }, (_, i) => {
          const lit = i / bars < level * 1.4;
          return (
            <span
              key={i}
              className={`w-2 rounded-full transition-all duration-75 ${lit ? "bg-gradient-to-t from-amber-300 to-orange-500" : "bg-white/10"}`}
              style={{ height: `${20 + (i / bars) * 80}%` }}
            />
          );
        })}
      </div>
      <p className={`text-sm ${heard ? "text-emerald-300" : "text-slate-400"}`}>
        {heard ? t("wizard.micHeard") : t("wizard.micSay")}
      </p>
    </div>
  );
}

function SetupStep() {
  const { settings } = useApp();
  const { t } = useT();
  const mode = settings.settings?.brain.mode ?? "local";
  return (
    <div className="space-y-5">
      {mode !== "local" && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">{t("wizard.keysTitle")}</h3>
          <p className="mb-2 text-xs text-slate-400">{t("wizard.keysHint")}</p>
          <div className="rounded-2xl bg-white/[0.03] px-4 ring-1 ring-white/[0.06]">
            <KeyList only={["anthropic", "openai"]} />
          </div>
        </div>
      )}
      {mode !== "cloud" && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">{t("wizard.modelsTitle")}</h3>
          <p className="mb-2 text-xs text-slate-400">{t("wizard.modelsHint")}</p>
          <div className="rounded-2xl bg-white/[0.03] px-4 ring-1 ring-white/[0.06]">
            <ModelList />
          </div>
        </div>
      )}
    </div>
  );
}

function WakeStep({ heard }: { heard: boolean }) {
  const { core } = useApp();
  const { t } = useT();
  return (
    <div className="flex flex-col items-center gap-4 py-2 text-center">
      <Orb state={heard ? "wake" : core.state} />
      <p
        className={`text-lg font-medium ${heard ? "text-emerald-300" : ""}`}
        data-testid="wake-result"
      >
        {heard ? (
          <>
            <Check className="mr-1 inline size-5" />
            {t("wizard.wakeHeard")}
          </>
        ) : (
          t("wizard.wakeSay")
        )}
      </p>
    </div>
  );
}

export function Wizard() {
  const { client, core, settings } = useApp();
  const { t } = useT();
  const [index, setIndex] = useState(0);
  const [wakeHeard, setWakeHeard] = useState(false);
  const step = STEPS[index]!;
  const last = index === STEPS.length - 1;

  // The wake word check passes on the first state change caused by the wake word.
  useEffect(() => {
    if (!client || step !== "wake") return;
    return client.on("state", (e) => {
      if (e.reason === "wake_word") setWakeHeard(true);
    });
  }, [client, step]);

  const finish = async () => {
    await settings.update({ general: { first_run_done: true } });
    await hideWindow().catch(() => undefined);
  };

  return (
    <main className="flex h-full flex-col bg-[radial-gradient(ellipse_at_top,_#1e1b4b_0%,_#020617_65%)] p-8">
      <div
        className="mb-6 flex items-center gap-1.5"
        aria-label={t("wizard.progress", { n: index + 1, total: STEPS.length })}
      >
        {STEPS.map((s, i) => (
          <span
            key={s}
            className={`h-1.5 flex-1 rounded-full transition-colors ${i <= index ? "bg-gradient-to-r from-amber-300 to-orange-500" : "bg-white/10"}`}
          />
        ))}
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.2 }}
          className="min-h-0 flex-1 overflow-y-auto"
          data-testid={`wizard-${step}`}
        >
          <h1 className="text-2xl font-semibold tracking-tight">{t(`wizard.${step}Title`)}</h1>
          <p className="mt-1 mb-6 text-sm text-slate-400">{t(`wizard.${step}Hint`)}</p>
          {step === "language" && <LanguageStep />}
          {step === "mic" && <MicStep />}
          {step === "mode" && settings.settings && (
            <ModeCards
              value={settings.settings.brain.mode}
              onChange={(mode) => settings.update({ brain: { mode } })}
            />
          )}
          {step === "setup" && <SetupStep />}
          {step === "wake" && <WakeStep heard={wakeHeard} />}
        </motion.div>
      </AnimatePresence>
      <footer className="mt-6 flex items-center gap-2">
        {index > 0 && (
          <Button variant="subtle" onClick={() => setIndex(index - 1)}>
            <ChevronLeft className="size-4" />
            {t("common.back")}
          </Button>
        )}
        <div className="flex-1" />
        {core.status !== "connected" && (
          <span className="text-xs text-slate-500">{t("settings.waiting")}</span>
        )}
        {last ? (
          <Button variant="primary" onClick={finish} disabled={!settings.settings}>
            {wakeHeard ? t("wizard.finish") : t("wizard.finishSkip")}
          </Button>
        ) : (
          <Button
            variant="primary"
            onClick={() => setIndex(index + 1)}
            disabled={!settings.settings}
          >
            {t("common.next")}
          </Button>
        )}
      </footer>
    </main>
  );
}
