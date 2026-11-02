// Shortcut strings in Tauri's accelerator format, e.g. "CommandOrControl+Shift+Space".

const MODIFIER_CODES = new Set([
  "ShiftLeft",
  "ShiftRight",
  "ControlLeft",
  "ControlRight",
  "AltLeft",
  "AltRight",
  "MetaLeft",
  "MetaRight",
]);

export interface KeyLike {
  code: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

function keyName(code: string): string {
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  return code;
}

/**
 * Builds an accelerator from a keydown. Returns null while only modifiers are held, or for a
 * bare key: a global shortcut without a modifier would swallow normal typing.
 */
export function acceleratorFromEvent(e: KeyLike, mac = isMac()): string | null {
  if (MODIFIER_CODES.has(e.code)) return null;
  const parts: string[] = [];
  if (mac ? e.metaKey : e.ctrlKey) parts.push("CommandOrControl");
  if (mac && e.ctrlKey) parts.push("Control");
  if (!mac && e.metaKey) parts.push("Super");
  if (e.altKey) parts.push("Alt");
  if (e.shiftKey) parts.push("Shift");
  const key = keyName(e.code);
  const isFunctionKey = /^F\d{1,2}$/.test(key);
  if (parts.length === 0 && !isFunctionKey) return null;
  return [...parts, key].join("+");
}

/** Human-readable form for the current OS. */
export function formatAccelerator(accelerator: string, mac = isMac()): string {
  const names: Record<string, string> = mac
    ? { CommandOrControl: "⌘", Control: "⌃", Alt: "⌥", Shift: "⇧", Super: "⌘" }
    : { CommandOrControl: "Ctrl", Control: "Ctrl", Alt: "Alt", Shift: "Shift", Super: "Win" };
  return accelerator
    .split("+")
    .filter(Boolean)
    .map((p) => names[p] ?? p)
    .join(mac ? "" : " + ");
}

export function isMac(): boolean {
  return typeof navigator !== "undefined" && /Mac/i.test(navigator.platform || navigator.userAgent);
}
