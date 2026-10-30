import { act, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { App } from "./App";
import { CoreClient, type SocketLike } from "./lib/rpc";

class Socket implements SocketLike {
  readyState = 0;
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  send() {}
  close() {}
}

it("shows connection status and the assistant state from core events", () => {
  let socket!: Socket;
  const client = new CoreClient("ws://x", {
    socketFactory: () => (socket = new Socket()),
    reconnectMs: 0,
  });
  client.connect();
  render(<App client={client} />);
  expect(screen.getByTestId("core-status")).toHaveTextContent("подключение");

  act(() => {
    socket.readyState = 1;
    socket.onopen?.({});
  });
  expect(screen.getByTestId("core-status")).toHaveTextContent("core: подключён");

  act(() => {
    socket.onmessage?.({
      data: JSON.stringify({ jsonrpc: "2.0", method: "state", params: { state: "thinking" } }),
    });
  });
  expect(screen.getByTestId("assistant-state")).toHaveTextContent("Думаю");

  act(() => {
    socket.onmessage?.({
      data: JSON.stringify({
        jsonrpc: "2.0",
        method: "confirm.request",
        params: {
          request_id: "r1",
          tool: "pc.set_volume",
          risk: "confirm",
          title: "Сделать громкость 70%?",
          arguments: {},
          voice_allowed: true,
        },
      }),
    });
  });
  expect(screen.getByText("Сделать громкость 70%?")).toBeInTheDocument();
});
