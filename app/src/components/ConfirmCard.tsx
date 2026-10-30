import type { ConfirmRequestEvent } from "@protocol/ipc";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useT } from "../i18n";
import { Badge, Button } from "./ui";

export function ConfirmCard({
  confirm,
  since,
  onReply,
}: {
  confirm: ConfirmRequestEvent;
  /** When the request arrived (ms); drives the countdown bar. */
  since: number;
  onReply: (approved: boolean, always?: boolean) => void;
}) {
  const { t } = useT();
  const dangerous = confirm.risk === "dangerous";
  // A card that mounts late (e.g. the chat window opened mid-request) starts its bar part-way.
  const [shownAt] = useState(() => Date.now());
  const elapsed = Math.max(0, (shownAt - since) / 1000);
  const Icon = dangerous ? ShieldAlert : ShieldCheck;
  return (
    <div
      className="relative w-full overflow-hidden rounded-2xl bg-slate-900/90 p-4 shadow-2xl ring-1 ring-white/10 backdrop-blur-xl"
      data-testid="confirm-card"
    >
      <div className="flex items-start gap-3">
        <div
          className={`mt-0.5 rounded-xl p-2 ${dangerous ? "bg-rose-500/15 text-rose-300" : "bg-amber-400/15 text-amber-300"}`}
        >
          <Icon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-slate-50">{confirm.title}</p>
          {confirm.details && <p className="mt-1 text-sm text-slate-400">{confirm.details}</p>}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <code className="rounded bg-white/5 px-1.5 py-0.5 text-[11px] text-slate-400">
              {confirm.tool}
            </code>
            {dangerous && <Badge tone="bad">{t("confirm.dangerous")}</Badge>}
          </div>
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <Button variant="primary" className="flex-1" onClick={() => onReply(true)}>
          {t("confirm.yes")}
        </Button>
        <Button className="flex-1" onClick={() => onReply(false)}>
          {t("confirm.no")}
        </Button>
        {!dangerous && (
          <Button variant="subtle" onClick={() => onReply(true, true)}>
            {t("confirm.always")}
          </Button>
        )}
      </div>
      <p className="mt-2 text-center text-[11px] text-slate-500">
        {confirm.voice_allowed ? t("confirm.voiceHint") : t("confirm.clickOnly")}
      </p>
      {confirm.timeout_s ? (
        <div
          key={confirm.request_id}
          className="animate-countdown absolute bottom-0 left-0 h-0.5 w-full origin-left bg-gradient-to-r from-amber-300 to-orange-500"
          style={{
            animationDuration: `${confirm.timeout_s}s`,
            animationDelay: `-${Math.min(elapsed, confirm.timeout_s)}s`,
          }}
        />
      ) : null}
    </div>
  );
}
