mod core;
mod tray;
mod windows;

use tauri::{Manager, RunEvent, WindowEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    #[cfg(desktop)]
    {
        // A second launch focuses the running app instead of starting another core.
        builder = builder
            .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
                windows::show(app, windows::CHAT);
            }))
            .plugin(tauri_plugin_global_shortcut::Builder::new().build())
            .plugin(tauri_plugin_autostart::init(
                tauri_plugin_autostart::MacosLauncher::LaunchAgent,
                None,
            ));
    }

    builder
        .manage(core::CoreState::default())
        .invoke_handler(tauri::generate_handler![
            core::core_info,
            windows::show_window,
            windows::hide_window,
            tray::update_tray,
        ])
        .setup(|app| {
            if let Err(err) = core::spawn(app.handle()) {
                eprintln!("failed to start solana-core: {err}");
            }
            tray::create(app.handle())?;
            windows::place_overlay(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            // Chat, settings and the wizard hide on close: the app lives in the tray.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() != windows::OVERLAY {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the Tauri app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                core::kill(app);
            }
            // Keep running in the tray when the last visible window is hidden.
            if let RunEvent::ExitRequested {
                code: None, api, ..
            } = event
            {
                if app.get_webview_window(windows::OVERLAY).is_some() {
                    api.prevent_exit();
                }
            }
        });
}
