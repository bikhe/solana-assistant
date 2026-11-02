// In-memory core for UI tests: answers requests from a handler map and pushes events.
import { act } from "@testing-library/react";
import { CoreClient, type EventName, type SocketLike } from "../lib/rpc";

type Handler = (params: Record<string, unknown>) => unknown;

export const defaultSettings = {
  general: { language: "ru", autostart: false, first_run_done: true },
  voice: {
    wake_word_enabled: true,
    wake_sensitivity: 0.5,
    input_device: null,
    output_device: null,
    stt_provider: "faster-whisper",
    tts_provider: "silero",
    tts_voice: null,
    end_of_speech_ms: 1000,
    push_to_talk_hotkey: "CommandOrControl+Shift+Space",
  },
  brain: {
    mode: "local",
    cloud_provider: "anthropic",
    cloud_model: "claude-sonnet-5-5",
    cloud_base_url: null,
    local_provider: "ollama",
    local_model: "qwen3:8b",
    local_base_url: "http://127.0.0.1:11434/v1",
  },
  tools: { always_allow: [], disabled: [] },
  mcp: { servers: {} },
  skills: { disabled: [] },
};

function merge(target: Record<string, unknown>, patch: Record<string, unknown>) {
  for (const [k, v] of Object.entries(patch)) {
    const cur = target[k];
    if (v && typeof v === "object" && !Array.isArray(v) && cur && typeof cur === "object") {
      merge(cur as Record<string, unknown>, v as Record<string, unknown>);
    } else target[k] = v;
  }
}

class Socket implements SocketLike {
  readyState = 0;
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  constructor(private readonly core: FakeCore) {}
  send(data: string) {
    const msg = JSON.parse(data) as { id: number; method: string; params: Record<string, unknown> };
    this.core.requests.push({ method: msg.method, params: msg.params });
    const handler = this.core.handlers[msg.method];
    queueMicrotask(() => {
      if (!handler) {
        this.reply({ id: msg.id, error: { code: -32601, message: "Method not found" } });
        return;
      }
      this.reply({ id: msg.id, result: handler(msg.params) });
    });
  }
  reply(body: object) {
    this.onmessage?.({ data: JSON.stringify({ jsonrpc: "2.0", ...body }) });
  }
  close() {}
}

export class FakeCore {
  settings = structuredClone(defaultSettings) as Record<string, unknown>;
  requests: { method: string; params: Record<string, unknown> }[] = [];
  socket!: Socket;
  readonly client: CoreClient;
  handlers: Record<string, Handler> = {
    ping: () => ({ pong: true, version: "0.1.0", protocol_version: 1, fake: true }),
    "settings.get": () => ({ settings: this.settings }),
    "settings.set": (p) => {
      merge(this.settings, p.patch as Record<string, unknown>);
      return { settings: this.settings };
    },
    "chat.send": () => ({ turn_id: "t1" }),
    "confirm.reply": () => ({ ok: true }),
    "voice.mute": (p) => ({ muted: p.muted }),
    "tools.list": () => ({ tools: [] }),
    "mcp.list": () => ({ servers: [] }),
    "skills.list": () => ({ skills: [] }),
    "models.list": () => ({ models: [] }),
  };

  constructor() {
    this.client = new CoreClient("ws://fake", {
      socketFactory: () => (this.socket = new Socket(this)),
      reconnectMs: 0,
    });
  }

  /** Connects and lets the initial ping / settings.get settle. */
  async connect() {
    this.client.connect();
    await act(async () => {
      this.socket.readyState = 1;
      this.socket.onopen?.({});
      await new Promise((r) => setTimeout(r, 0));
    });
  }

  async emit(event: EventName, params: object) {
    await act(async () => {
      this.socket.onmessage?.({ data: JSON.stringify({ jsonrpc: "2.0", method: event, params }) });
    });
  }

  sent(method: string) {
    return this.requests.filter((r) => r.method === method).map((r) => r.params);
  }
}
