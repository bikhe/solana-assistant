// API keys go straight to the OS keyring through the core; the app never reads them back.
import { KEY_SLOTS } from "../lib/options";
import { Check, KeyRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { useApp } from "../lib/appContext";
import { isUnavailable, requestPending } from "../lib/pending";
import { Badge, Button, Notice, TextField } from "./ui";

export function KeyList({ only }: { only?: string[] }) {
  const { client, core } = useApp();
  const { t } = useT();
  const [status, setStatus] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [unavailable, setUnavailable] = useState(false);
  const connected = core.status === "connected";
  const slots = KEY_SLOTS.filter((s) => !only || only.includes(s.id));

  useEffect(() => {
    if (!client || !connected) return;
    requestPending(client, "secrets.status", { names: KEY_SLOTS.map((s) => s.id) })
      .then((r) => setStatus(r.set))
      .catch((e) => isUnavailable(e) && setUnavailable(true));
  }, [client, connected]);

  const save = (id: string) => {
    if (!client) return;
    const value = drafts[id] ?? "";
    requestPending(client, "secrets.set", { name: id, value })
      .then(() => {
        setStatus((s) => ({ ...s, [id]: value !== "" }));
        setDrafts((d) => ({ ...d, [id]: "" }));
      })
      .catch((e) => isUnavailable(e) && setUnavailable(true));
  };

  return (
    <div>
      {unavailable && <Notice>{t("keys.unavailable")}</Notice>}
      <ul className="divide-y divide-white/5">
        {slots.map((slot) => (
          <li key={slot.id} className="py-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <KeyRound className="size-4 text-slate-400" />
              {t(slot.label)}
              {status[slot.id] && (
                <Badge tone="good">
                  <Check className="mr-0.5 inline size-3" />
                  {t("keys.saved")}
                </Badge>
              )}
            </div>
            <div className="mt-0.5 mb-2 text-xs text-slate-400">{t(slot.hint)}</div>
            <div className="flex gap-2">
              <TextField
                type="password"
                autoComplete="off"
                className="flex-1"
                aria-label={t(slot.label)}
                placeholder={status[slot.id] ? "••••••••••••" : t("keys.placeholder")}
                value={drafts[slot.id] ?? ""}
                disabled={unavailable || !connected}
                onChange={(e) => setDrafts((d) => ({ ...d, [slot.id]: e.target.value }))}
                onKeyDown={(e) => e.key === "Enter" && save(slot.id)}
              />
              <Button
                disabled={unavailable || !connected || !drafts[slot.id]}
                onClick={() => save(slot.id)}
              >
                {t("common.save")}
              </Button>
              {status[slot.id] && (
                <Button
                  variant="subtle"
                  disabled={unavailable}
                  onClick={() => {
                    setDrafts((d) => ({ ...d, [slot.id]: "" }));
                    requestPending(client!, "secrets.set", { name: slot.id, value: "" })
                      .then(() => setStatus((s) => ({ ...s, [slot.id]: false })))
                      .catch(() => undefined);
                  }}
                >
                  {t("common.remove")}
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
