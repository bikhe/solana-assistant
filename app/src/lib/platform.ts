// Everything that differs between the Tauri shell and a plain browser tab (pnpm dev).
// In the browser the window helpers fall back to switching ?view= in the same tab.
import { invoke, isTauri } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  disable as disableAutostart,
  enable as enableAutostart,
  isEnabled as autostartEnabled,
} from "@tauri-apps/plugin-autostart";
import { register, unregister } from "@tauri-apps/plugin-global-shortcut";

export type View = "overlay" | "chat" | "settings" | "wizard";
const views: readonly View[] = ["overlay", "chat", "settings", "wizard"];

export const inTauri = (): boolean => isTauri();

export function viewFromSearch(search: string): View {
  const v = new URLSearchParams(search).get("view");
  return views.includes(v as View) ? (v as View) : "chat";
}

/** In Tauri the window label is the view; in the browser it is ?view=. */
export function currentView(): View {
  if (inTauri()) {
    const label = getCurrentWindow().label;
    return views.includes(label as View) ? (label as View) : "chat";
  }
  return viewFromSearch(window.location.search);
}

export function browserNavigate(view: View): void {
  const params = new URLSearchParams(window.location.search);
  params.set("view", view);
  window.location.search = params.toString();
}

export async function showWindow(view: Exclude<View, "overlay">): Promise<void> {
  if (inTauri()) await invoke("show_window", { label: view });
  else browserNavigate(view);
}

export async function hideWindow(): Promise<void> {
  if (inTauri()) await invoke("hide_window");
  else browserNavigate("chat");
}

export async function setWindowTitle(title: string): Promise<void> {
  if (inTauri()) await getCurrentWindow().setTitle(title);
  else document.title = title;
}

/** Overlay only: let clicks fall through to the windows below. */
export async function setClickThrough(on: boolean): Promise<void> {
  if (inTauri()) await getCurrentWindow().setIgnoreCursorEvents(on);
}

export interface TrayLabels {
  mute: string;
  chat: string;
  settings: string;
  quit: string;
}

export async function updateTray(labels: TrayLabels, muted: boolean): Promise<void> {
  if (inTauri()) await invoke("update_tray", { labels, muted });
}

export function onTrayAction(callback: (action: string) => void): () => void {
  if (!inTauri()) return () => undefined;
  const off = listen<string>("tray-action", (e) => callback(e.payload));
  return () => void off.then((f) => f());
}

// Each window has its own core connection, so settings changes are shared explicitly.
const SETTINGS_EVENT = "settings-changed";
let channel: BroadcastChannel | null = null;
function browserChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  channel ??= new BroadcastChannel("solana");
  return channel;
}

export function broadcastSettings(settings: unknown): void {
  if (inTauri()) void emit(SETTINGS_EVENT, settings);
  else browserChannel()?.postMessage({ type: SETTINGS_EVENT, settings });
}

export function onSettingsChanged(callback: (settings: unknown) => void): () => void {
  if (inTauri()) {
    const off = listen(SETTINGS_EVENT, (e) => callback(e.payload));
    return () => void off.then((f) => f());
  }
  const ch = browserChannel();
  if (!ch) return () => undefined;
  const handler = (e: MessageEvent) => {
    if (e.data?.type === SETTINGS_EVENT) callback(e.data.settings);
  };
  ch.addEventListener("message", handler);
  return () => ch.removeEventListener("message", handler);
}

/** Registers a hold-to-talk shortcut. Resolves to an unregister function. */
export async function registerHoldShortcut(
  accelerator: string,
  onDown: () => void,
  onUp: () => void,
): Promise<() => void> {
  if (!inTauri() || !accelerator) return () => undefined;
  await register(accelerator, (e) => (e.state === "Pressed" ? onDown() : onUp()));
  return () => void unregister(accelerator).catch(() => undefined);
}

export async function syncAutostart(enabled: boolean): Promise<void> {
  if (!inTauri()) return;
  if ((await autostartEnabled()) === enabled) return;
  await (enabled ? enableAutostart() : disableAutostart());
}
