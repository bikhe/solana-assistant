import { STT_PROVIDERS, TTS_PROVIDERS } from "../../lib/options";
import { useEffect, useState } from "react";
import { SliderSetting } from "../../components/fields";
import { Row, Section, Select, Toggle } from "../../components/ui";
import { useT } from "../../i18n";
import { listAudioDevices } from "../../lib/audio";
import type { TabProps } from "./tabs";

function DeviceSelect({
  kind,
  value,
  label,
  onChange,
}: {
  kind: MediaDeviceKind;
  value: string | null;
  label: string;
  onChange: (value: string | null) => void;
}) {
  const { t } = useT();
  const [devices, setDevices] = useState<string[]>([]);
  useEffect(() => {
    listAudioDevices(kind).then(setDevices);
  }, [kind]);
  const names = value && !devices.includes(value) ? [value, ...devices] : devices;
  return (
    <Select
      aria-label={label}
      className="max-w-64"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">{t("voice.deviceDefault")}</option>
      {names.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </Select>
  );
}

export function VoiceTab({ settings: s, update }: TabProps) {
  const { t } = useT();
  const v = s.voice;
  return (
    <>
      <Section title={t("voice.wake")}>
        <Row label={t("voice.wakeEnabled")} hint={t("voice.wakeEnabledHint")}>
          <Toggle
            label={t("voice.wakeEnabled")}
            checked={v.wake_word_enabled}
            onChange={(wake_word_enabled) => update({ voice: { wake_word_enabled } })}
          />
        </Row>
        <Row label={t("voice.sensitivity")} hint={t("voice.sensitivityHint")}>
          <SliderSetting
            label={t("voice.sensitivity")}
            value={v.wake_sensitivity}
            min={0}
            max={1}
            step={0.05}
            format={(x) => `${Math.round(x * 100)}%`}
            onSave={(wake_sensitivity) => update({ voice: { wake_sensitivity } })}
          />
        </Row>
      </Section>
      <Section title={t("voice.devices")}>
        <Row label={t("voice.input")}>
          <DeviceSelect
            kind="audioinput"
            label={t("voice.input")}
            value={v.input_device}
            onChange={(input_device) => update({ voice: { input_device } })}
          />
        </Row>
        <Row label={t("voice.output")}>
          <DeviceSelect
            kind="audiooutput"
            label={t("voice.output")}
            value={v.output_device}
            onChange={(output_device) => update({ voice: { output_device } })}
          />
        </Row>
      </Section>
      <Section title={t("voice.engines")}>
        <Row label={t("voice.stt")} hint={t("voice.sttHint")}>
          <Select
            aria-label={t("voice.stt")}
            value={v.stt_provider}
            onChange={(e) => update({ voice: { stt_provider: e.target.value } })}
          >
            {STT_PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {t(`provider.${p}`)}
              </option>
            ))}
          </Select>
        </Row>
        <Row label={t("voice.tts")} hint={t("voice.ttsHint")}>
          <Select
            aria-label={t("voice.tts")}
            value={v.tts_provider}
            onChange={(e) => update({ voice: { tts_provider: e.target.value } })}
          >
            {TTS_PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {t(`provider.${p}`)}
              </option>
            ))}
          </Select>
        </Row>
        <Row label={t("voice.endOfSpeech")} hint={t("voice.endOfSpeechHint")}>
          <SliderSetting
            label={t("voice.endOfSpeech")}
            value={v.end_of_speech_ms}
            min={200}
            max={5000}
            step={100}
            format={(ms) => t("common.seconds", { n: (ms / 1000).toFixed(1) })}
            onSave={(end_of_speech_ms) => update({ voice: { end_of_speech_ms } })}
          />
        </Row>
      </Section>
    </>
  );
}
