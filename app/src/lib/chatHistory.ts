// Chat history built from core events plus the user's own typed messages.
import type { EventName, EventParams } from "./rpc";

export type ChatItem =
  | { kind: "user"; id: string; text: string; via: "text" | "voice"; time: number }
  | {
      kind: "assistant";
      id: string;
      text: string;
      done: boolean;
      interrupted: boolean;
      time: number;
    }
  | {
      kind: "tool";
      id: string;
      tool: string;
      status: "running" | "ok" | "error";
      summary?: string;
      time: number;
    }
  | { kind: "error"; id: string; message: string; time: number };

export type ChatAction =
  | { type: "event"; event: EventName; params: unknown; time: number }
  | { type: "sent"; id: string; text: string; time: number }
  | { type: "failed"; id: string; message: string; time: number }
  | { type: "clear" };

export const HISTORY_LIMIT = 200;

function upsert(
  items: ChatItem[],
  id: string,
  kind: ChatItem["kind"],
  make: (old?: ChatItem) => ChatItem,
) {
  const i = items.findIndex((it) => it.id === id && it.kind === kind);
  if (i === -1) return [...items, make()];
  const copy = items.slice();
  copy[i] = make(items[i]);
  return copy;
}

function applyEvent(
  items: ChatItem[],
  event: EventName,
  params: unknown,
  time: number,
): ChatItem[] {
  switch (event) {
    case "transcript.final": {
      const e = params as EventParams<"transcript.final">;
      return upsert(items, e.utterance_id, "user", () => ({
        kind: "user",
        id: e.utterance_id,
        text: e.text,
        via: "voice",
        time,
      }));
    }
    case "assistant.delta": {
      const e = params as EventParams<"assistant.delta">;
      return upsert(items, e.turn_id, "assistant", (old) => ({
        kind: "assistant",
        id: e.turn_id,
        text: (old?.kind === "assistant" ? old.text : "") + e.text,
        done: false,
        interrupted: false,
        time: old?.time ?? time,
      }));
    }
    case "assistant.done": {
      const e = params as EventParams<"assistant.done">;
      return upsert(items, e.turn_id, "assistant", (old) => ({
        kind: "assistant",
        id: e.turn_id,
        text: e.text,
        done: true,
        interrupted: e.interrupted ?? false,
        time: old?.time ?? time,
      }));
    }
    case "tool.started": {
      const e = params as EventParams<"tool.started">;
      return upsert(items, e.call_id, "tool", () => ({
        kind: "tool",
        id: e.call_id,
        tool: e.tool,
        status: "running",
        time,
      }));
    }
    case "tool.finished": {
      const e = params as EventParams<"tool.finished">;
      return upsert(items, e.call_id, "tool", (old) => ({
        kind: "tool",
        id: e.call_id,
        tool: e.tool,
        status: e.ok ? "ok" : "error",
        summary: e.ok ? e.summary : (e.error ?? e.summary),
        time: old?.time ?? time,
      }));
    }
    case "error": {
      const e = params as EventParams<"error">;
      return [
        ...items,
        { kind: "error", id: `err-${time}-${items.length}`, message: e.message, time },
      ];
    }
    default:
      return items;
  }
}

export function chatReducer(items: ChatItem[], action: ChatAction): ChatItem[] {
  let next: ChatItem[];
  switch (action.type) {
    case "clear":
      return [];
    case "sent":
      next = [
        ...items,
        { kind: "user", id: action.id, text: action.text, via: "text", time: action.time },
      ];
      break;
    case "failed":
      next = [
        ...items,
        { kind: "error", id: `err-${action.id}`, message: action.message, time: action.time },
      ];
      break;
    case "event":
      next = applyEvent(items, action.event, action.params, action.time);
      break;
  }
  return next.length > HISTORY_LIMIT ? next.slice(-HISTORY_LIMIT) : next;
}

const STORAGE_KEY = "solana.chat.v1";

export function loadHistory(
  storage: Pick<Storage, "getItem"> | undefined = globalThis.localStorage,
): ChatItem[] {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    const items = raw ? (JSON.parse(raw) as ChatItem[]) : [];
    // An answer cut off by closing the app will never finish.
    return Array.isArray(items)
      ? items.map((it) => (it.kind === "assistant" && !it.done ? { ...it, done: true } : it))
      : [];
  } catch {
    return [];
  }
}

export function saveHistory(
  items: ChatItem[],
  storage: Pick<Storage, "setItem"> | undefined = globalThis.localStorage,
): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Storage full or disabled: history just will not survive a restart.
  }
}
