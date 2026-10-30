import { createContext, useContext } from "react";
import type { ConfirmRequestEvent } from "@protocol/ipc";
import type { CoreAction, CoreView } from "./coreView";
import type { CoreClient } from "./rpc";
import type { SettingsHandle } from "./settings";

export interface AppContextValue {
  client: CoreClient | null;
  core: CoreView;
  dispatch: (action: CoreAction) => void;
  settings: SettingsHandle;
  /** True when no core address is known (browser without ?port=&token=). */
  noCore: boolean;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp outside of AppContext");
  return value;
}

export function replyConfirm(
  ctx: Pick<AppContextValue, "client" | "dispatch">,
  confirm: ConfirmRequestEvent,
  approved: boolean,
  always = false,
): void {
  ctx.dispatch({ type: "confirm.answered", requestId: confirm.request_id });
  ctx.client
    ?.request("confirm.reply", { request_id: confirm.request_id, approved, always })
    .catch(() => undefined);
}

export function setMuted(client: CoreClient | null, muted: boolean): void {
  client?.request("voice.mute", { muted }).catch(() => undefined);
}
