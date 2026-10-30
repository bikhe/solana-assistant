import { Cloud, Cpu, Sparkles } from "lucide-react";
import { useT } from "../i18n";
import type { BrainMode } from "../lib/settings";

const modes: { id: BrainMode; icon: typeof Cloud }[] = [
  { id: "local", icon: Cpu },
  { id: "hybrid", icon: Sparkles },
  { id: "cloud", icon: Cloud },
];

/** Cloud / local / hybrid picker used by settings and the wizard. */
export function ModeCards({
  value,
  onChange,
}: {
  value: BrainMode;
  onChange: (mode: BrainMode) => void;
}) {
  const { t } = useT();
  return (
    <div className="grid grid-cols-3 gap-3" role="radiogroup" aria-label={t("models.mode")}>
      {modes.map(({ id, icon: Icon }) => {
        const selected = value === id;
        return (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(id)}
            className={`rounded-2xl p-4 text-left transition ${
              selected
                ? "bg-gradient-to-br from-amber-300/20 to-orange-500/10 ring-2 ring-amber-400/70"
                : "bg-white/[0.03] ring-1 ring-white/10 hover:bg-white/[0.06]"
            }`}
          >
            <Icon className={`size-5 ${selected ? "text-amber-300" : "text-slate-400"}`} />
            <div className="mt-2 text-sm font-semibold">{t(`mode.${id}`)}</div>
            <div className="mt-1 text-xs leading-relaxed text-slate-400">{t(`mode.${id}Hint`)}</div>
          </button>
        );
      })}
    </div>
  );
}
