"""MCP demo for ``solana-core --fake``: sample servers served by ``FakeConnector``."""

from __future__ import annotations

from solana_core.config import ConfigStore
from solana_core.config.models import McpServerEntry, McpSettings
from solana_core.mcp.connection import FakeConnector, RemoteTool

_PATH = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

DEMO_SERVERS = {
    "filesystem": McpServerEntry(
        command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "~"]
    ),
    "time": McpServerEntry(command="uvx", args=["mcp-server-time"]),
    "home-assistant": McpServerEntry(
        url="http://homeassistant.local:8123/mcp_server/sse", enabled=False
    ),
}


def fake_connector() -> FakeConnector:
    connector = FakeConnector(
        {
            "filesystem": [
                RemoteTool("read_text_file", "Прочитать текстовый файл", _PATH),
                RemoteTool("list_directory", "Список файлов в папке", _PATH),
            ],
            "time": [RemoteTool("get_current_time", "Текущее время в часовом поясе")],
        }
    )
    connector.fail["home-assistant"] = "Сервер требует авторизацию (HTTP 401)"
    return connector


def seed_demo(config: ConfigStore) -> None:
    """Fill an empty fake config with the demo servers, so the MCP tab has something to show."""
    if not config.settings.mcp.servers:
        config.save(
            config.settings.model_copy(update={"mcp": McpSettings(servers=dict(DEMO_SERVERS))})
        )
