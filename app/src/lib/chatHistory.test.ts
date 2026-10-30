import { describe, expect, it } from "vitest";
import { chatReducer, HISTORY_LIMIT, loadHistory, saveHistory, type ChatItem } from "./chatHistory";
import type { EventName } from "./rpc";

const ev = (items: ChatItem[], event: EventName, params: object) =>
  chatReducer(items, { type: "event", event, params, time: 1 });

describe("chatReducer", () => {
  it("records a voice turn with a tool call", () => {
    let items = ev([], "transcript.final", { utterance_id: "u1", text: "сделай громче" });
    items = ev(items, "tool.started", { call_id: "c1", tool: "pc.volume_change", arguments: {} });
    items = ev(items, "tool.finished", {
      call_id: "c1",
      tool: "pc.volume_change",
      ok: true,
      summary: "70%",
    });
    items = ev(items, "assistant.delta", { turn_id: "t1", text: "Сделала " });
    items = ev(items, "assistant.delta", { turn_id: "t1", text: "громче" });
    expect(items.map((i) => i.kind)).toEqual(["user", "tool", "assistant"]);
    expect(items[1]).toMatchObject({ status: "ok", summary: "70%" });
    expect(items[2]).toMatchObject({ text: "Сделала громче", done: false });
    items = ev(items, "assistant.done", {
      turn_id: "t1",
      text: "Сделала громче.",
      interrupted: true,
    });
    expect(items[2]).toMatchObject({ text: "Сделала громче.", done: true, interrupted: true });
  });

  it("does not duplicate a repeated final transcript", () => {
    let items = ev([], "transcript.final", { utterance_id: "u1", text: "a" });
    items = ev(items, "transcript.final", { utterance_id: "u1", text: "ab" });
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ text: "ab", via: "voice" });
  });

  it("shows typed messages, failures and core errors", () => {
    let items = chatReducer([], { type: "sent", id: "l1", text: "привет", time: 1 });
    items = chatReducer(items, { type: "failed", id: "l1", message: "нет связи", time: 2 });
    items = ev(items, "error", {
      code: "llm_unreachable",
      message: "LLM недоступна",
      recoverable: true,
    });
    expect(items.map((i) => i.kind)).toEqual(["user", "error", "error"]);
    expect(chatReducer(items, { type: "clear" })).toEqual([]);
  });

  it("keeps only the latest messages", () => {
    let items: ChatItem[] = [];
    for (let i = 0; i < HISTORY_LIMIT + 5; i++)
      items = chatReducer(items, { type: "sent", id: `l${i}`, text: String(i), time: i });
    expect(items).toHaveLength(HISTORY_LIMIT);
    expect(items[0]).toMatchObject({ id: "l5" });
  });

  it("survives a restart and closes unfinished answers", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    };
    saveHistory(ev([], "assistant.delta", { turn_id: "t", text: "полу" }), storage);
    expect(loadHistory(storage)[0]).toMatchObject({ text: "полу", done: true });
    store.set("solana.chat.v1", "{broken");
    expect(loadHistory(storage)).toEqual([]);
  });
});
