import { describe, expect, it, vi } from "vitest";
import { CoreClient, RpcError, type SocketLike } from "./rpc";

class FakeSocket implements SocketLike {
  static last: FakeSocket;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.last = this;
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
    this.onclose?.({});
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function makeClient(reconnectMs = 0) {
  const client = new CoreClient("ws://x", {
    socketFactory: (url) => new FakeSocket(url),
    reconnectMs,
  });
  client.connect();
  FakeSocket.last.open();
  return { client, socket: FakeSocket.last };
}

describe("CoreClient", () => {
  it("matches responses to requests", async () => {
    const { client, socket } = makeClient();
    const pong = client.request("ping");
    expect(socket.sent[0]).toEqual({ jsonrpc: "2.0", id: 1, method: "ping", params: {} });
    socket.receive({
      jsonrpc: "2.0",
      id: 1,
      result: { pong: true, version: "0.1.0", protocol_version: 1, fake: true },
    });
    await expect(pong).resolves.toMatchObject({ pong: true, fake: true });
  });

  it("turns error responses into RpcError", async () => {
    const { client, socket } = makeClient();
    const reply = client.request("chat.send", { text: "привет" });
    socket.receive({ jsonrpc: "2.0", id: 1, error: { code: -32001, message: "nope" } });
    await expect(reply).rejects.toBeInstanceOf(RpcError);
    await expect(reply).rejects.toMatchObject({ code: -32001 });
  });

  it("delivers events to typed and catch-all listeners", () => {
    const { client, socket } = makeClient();
    const onState = vi.fn();
    const onAny = vi.fn();
    const off = client.on("state", onState);
    client.onAny(onAny);
    socket.receive({ jsonrpc: "2.0", method: "state", params: { state: "listening" } });
    expect(onState).toHaveBeenCalledWith({ state: "listening" });
    expect(onAny).toHaveBeenCalledWith("state", { state: "listening" });
    off();
    socket.receive({ jsonrpc: "2.0", method: "state", params: { state: "idle" } });
    expect(onState).toHaveBeenCalledTimes(1);
  });

  it("rejects pending requests when the connection drops and reconnects", async () => {
    vi.useFakeTimers();
    try {
      const { client, socket } = makeClient(100);
      const statuses: string[] = [];
      client.onStatus((s) => statuses.push(s));
      const reply = client.request("ping");
      socket.close();
      await expect(reply).rejects.toThrow("connection lost");
      expect(client.status).toBe("disconnected");
      vi.advanceTimersByTime(100);
      expect(FakeSocket.last).not.toBe(socket);
      FakeSocket.last.open();
      expect(statuses).toEqual(["disconnected", "connecting", "connected"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refuses requests while disconnected", async () => {
    const client = new CoreClient("ws://x", { socketFactory: (u) => new FakeSocket(u) });
    await expect(client.request("ping")).rejects.toThrow("not connected");
  });
});
