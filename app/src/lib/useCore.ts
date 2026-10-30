import { useEffect, useReducer, useState } from "react";
import { coreUrl, resolveCoreInfo } from "./connection";
import { coreReducer, initialView, type CoreAction, type CoreView } from "./coreView";
import { CoreClient } from "./rpc";

export type { CoreView, LogEntry } from "./coreView";

export interface CoreHandle {
  view: CoreView;
  dispatch: (action: CoreAction) => void;
}

/** Subscribes to a CoreClient and keeps a render-friendly view of what the core reports. */
export function useCore(client: CoreClient | null): CoreHandle {
  const [view, dispatch] = useReducer(coreReducer, initialView);

  useEffect(() => {
    if (!client) return;
    const offs = [
      client.onStatus((status) => {
        dispatch({ type: "status", status });
        if (status === "connected") {
          client
            .request("ping")
            .then((r) => dispatch({ type: "fake", fake: r.fake }))
            .catch(() => undefined);
        }
      }),
      client.onAny((event, params) => dispatch({ type: "event", event, params, time: Date.now() })),
    ];
    dispatch({ type: "status", status: client.status });
    return () => offs.forEach((off) => off());
  }, [client]);

  return { view, dispatch };
}

/** Finds the core (Tauri or ?port=&token=) and opens a connection, unless a client is given. */
export function useCoreClient(given?: CoreClient): { client: CoreClient | null; noCore: boolean } {
  const [client, setClient] = useState<CoreClient | null>(given ?? null);
  const [noCore, setNoCore] = useState(false);

  useEffect(() => {
    if (given) return;
    let created: CoreClient | null = null;
    let cancelled = false;
    resolveCoreInfo().then((info) => {
      if (cancelled) return;
      if (!info) {
        setNoCore(true);
        return;
      }
      created = new CoreClient(coreUrl(info));
      created.connect();
      setClient(created);
    });
    return () => {
      cancelled = true;
      created?.close();
    };
  }, [given]);

  return { client, noCore };
}
