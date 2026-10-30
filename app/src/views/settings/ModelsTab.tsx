import { CLOUD_PROVIDERS, LOCAL_PROVIDERS } from "../../lib/options";
import { TextSetting } from "../../components/fields";
import { ModeCards } from "../../components/ModeCards";
import { ModelList } from "../../components/ModelList";
import { Row, Section, Select } from "../../components/ui";
import { useT } from "../../i18n";
import type { TabProps } from "./tabs";

export function ModelsTab({ settings: s, update }: TabProps) {
  const { t } = useT();
  const b = s.brain;
  return (
    <>
      <div className="mb-5">
        <ModeCards value={b.mode} onChange={(mode) => update({ brain: { mode } })} />
      </div>
      {b.mode !== "local" && (
        <Section title={t("models.cloud")}>
          <Row label={t("models.provider")}>
            <Select
              aria-label={t("models.cloud")}
              value={b.cloud_provider}
              onChange={(e) => update({ brain: { cloud_provider: e.target.value } })}
            >
              {CLOUD_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {t(`provider.${p}`)}
                </option>
              ))}
            </Select>
          </Row>
          <Row label={t("models.model")}>
            <TextSetting
              value={b.cloud_model}
              onSave={(cloud_model) => update({ brain: { cloud_model } })}
            />
          </Row>
          <Row label={t("models.baseUrl")} hint={t("models.baseUrlHint")}>
            <TextSetting
              value={b.cloud_base_url ?? ""}
              placeholder="https://…/v1"
              onSave={(url) => update({ brain: { cloud_base_url: url || null } })}
            />
          </Row>
        </Section>
      )}
      {b.mode !== "cloud" && (
        <Section title={t("models.local")}>
          <Row label={t("models.provider")} hint={t("models.localHint")}>
            <Select
              aria-label={t("models.local")}
              value={b.local_provider}
              onChange={(e) => update({ brain: { local_provider: e.target.value } })}
            >
              {LOCAL_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {t(`provider.${p}`)}
                </option>
              ))}
            </Select>
          </Row>
          <Row label={t("models.model")}>
            <TextSetting
              value={b.local_model}
              onSave={(local_model) => update({ brain: { local_model } })}
            />
          </Row>
          <Row label={t("models.baseUrl")}>
            <TextSetting
              value={b.local_base_url}
              onSave={(local_base_url) => update({ brain: { local_base_url } })}
            />
          </Row>
        </Section>
      )}
      <Section title={t("models.downloads")}>
        <ModelList />
      </Section>
    </>
  );
}
