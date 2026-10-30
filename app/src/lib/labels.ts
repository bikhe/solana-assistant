import type { AssistantState } from "@protocol/ipc";
import type { ConnectionStatus } from "./rpc";

// WP4 moves these into proper i18n (ru + en).
export const stateLabels: Record<AssistantState, string> = {
  idle: "Жду «Эй, Солана»",
  wake: "Слушаю…",
  listening: "Слушаю…",
  thinking: "Думаю…",
  speaking: "Отвечаю",
  muted: "Микрофон выключен",
  error: "Ошибка",
};

export const statusLabels: Record<ConnectionStatus, string> = {
  connecting: "подключение…",
  connected: "подключён",
  disconnected: "не подключён",
};
