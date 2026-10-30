// Typed view of the settings document. The wire type is an open object (protocol `Settings`);
// this mirrors core/solana_core/config/models.py.
import { useCallback, useEffect, useState } from "react";
import type { Language } from "@protocol/ipc";
import { broadcastSettings, onSettingsChanged } from "./platform";
import type { CoreClient } from "./rpc";

export type BrainMode = "cloud" | "local" | "hybrid";

export interface AppSettings {
  general: { language: Language; autostart: boolean; first_run_done: boolean };
  voice: {
    wake_word_enabled: boolean;
    wake_sensitivity: number;
    input_device: string | null;
    output_device: string | null;
    stt_provider: string;
    tts_provider: string;
    tts_voice: string | null;
    end_of_speech_ms: number;
    push_to_talk_hotkey: string;
  };
  brain: {
    mode: BrainMode;
    cloud_provider: string;
    cloud_model: string;
    cloud_base_url: string | null;
    local_provider: string;
    local_model: string;
    local_base_url: string;
  };
  tools: { always_allow: string[]; disabled: string[] };
  mcp: { servers: Record<string, unknown> };
  skills: { disabled: string[] };
}

/** Recursive partial, the shape of a settings.set patch. */
export type SettingsPatch = {
  [K in keyof AppSettings]?: Partial<AppSettings[K]>;
};

export interface SettingsHandle {
  settings: AppSettings | null;
  /** Deep-merges the patch on the core and shares the result with the other windows. */
  update: (patch: SettingsPatch) => Promise<AppSettings | null>;
  error: string | null;
}

/** Loads settings once connected and keeps them in sync across windows. */
export function useSettings(client: CoreClient | null, connected: boolean): SettingsHandle {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !connected) return;
    let cancelled = false;
    client
      .request("settings.get")
      .then((r) => !cancelled && setSettings(r.settings as unknown as AppSettings))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [client, connected]);

  useEffect(() => onSettingsChanged((s) => setSettings(s as AppSettings)), []);

  const update = useCallback(
    async (patch: SettingsPatch) => {
      if (!client) return null;
      try {
        const r = await client.request("settings.set", { patch });
        const next = r.settings as unknown as AppSettings;
        setSettings(next);
        setError(null);
        broadcastSettings(next);
        return next;
      } catch (e) {
        setError((e as Error).message);
        return null;
      }
    },
    [client],
  );

  return { settings, update, error };
}
