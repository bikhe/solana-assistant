//! Tray icon and its menu. Menu labels come from the frontend so they follow the UI language;
//! "mute" is forwarded to the frontend because only it talks to the core.

use serde::Deserialize;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Wry};

use crate::windows;

pub struct TrayItems {
    mute: CheckMenuItem<Wry>,
    chat: MenuItem<Wry>,
    settings: MenuItem<Wry>,
    quit: MenuItem<Wry>,
}

#[derive(Deserialize)]
pub struct TrayLabels {
    mute: String,
    chat: String,
    settings: String,
    quit: String,
}

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let mute =
        CheckMenuItem::with_id(app, "mute", "Выключить микрофон", true, false, None::<&str>)?;
    let chat = MenuItem::with_id(app, "chat", "Чат", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Настройки", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Выход", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &mute,
            &PredefinedMenuItem::separator(app)?,
            &chat,
            &settings,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    let mut tray = TrayIconBuilder::with_id("main")
        .tooltip("Solana")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "mute" => {
                let _ = app.emit("tray-action", "mute");
            }
            "chat" => windows::show(app, windows::CHAT),
            "settings" => windows::show(app, windows::SETTINGS),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                windows::show(tray.app_handle(), windows::CHAT);
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;

    app.manage(TrayItems {
        mute,
        chat,
        settings,
        quit,
    });
    Ok(())
}

/// Updates menu labels (UI language) and the microphone check mark.
#[tauri::command]
pub fn update_tray(
    items: tauri::State<'_, TrayItems>,
    labels: TrayLabels,
    muted: bool,
) -> Result<(), String> {
    let err = |e: tauri::Error| e.to_string();
    items.mute.set_text(labels.mute).map_err(err)?;
    items.mute.set_checked(muted).map_err(err)?;
    items.chat.set_text(labels.chat).map_err(err)?;
    items.settings.set_text(labels.settings).map_err(err)?;
    items.quit.set_text(labels.quit).map_err(err)?;
    Ok(())
}
