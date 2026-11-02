import { useT } from "../i18n";
import { useApp } from "../lib/appContext";

const dot = {
  connected: "bg-emerald-400",
  connecting: "bg-amber-400 animate-pulse",
  disconnected: "bg-rose-500",
};

/** Core connection status, with a "fake" badge in demo mode. */
export function StatusPill() {
  const { core, noCore } = useApp();
  const { t } = useT();
  return (
    <div className="flex items-center gap-1.5">
      {core.fake && (
        <span className="rounded-full bg-fuchsia-500/20 px-2 py-0.5 text-[11px] font-medium text-fuchsia-300">
          fake
        </span>
      )}
      <div
        className="flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-xs text-slate-300"
        data-testid="core-status"
        title={t("status.title")}
      >
        <span className={`size-2 rounded-full ${dot[core.status]}`} />
        {noCore ? t("status.notFound") : t(`status.${core.status}`)}
      </div>
    </div>
  );
}
