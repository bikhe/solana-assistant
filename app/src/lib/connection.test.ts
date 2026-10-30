import { expect, it } from "vitest";
import { coreUrl, infoFromSearch } from "./connection";

it("reads port and token from the page URL", () => {
  expect(infoFromSearch("?port=8765&token=dev")).toEqual({ port: 8765, token: "dev" });
  expect(infoFromSearch("?port=8765")).toBeNull();
  expect(infoFromSearch("")).toBeNull();
});

it("builds the WebSocket URL", () => {
  expect(coreUrl({ port: 1, token: "a b" })).toBe("ws://127.0.0.1:1/?token=a%20b");
});
