//! Window helpers. All windows are declared in tauri.conf.json; the frontend picks its view by
//! the window label.

use tauri::{AppHandle, Manager, PhysicalPosition, WebviewWindow};

pub const OVERLAY: &str = "overlay";
pub const CHAT: &str = "chat";
pub const SETTINGS: &str = "settings";
pub const WIZARD: &str = "wizard";

/// Gap between the overlay and the top edge of the screen, in logical pixels.
const OVERLAY_TOP_GAP: f64 = 12.0;

pub fn show(app: &AppHandle, label: &str) {
    if let Some(window) = app.get_webview_window(label) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Puts the overlay at the top centre of the primary monitor.
pub fn place_overlay(app: &AppHandle) {
    let Some(window) = app.get_webview_window(OVERLAY) else {
        return;
    };
    let Ok(Some(monitor)) = window.primary_monitor() else {
        return;
    };
    let Ok(size) = window.outer_size() else {
        return;
    };
    let area = monitor.size();
    let origin = monitor.position();
    let x = origin.x + (area.width as i32 - size.width as i32) / 2;
    let y = origin.y + (OVERLAY_TOP_GAP * monitor.scale_factor()) as i32;
    let _ = window.set_position(PhysicalPosition::new(x, y));
}

/// Shows and focuses one of the app windows (chat, settings, wizard).
#[tauri::command]
pub fn show_window(app: AppHandle, label: String) -> Result<(), String> {
    match label.as_str() {
        CHAT | SETTINGS | WIZARD => {
            show(&app, &label);
            Ok(())
        }
        _ => Err(format!("unknown window: {label}")),
    }
}

/// Hides the calling window.
#[tauri::command]
pub fn hide_window(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|e| e.to_string())
}
