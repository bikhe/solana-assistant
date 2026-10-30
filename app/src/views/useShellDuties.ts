// App-wide side effects. They run in the overlay window, which lives as long as the app.
import { useEffect, useRef } from "react";
import { useT } from "../i18n";
import { setMuted, type AppContextValue } from "../lib/appContext";
import { requestPending } from "../lib/pending";
import {
  onTrayAction,
  registerHoldShortcut,
  showWindow,
  syncAutostart,
  updateTray,
} from "../lib/platform";

export function useShellDuties({ client, core, settings }: AppContextValue): void {
  const { t, lang } = useT();
  const muted = core.state === "muted";
  const s = settings.settings;

  // Tray: labels follow the UI language, the check mark follows the core.
  useEffect(() => {
    updateTray(
      {
        mute: t("tray.mute"),
        chat: t("tray.chat"),
        settings: t("tray.settings"),
        quit: t("tray.quit"),
      },
      muted,
    ).catch(() => undefined);
    // t changes with lang only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, muted]);

  const mutedRef = useRef(muted);
  useEffect(() => {
    mutedRef.current = muted;
  }, [muted]);
  useEffect(
    () =>
      onTrayAction((action) => {
        if (action === "mute") setMuted(client, !mutedRef.current);
      }),
    [client],
  );

  // First run: open the wizard once settings say it has not been completed.
  const wizardShown = useRef(false);
  useEffect(() => {
    if (s && !s.general.first_run_done && !wizardShown.current) {
      wizardShown.current = true;
      showWindow("wizard").catch(() => undefined);
    }
  }, [s]);

  // Start with the OS when the user asks for it.
  const autostart = s?.general.autostart;
  useEffect(() => {
    if (autostart !== undefined) syncAutostart(autostart).catch(() => undefined);
  }, [autostart]);

  // Hold-to-talk: press starts listening, release ends the phrase.
  const hotkey = s?.voice.push_to_talk_hotkey;
  useEffect(() => {
    if (!client || !hotkey) return;
    const listen = (active: boolean) =>
      requestPending(client, "voice.listen", { active }).catch(() => undefined);
    let off: (() => void) | null = null;
    let cancelled = false;
    registerHoldShortcut(
      hotkey,
      () => listen(true),
      () => listen(false),
    )
      .then((unregister) => (cancelled ? unregister() : (off = unregister)))
      .catch((e) => console.warn(`hotkey ${hotkey} not registered:`, e));
    return () => {
      cancelled = true;
      off?.();
    };
  }, [client, hotkey]);
}
