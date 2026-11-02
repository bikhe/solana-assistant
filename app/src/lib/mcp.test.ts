import { describe, expect, it } from "vitest";
import { MCP_PRESETS, parseCommandLine, parseMcpJson, slug, splitArgs, suggestName } from "./mcp";

describe("mcp helpers", () => {
  it("splits command lines like a shell", () => {
    expect(splitArgs(`npx -y "@scope/pkg" 'C:\\My Files' --flag`)).toEqual([
      "npx",
      "-y",
      "@scope/pkg",
      "C:\\My Files",
      "--flag",
    ]);
  });

  it("tells URLs from commands", () => {
    expect(parseCommandLine("  https://mcp.deepwiki.com/mcp ")).toEqual({
      url: "https://mcp.deepwiki.com/mcp",
    });
    expect(parseCommandLine("uvx mcp-server-time")).toEqual({
      command: "uvx",
      args: ["mcp-server-time"],
    });
    expect(parseCommandLine("   ")).toBeNull();
  });

  it("suggests readable names", () => {
    expect(suggestName({ url: "https://mcp.deepwiki.com/mcp" })).toBe("deepwiki");
    expect(suggestName({ url: "https://learn.microsoft.com/api/mcp" })).toBe("learn");
    expect(
      suggestName({ command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "~"] }),
    ).toBe("filesystem");
    expect(suggestName({ command: "uvx", args: ["mcp-server-time"] })).toBe("time");
    expect(slug("My Server!")).toBe("My-Server");
  });

  it("reads Claude Desktop configs", () => {
    const text = JSON.stringify({
      mcpServers: {
        "file system": {
          command: "npx",
          args: ["-y", "@modelcontextprotocol/server-filesystem", "/home"],
          env: { DEBUG: 1 },
        },
        remote: { type: "http", url: "https://example.com/mcp", headers: { "X-A": "b" } },
        off: { command: "uvx", args: ["x"], disabled: true },
        broken: { args: ["nothing to run"] },
      },
    });
    expect(parseMcpJson(text)).toEqual([
      {
        name: "file-system",
        config: {
          command: "npx",
          args: ["-y", "@modelcontextprotocol/server-filesystem", "/home"],
          env: { DEBUG: "1" },
        },
        enabled: true,
      },
      {
        name: "remote",
        config: { url: "https://example.com/mcp", headers: { "X-A": "b" } },
        enabled: true,
      },
      { name: "off", config: { command: "uvx", args: ["x"] }, enabled: false },
    ]);
    expect(parseMcpJson('{"time": {"command": "uvx", "args": ["mcp-server-time"]}}')).toHaveLength(
      1,
    );
    expect(() => parseMcpJson("not json")).toThrow();
  });

  it("has valid, unique presets", () => {
    const names = MCP_PRESETS.map((p) => p.name);
    expect(new Set(names).size).toBe(names.length);
    for (const p of MCP_PRESETS) {
      expect(p.name).toMatch(/^[A-Za-z0-9_-]+$/);
      expect(Boolean(p.config.url) !== Boolean(p.config.command)).toBe(true);
    }
  });
});
