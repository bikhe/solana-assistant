// Settings fields that save themselves: text on blur or Enter, sliders on release.
import { useEffect, useState } from "react";
import { acceleratorFromEvent, formatAccelerator } from "../lib/accelerator";
import { useT } from "../i18n";
import { Button, Slider, TextField } from "./ui";

export function TextSetting({
  value,
  onSave,
  placeholder,
  className = "w-64",
}: {
  value: string;
  onSave: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [text, setText] = useState(value);
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    setSynced(value);
    setText(value);
  }
  const commit = () => text !== value && onSave(text.trim());
  return (
    <TextField
      className={className}
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
    />
  );
}

export function SliderSetting({
  value,
  onSave,
  min,
  max,
  step,
  format,
  label,
}: {
  value: number;
  onSave: (value: number) => void;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  label: string;
}) {
  const [current, setCurrent] = useState(value);
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    setSynced(value);
    setCurrent(value);
  }
  const commit = () => current !== value && onSave(current);
  return (
    <>
      <span className="w-14 text-right text-xs text-slate-400 tabular-nums">{format(current)}</span>
      <Slider
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={current}
        onChange={(e) => setCurrent(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
    </>
  );
}

/** Click, then press the new shortcut. Esc cancels. */
export function HotkeyField({
  value,
  onSave,
}: {
  value: string;
  onSave: (accelerator: string) => void;
}) {
  const { t } = useT();
  const [recording, setRecording] = useState(false);

  useEffect(() => {
    if (!recording) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      if (e.code === "Escape") {
        setRecording(false);
        return;
      }
      const accelerator = acceleratorFromEvent(e);
      if (accelerator) {
        setRecording(false);
        onSave(accelerator);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [recording, onSave]);

  return (
    <Button
      className={`min-w-44 font-mono ${recording ? "ring-2 ring-amber-400/70" : ""}`}
      onClick={() => setRecording((r) => !r)}
      data-testid="hotkey-field"
    >
      {recording ? t("hotkey.recording") : formatAccelerator(value)}
    </Button>
  );
}
