import type { AppSettings, SettingsPatch } from "../../lib/settings";

export interface TabProps {
  settings: AppSettings;
  update: (patch: SettingsPatch) => Promise<AppSettings | null>;
}
