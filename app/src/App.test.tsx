import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { FakeCore } from "./test/fakeCore";

const confirm = {
  request_id: "r1",
  tool: "pc.volume_set",
  risk: "confirm",
  title: "Сделать громкость 70%?",
  arguments: { level: 70 },
  voice_allowed: true,
  timeout_s: 8,
};

let core: FakeCore;
beforeEach(() => {
  localStorage.clear();
  core = new FakeCore();
});

async function show(view: "overlay" | "chat" | "settings" | "wizard") {
  render(<App client={core.client} view={view} />);
  await core.connect();
}

describe("overlay", () => {
  it("is empty while idle and follows the voice turn", async () => {
    await show("overlay");
    expect(screen.queryByTestId("overlay-strip")).toBeNull();

    await core.emit("state", { state: "listening" });
    await core.emit("transcript.partial", { utterance_id: "u", text: "какая сегодня" });
    expect(screen.getByTestId("overlay-text")).toHaveTextContent("какая сегодня");

    await core.emit("state", { state: "speaking" });
    await core.emit("assistant.delta", { turn_id: "t", text: "Плюс пять" });
    expect(screen.getByTestId("overlay-text")).toHaveTextContent("Плюс пять");
  });

  it("answers a confirmation with a click", async () => {
    await show("overlay");
    await core.emit("state", { state: "thinking" });
    await core.emit("confirm.request", confirm);
    const card = screen.getByTestId("confirm-card");
    expect(card).toHaveTextContent("Сделать громкость 70%?");
    fireEvent.click(within(card).getByText("Всегда разрешать"));
    await waitFor(() =>
      expect(core.sent("confirm.reply")).toEqual([
        { request_id: "r1", approved: true, always: true },
      ]),
    );
    await waitFor(() => expect(screen.queryByTestId("confirm-card")).toBeNull());
  });

  it("hides “always allow” for dangerous tools", async () => {
    await show("overlay");
    await core.emit("state", { state: "thinking" });
    await core.emit("confirm.request", { ...confirm, risk: "dangerous", voice_allowed: false });
    expect(screen.queryByText("Всегда разрешать")).toBeNull();
    expect(screen.getByText("Это действие подтверждается только кнопкой")).toBeInTheDocument();
  });
});

describe("chat", () => {
  it("sends typed text and shows the streamed answer", async () => {
    await show("chat");
    expect(screen.getByTestId("core-status")).toHaveTextContent("подключён");
    fireEvent.change(screen.getByPlaceholderText("Напишите Солане…"), {
      target: { value: "привет" },
    });
    fireEvent.click(screen.getByLabelText("Отправить"));
    await waitFor(() =>
      expect(core.sent("chat.send")).toEqual([{ text: "привет", language: "ru" }]),
    );

    await core.emit("assistant.delta", { turn_id: "t1", text: "Привет! " });
    await core.emit("assistant.done", { turn_id: "t1", text: "Привет! Чем помочь?" });
    const list = screen.getByTestId("chat-list");
    expect(list).toHaveTextContent("привет");
    expect(list).toHaveTextContent("Привет! Чем помочь?");
  });

  it("adds voice turns and tool calls to the history", async () => {
    await show("chat");
    await core.emit("transcript.final", { utterance_id: "u1", text: "сделай громче" });
    await core.emit("tool.started", { call_id: "c1", tool: "pc.volume_change", arguments: {} });
    await core.emit("tool.finished", {
      call_id: "c1",
      tool: "pc.volume_change",
      ok: true,
      summary: "70%",
    });
    const list = screen.getByTestId("chat-list");
    expect(list).toHaveTextContent("сделай громче");
    expect(list).toHaveTextContent("pc.volume_change");
    expect(list).toHaveTextContent("70%");
  });

  it("explains when the core has no chat yet", async () => {
    delete core.handlers["chat.send"];
    await show("chat");
    fireEvent.change(screen.getByPlaceholderText("Напишите Солане…"), { target: { value: "эй" } });
    fireEvent.submit(screen.getByPlaceholderText("Напишите Солане…").closest("form")!);
    expect(
      await screen.findByText("Текстовый чат пока недоступен в этой версии ядра"),
    ).toBeInTheDocument();
  });

  it("mutes the microphone", async () => {
    await show("chat");
    fireEvent.click(screen.getByLabelText("Выключить микрофон"));
    await waitFor(() => expect(core.sent("voice.mute")).toEqual([{ muted: true }]));
    await core.emit("state", { state: "muted" });
    expect(screen.getByLabelText("Включить микрофон")).toBeInTheDocument();
  });
});

