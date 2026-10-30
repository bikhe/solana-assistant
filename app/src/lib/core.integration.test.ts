// @vitest-environment node
// End-to-end: starts the real solana-core in --fake mode and checks that its events reach the app client.
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { coreUrl, type CoreInfo } from "./connection";
import { CoreClient, type EventParams, type SocketLike } from "./rpc";

const coreDir = fileURLToPath(new URL("../../../core", import.meta.url));
const hasUv = spawnSync("uv", ["--version"], { stdio: "ignore" }).status === 0;

describe.skipIf(!hasUv)("solana-core --fake", () => {
  let proc: ChildProcess;
  let info: CoreInfo;

  beforeAll(async () => {
    proc = spawn(
      "uv",
      ["run", "--project", coreDir, "solana-core", "--fake", "--fake-speed", "20", "--port", "0"],
      { stdio: ["ignore", "pipe", "inherit"] },
    );
    const lines = createInterface({ input: proc.stdout! });
    info = await new Promise<CoreInfo>((resolve, reject) => {
      proc.once("exit", (code) => reject(new Error(`core exited with ${code}`)));
      lines.on("line", (line) => {
        if (line.startsWith("SOLANA_CORE_READY ")) resolve(JSON.parse(line.slice(18)));
      });
    });
  }, 120_000);

  afterAll(() => {
    proc?.kill();
  });

  it("delivers core events to the app client", async () => {
    const client = new CoreClient(coreUrl(info), {
      socketFactory: (url) => new WebSocket(url) as unknown as SocketLike,
      reconnectMs: 0,
    });
    const states: EventParams<"state">["state"][] = [];
    const sawWake = new Promise<void>((resolve) => {
      client.on("state", (e) => {
        states.push(e.state);
        if (e.state === "wake") resolve();
      });
    });
    const connected = new Promise<void>((resolve) =>
      client.onStatus((s) => s === "connected" && resolve()),
    );
    client.connect();
    await connected;

    const pong = await client.request("ping");
    expect(pong).toMatchObject({ pong: true, fake: true, protocol_version: 1 });

    await sawWake;
    expect(states[0]).toBe("idle");
    client.close();
  });
});
