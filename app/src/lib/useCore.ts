import { useEffect, useState } from "react";
import type { AssistantState, ConfirmRequestEvent } from "@protocol/ipc";
import type { ConnectionStatus, CoreClient, EventName } from "./rpc";

export interface LogEntry {
  id: number;
  time: number;
  event: EventName;
  params: unknown;
}

export interface CoreView {
  status: ConnectionStatus;
  state: AssistantState;
  fake: boolean;
  transcript: string;
  answer: string;
  confirm: ConfirmRequestEvent | null;
  log: LogEntry[];
}

const LOG_LIMIT = 50;

export const initialView: CoreView = {
  status: "disconnected",
  state: "idle",
  fake: false,
  transcript: "",
  answer: "",
  confirm: null,
  log: [],
};

/** Subscribes to a CoreClient and keeps a render-friendly view of what the core reports. */
export function useCore(client: CoreClient | null): CoreView {
  const [view, setView] = useState<CoreView>(initialView);

  useEffect(() => {
    if (!client) return;
    let logId = 0;
    const patch = (p: Partial<CoreView>) => setView((v) => ({ ...v, ...p }));
    const offs = [
      client.onStatus((status) => {
        patch({ status });
        if (status === "connected") {
          client
            .request("ping")
            .then((r) => patch({ fake: r.fake }))
            .catch(() => undefined);
        }
      }),
      client.on("state", (e) =>
        // A confirmation card only makes sense while the assistant waits on it.
        setView((v) => ({
          ...v,
          state: e.state,
          confirm: e.state === "thinking" ? v.confirm : null,
        })),
      ),
      client.on("transcript.partial", (e) => patch({ transcript: e.text, answer: "" })),
      client.on("transcript.final", (e) => patch({ transcript: e.text })),
      client.on("assistant.delta", (e) => setView((v) => ({ ...v, answer: v.answer + e.text }))),
      client.on("assistant.done", (e) => patch({ answer: e.text })),
      client.on("confirm.request", (e) => patch({ confirm: e })),
      client.onAny((event, params) =>
        setView((v) => ({
          ...v,
          log: [{ id: logId++, time: Date.now(), event, params }, ...v.log].slice(0, LOG_LIMIT),
        })),
      ),
    ];
    patch({ status: client.status });
    return () => offs.forEach((off) => off());
  }, [client]);

  return view;
}
