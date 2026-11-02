import type { Language } from "@protocol/ipc";
import { HotkeyField } from "../../components/fields";
import { Button, Row, Section, Select, Toggle } from "../../components/ui";
import { useT } from "../../i18n";
import { showWindow } from "../../lib/platform";
import type { TabProps } from "./tabs";

export function GeneralTab({ settings: s, update }: TabProps) {
  const { t } = useT();
  return (
    <>
      <Section>
        <Row label={t("general.language")} hint={t("general.languageHint")}>
          <Select
            aria-label={t("general.language")}
            value={s.general.language}
            onChange={(e) => update({ general: { language: e.target.value as Language } })}
          >
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </Select>
        </Row>
        <Row label={t("general.autostart")} hint={t("general.autostartHint")}>
          <Toggle
            label={t("general.autostart")}
            checked={s.general.autostart}
            onChange={(autostart) => update({ general: { autostart } })}
          />
        </Row>
        <Row label={t("general.hotkey")} hint={t("general.hotkeyHint")}>
          <HotkeyField
            value={s.voice.push_to_talk_hotkey}
            onSave={(push_to_talk_hotkey) => update({ voice: { push_to_talk_hotkey } })}
          />
        </Row>
      </Section>
      <Section>
        <Row label={t("general.wizard")} hint={t("general.wizardHint")}>
          <Button onClick={() => showWindow("wizard").catch(() => undefined)}>
            {t("general.wizardOpen")}
          </Button>
        </Row>
      </Section>
    </>
  );
}
