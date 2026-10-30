//! Checks GitHub Releases for a newer version and offers to install it.
//!
//! The updater is active only in builds whose config has `plugins.updater` (the release workflow
//! adds it when the signing key is set up, see docs/RELEASING.md). Other builds skip it.

use tauri::{AppHandle, Config};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

pub fn enabled(config: &Config) -> bool {
    config.plugins.0.contains_key("updater")
}

pub fn check_in_background(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(err) = check(&app).await {
            eprintln!("update check failed: {err}");
        }
    });
}

async fn check(app: &AppHandle) -> tauri_plugin_updater::Result<()> {
    let Some(update) = app.updater()?.check().await? else {
        return Ok(());
    };
    let version = update.version.clone();
    let app = app.clone();
    app.clone()
        .dialog()
        .message(format!(
            "Доступна новая версия Solana {version} (у вас {}). Установить сейчас? \
             Приложение перезапустится.",
            update.current_version
        ))
        .title("Обновление Solana")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Обновить".into(),
            "Позже".into(),
        ))
        .show(move |accepted| {
            if !accepted {
                return;
            }
            tauri::async_runtime::spawn(async move {
                // The installer replaces the sidecar, which Windows can't do while it runs.
                let installed = update
                    .download_and_install(|_, _| {}, || crate::core::kill(&app))
                    .await;
                match installed {
                    Ok(()) => app.restart(),
                    Err(err) => {
                        eprintln!("update to {version} failed: {err}");
                        if !crate::core::is_running(&app) {
                            let _ = crate::core::spawn(&app);
                        }
                        app.dialog()
                            .message(format!("Не удалось установить обновление: {err}"))
                            .title("Обновление Solana")
                            .kind(MessageDialogKind::Error)
                            .show(|_| {});
                    }
                }
            });
        });
    Ok(())
}
