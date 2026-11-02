// Pure reducer from core events to what the UI shows. Kept free of React so it is easy to test.
import type {
  AssistantState,
  ConfirmRequestEvent,
  ErrorEvent,
  ToolStartedEvent,
} from "@protocol/ipc";
import type { ConnectionStatus, EventName, EventParams } from "./rpc";

export interface LogEntry {
  id: number;
  time: number;
  event: EventName;
  params: unknown;
}

export interface CoreView {
  status: ConnectionStatus;
  state: AssistantState;
  /** Why the core entered the current state, e.g. wake_word, hotkey. */
  reason: string | null;
  fake: boolean;
  transcript: string;
  answer: string;
  /** Tool that is running right now, if any. */
  tool: ToolStartedEvent | null;
  confirm: ConfirmRequestEvent | null;
  /** Time the confirmation card appeared, for its countdown. */
  confirmSince: number;
  error: ErrorEvent | null;
  log: LogEntry[];
  nextLogId: number;
}

export type CoreAction =
  | { type: "status"; status: ConnectionStatus }
  | { type: "fake"; fake: boolean }
  | { type: "event"; event: EventName; params: unknown; time: number }
  | { type: "confirm.answered"; requestId: string }
  | { type: "error.dismiss" };

export const LOG_LIMIT = 50;

export const initialView: CoreView = {
  status: "disconnected",
  state: "idle",
  reason: null,
  fake: false,
  transcript: "",
  answer: "",
  tool: null,
  confirm: null,
  confirmSince: 0,
  error: null,
  log: [],
  nextLogId: 0,
};

function applyEvent(v: CoreView, event: EventName, params: unknown, time: number): CoreView {
  switch (event) {
    case "state": {
      const e = params as EventParams<"state">;
      const next: CoreView = { ...v, state: e.state, reason: e.reason ?? null };
      // A new turn starts with a clean slate.
      if (e.state === "wake" || (e.state === "listening" && v.state === "idle")) {
        next.transcript = "";
        next.answer = "";
        next.tool = null;
      }
      // A confirmation card only makes sense while the assistant waits on it.
      if (e.state !== "thinking") next.confirm = null;
      if (e.state !== "error") next.error = e.state === "idle" ? null : v.error;
      return next;
    }
    case "transcript.partial":
      return { ...v, transcript: (params as EventParams<"transcript.partial">).text, answer: "" };
    case "transcript.final":
      return { ...v, transcript: (params as EventParams<"transcript.final">).text };
    case "assistant.delta":
      return { ...v, answer: v.answer + (params as EventParams<"assistant.delta">).text };
    case "assistant.done":
      return { ...v, answer: (params as EventParams<"assistant.done">).text, tool: null };
    case "tool.started":
      return { ...v, tool: params as EventParams<"tool.started"> };
    case "tool.finished": {
      const e = params as EventParams<"tool.finished">;
      return v.tool?.call_id === e.call_id ? { ...v, tool: null } : v;
    }
    case "confirm.request":
      return { ...v, confirm: params as EventParams<"confirm.request">, confirmSince: time };
    case "error":
      return { ...v, error: params as EventParams<"error"> };
    default:
      return v;
  }
}

export function coreReducer(v: CoreView, action: CoreAction): CoreView {
  switch (action.type) {
    case "status":
      return { ...v, status: action.status };
    case "fake":
      return { ...v, fake: action.fake };
    case "confirm.answered":
      return v.confirm?.request_id === action.requestId ? { ...v, confirm: null } : v;
    case "error.dismiss":
      return { ...v, error: null };
    case "event": {
      const next = applyEvent(v, action.event, action.params, action.time);
      const entry = {
        id: v.nextLogId,
        time: action.time,
        event: action.event,
        params: action.params,
      };
      return { ...next, log: [entry, ...v.log].slice(0, LOG_LIMIT), nextLogId: v.nextLogId + 1 };
    }
  }
}
