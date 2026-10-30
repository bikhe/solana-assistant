// Downloadable local models with live progress from download.progress events.
import { formatBytes } from "../lib/format";
import type { ModelInfo } from "@protocol/ipc";
import { Check, Download } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { useApp } from "../lib/appContext";
import { Badge, Button } from "./ui";

interface Progress {
  done: number;
  total: number | null;
  error?: string;
}

export function ModelList({ kinds }: { kinds?: ModelInfo["kind"][] }) {
  const { client, core } = useApp();
  const { t } = useT();
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const connected = core.status === "connected";

  useEffect(() => {
    if (!client || !connected) return;
    client
      .request("models.list")
      .then((r) => setModels(r.models))
      .catch(() => setModels([]));
    return client.on("download.progress", (e) => {
      setProgress((p) => ({
        ...p,
        [e.model_id]: { done: e.downloaded_bytes, total: e.total_bytes, error: e.error },
      }));
      if (e.done && !e.error) {
        setModels(
          (ms) => ms?.map((m) => (m.id === e.model_id ? { ...m, installed: true } : m)) ?? ms,
        );
      }
    });
  }, [client, connected]);

  const shown = models?.filter((m) => !kinds || kinds.includes(m.kind));
  if (!shown) return <p className="py-3 text-sm text-slate-400">{t("common.loading")}</p>;
  if (shown.length === 0) return <p className="py-3 text-sm text-slate-400">{t("models.none")}</p>;

  return (
    <ul className="divide-y divide-white/5" data-testid="model-list">
      {shown.map((m) => {
        const p = progress[m.id];
        const downloading = p && !m.installed && !p.error;
        const share = p?.total ? Math.min(1, p.done / p.total) : 0;
        return (
          <li key={m.id} className="flex items-center gap-3 py-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-medium">
                {m.name}
                <Badge>{t(`models.kind.${m.kind}`)}</Badge>
              </div>
              <div className="mt-0.5 text-xs text-slate-400">
                {formatBytes(m.size_bytes)}
                {p?.error && <span className="ml-2 text-rose-300">{p.error}</span>}
              </div>
              {downloading && (
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-amber-300 to-orange-500 transition-[width]"
                    style={{ width: `${Math.round(share * 100)}%` }}
                  />
                </div>
              )}
            </div>
            {m.installed ? (
              <Badge tone="good">
                <Check className="mr-0.5 inline size-3" />
                {t("models.installed")}
              </Badge>
            ) : (
              <Button
                disabled={!connected || !!downloading}
                onClick={() => {
                  setProgress((pr) => ({ ...pr, [m.id]: { done: 0, total: m.size_bytes } }));
                  client?.request("models.download", { model_id: m.id }).catch((e: Error) =>
                    setProgress((pr) => ({
                      ...pr,
                      [m.id]: { done: 0, total: null, error: e.message },
                    })),
                  );
                }}
              >
                <Download className="size-4" />
                {downloading ? `${Math.round(share * 100)}%` : t("models.download")}
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
