// Choices offered by the settings screens and the wizard.
import type { MessageKey } from "../i18n";

// Keyring entry names match core/solana_core/brain/router.py PRESETS.
export const KEY_SLOTS: { id: string; label: MessageKey; hint: MessageKey }[] = [
  { id: "anthropic_api_key", label: "keys.anthropic", hint: "keys.anthropicHint" },
  { id: "openai_api_key", label: "keys.openai", hint: "keys.openaiHint" },
  { id: "openrouter_api_key", label: "keys.openrouter", hint: "keys.openrouterHint" },
  { id: "openai_compatible_api_key", label: "keys.custom", hint: "keys.customHint" },
];

export const STT_PROVIDERS = ["faster-whisper", "whisper.cpp", "gigaam", "cloud"] as const;

export const TTS_PROVIDERS = ["silero", "piper", "cloud"] as const;

export const CLOUD_PROVIDERS = ["anthropic", "openai", "openrouter", "openai-compatible"] as const;

export const LOCAL_PROVIDERS = ["ollama", "lmstudio", "llamacpp"] as const;

export const STEPS = ["language", "mic", "mode", "setup", "wake"] as const;

export type Step = (typeof STEPS)[number];
