// Choices offered by the settings screens and the wizard.
import type { MessageKey } from "../i18n";

export const KEY_SLOTS: { id: string; label: MessageKey; hint: MessageKey }[] = [
  { id: "anthropic", label: "keys.anthropic", hint: "keys.anthropicHint" },
  { id: "openai", label: "keys.openai", hint: "keys.openaiHint" },
  { id: "openrouter", label: "keys.openrouter", hint: "keys.openrouterHint" },
  { id: "custom", label: "keys.custom", hint: "keys.customHint" },
];

export const STT_PROVIDERS = ["faster-whisper", "whisper.cpp", "gigaam", "cloud"] as const;

export const TTS_PROVIDERS = ["silero", "piper", "cloud"] as const;

export const CLOUD_PROVIDERS = ["anthropic", "openai", "openrouter", "custom"] as const;

export const LOCAL_PROVIDERS = ["ollama", "llama.cpp", "lm-studio"] as const;

export const STEPS = ["language", "mic", "mode", "setup", "wake"] as const;

export type Step = (typeof STEPS)[number];
