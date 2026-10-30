import { describe, expect, it } from "vitest";
import { coreReducer, initialView, LOG_LIMIT, type CoreView } from "./coreView";
import type { EventName } from "./rpc";

const ev = (v: CoreView, event: EventName, params: object, time = 1) =>
  coreReducer(v, { type: "event", event, params, time });

const confirm = {
  request_id: "r1",
  tool: "pc.volume_set",
  risk: "confirm",
  title: "Громкость 70%?",
  arguments: {},
  voice_allowed: true,
};

describe("coreReducer", () => {
  it("builds the transcript and streams the answer", () => {
    let v = ev(initialView, "state", { state: "wake", reason: "wake_word" });
    expect(v.reason).toBe("wake_word");
    v = ev(v, "transcript.partial", { utterance_id: "u", text: "какая" });
    v = ev(v, "transcript.final", { utterance_id: "u", text: "какая погода" });
    v = ev(v, "assistant.delta", { turn_id: "t", text: "Плюс " });
    v = ev(v, "assistant.delta", { turn_id: "t", text: "пять" });
    expect(v).toMatchObject({ transcript: "какая погода", answer: "Плюс пять" });
    v = ev(v, "assistant.done", { turn_id: "t", text: "Плюс пять." });
    expect(v.answer).toBe("Плюс пять.");
  });

  it("starts a new turn with a clean slate", () => {
    let v = { ...initialView, transcript: "old", answer: "old" };
    v = ev(v, "state", { state: "wake" });
    expect(v).toMatchObject({ transcript: "", answer: "" });
  });

  it("keeps the confirmation only while thinking", () => {
    let v = ev(initialView, "state", { state: "thinking" });
    v = ev(v, "confirm.request", confirm, 42);
    expect(v.confirm?.request_id).toBe("r1");
    expect(v.confirmSince).toBe(42);
    expect(ev(v, "state", { state: "speaking" }).confirm).toBeNull();
    expect(coreReducer(v, { type: "confirm.answered", requestId: "r1" }).confirm).toBeNull();
    expect(coreReducer(v, { type: "confirm.answered", requestId: "other" }).confirm).not.toBeNull();
  });

  it("tracks the running tool", () => {
    let v = ev(initialView, "tool.started", { call_id: "c1", tool: "pc.media", arguments: {} });
    expect(v.tool?.tool).toBe("pc.media");
    v = ev(v, "tool.finished", { call_id: "other", tool: "x", ok: true });
    expect(v.tool).not.toBeNull();
    v = ev(v, "tool.finished", { call_id: "c1", tool: "pc.media", ok: true });
    expect(v.tool).toBeNull();
  });

  it("keeps an error until the assistant is idle again", () => {
    let v = ev(initialView, "error", { code: "mic", message: "Нет микрофона", recoverable: true });
    v = ev(v, "state", { state: "error" });
    expect(v.error?.message).toBe("Нет микрофона");
    expect(ev(v, "state", { state: "idle" }).error).toBeNull();
  });

  it("caps the event log", () => {
    let v = initialView;
    for (let i = 0; i < LOG_LIMIT + 10; i++) v = ev(v, "state", { state: "idle" });
    expect(v.log).toHaveLength(LOG_LIMIT);
    expect(v.log[0]!.id).toBe(LOG_LIMIT + 9);
  });
});
