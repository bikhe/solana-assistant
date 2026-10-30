import { describe, expect, it } from "vitest";
import { acceleratorFromEvent, formatAccelerator } from "./accelerator";

const key = (
  code: string,
  mods: Partial<Record<"ctrlKey" | "metaKey" | "altKey" | "shiftKey", boolean>> = {},
) => ({
  code,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...mods,
});

describe("accelerator", () => {
  it("builds Tauri accelerators", () => {
    expect(acceleratorFromEvent(key("Space", { ctrlKey: true, shiftKey: true }), false)).toBe(
      "CommandOrControl+Shift+Space",
    );
    expect(acceleratorFromEvent(key("KeyS", { metaKey: true, altKey: true }), true)).toBe(
      "CommandOrControl+Alt+S",
    );
    expect(acceleratorFromEvent(key("Digit1", { altKey: true }), false)).toBe("Alt+1");
    expect(acceleratorFromEvent(key("F9"), false)).toBe("F9");
  });

  it("waits for a real key and refuses bare letters", () => {
    expect(acceleratorFromEvent(key("ShiftLeft", { shiftKey: true }), false)).toBeNull();
    expect(acceleratorFromEvent(key("KeyA"), false)).toBeNull();
  });

  it("formats for the OS", () => {
    expect(formatAccelerator("CommandOrControl+Shift+Space", false)).toBe("Ctrl + Shift + Space");
    expect(formatAccelerator("CommandOrControl+Shift+Space", true)).toBe("⌘⇧Space");
  });
});
