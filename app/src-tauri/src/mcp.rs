//! Reads the Claude Desktop config so the MCP tab can import its `mcpServers`.

use std::path::PathBuf;

use tauri::{AppHandle, Manager};

/// `<config dir>/Claude/claude_desktop_config.json`: %APPDATA% on Windows,
/// ~/Library/Application Support on macOS, ~/.config on Linux.
fn claude_desktop_config_path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().config_dir().ok()?;
    Some(dir.join("Claude").join("claude_desktop_config.json"))
}

/// The file's text, or `None` when Claude Desktop is not installed.
#[tauri::command]
pub fn claude_desktop_config(app: AppHandle) -> Option<String> {
    std::fs::read_to_string(claude_desktop_config_path(&app)?).ok()
}