describe("settings", () => {
  it("has all seven tabs", async () => {
    await show("settings");
    const names = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(names).toEqual(["Общие", "Голос", "Модели", "Ключи", "Инструменты", "MCP", "Скиллы"]);
  });

  it("switches the UI language", async () => {
    await show("settings");
    fireEvent.change(await screen.findByLabelText("Язык"), { target: { value: "en" } });
    await waitFor(() =>
      expect(core.sent("settings.set")).toEqual([{ patch: { general: { language: "en" } } }]),
    );
    expect(await screen.findByText("Start with the system")).toBeInTheDocument();
  });

  it("saves the brain mode", async () => {
    await show("settings");
    fireEvent.click(screen.getByRole("tab", { name: /Модели/ }));
    fireEvent.click(await screen.findByRole("radio", { name: /Облако/ }));
    await waitFor(() =>
      expect(core.sent("settings.set")).toEqual([{ patch: { brain: { mode: "cloud" } } }]),
    );
    expect(await screen.findByText("Облачная модель")).toBeInTheDocument();
  });

  it("records a new push-to-talk shortcut", async () => {
    await show("settings");
    fireEvent.click(await screen.findByTestId("hotkey-field"));
    act(() => {
      fireEvent.keyDown(window, { code: "KeyJ", ctrlKey: true, altKey: true });
    });
    await waitFor(() =>
      expect(core.sent("settings.set")).toEqual([
        { patch: { voice: { push_to_talk_hotkey: "CommandOrControl+Alt+J" } } },
      ]),
    );
  });

  it("tells the user when the core cannot store keys yet", async () => {
    await show("settings");
    fireEvent.click(screen.getByRole("tab", { name: /Ключи/ }));
    expect(
      await screen.findByText("Сохранение ключей появится в следующей версии ядра."),
    ).toBeInTheDocument();
  });

  it("stores keys once the core supports it", async () => {
    const stored: Record<string, string> = {};
    core.handlers["secrets.status"] = () => ({ set: { anthropic_api_key: false } });
    core.handlers["secrets.set"] = (p) => {
      stored[p.name as string] = p.value as string;
      return { ok: true };
    };
    await show("settings");
    fireEvent.click(screen.getByRole("tab", { name: /Ключи/ }));
    const input = await screen.findByLabelText("Anthropic");
    fireEvent.change(input, { target: { value: "sk-test" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(stored).toEqual({ anthropic_api_key: "sk-test" }));
    expect(await screen.findByText("сохранён")).toBeInTheDocument();
  });

  it("toggles tools", async () => {
    core.handlers["tools.list"] = () => ({
      tools: [
        { name: "pc.media", description: "Медиа", risk: "safe", source: "builtin", enabled: true },
      ],
    });
    core.handlers["tools.set_enabled"] = (p) => ({
      name: p.name,
      description: "Медиа",
      risk: "safe",
      source: "builtin",
      enabled: p.enabled,
    });
    await show("settings");
    fireEvent.click(screen.getByRole("tab", { name: /Инструменты/ }));
    const toggle = await screen.findByRole("switch", { name: "pc.media" });
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(core.sent("tools.set_enabled")).toEqual([{ name: "pc.media", enabled: false }]);
  });
});

describe("wizard", () => {
  it("walks through the steps and passes the wake word check", async () => {
    core.settings.general = { language: "ru", autostart: false, first_run_done: false };
    await show("wizard");
    expect(screen.getByTestId("wizard-language")).toBeInTheDocument();

    fireEvent.click(screen.getByText("English"));
    expect(await screen.findByText("Next")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Next"));
    expect(await screen.findByTestId("wizard-mic")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Next"));
    fireEvent.click(await screen.findByRole("radio", { name: /Hybrid/ }));
    fireEvent.click(screen.getByText("Next"));
    expect(await screen.findByText("API key")).toBeInTheDocument();
    expect(screen.getByText("Local models")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Next"));

    expect(await screen.findByTestId("wizard-wake")).toBeInTheDocument();
    await core.emit("state", { state: "wake", reason: "wake_word" });
    expect(screen.getByTestId("wake-result")).toHaveTextContent("Got it!");

    fireEvent.click(screen.getByText("Done"));
    await waitFor(() =>
      expect(core.sent("settings.set")).toContainEqual({
        patch: { general: { first_run_done: true } },
      }),
    );
  });
});
