mod core;
mod updater;

use tauri::RunEvent;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let context = tauri::generate_context!();
    let mut builder = tauri::Builder::default().plugin(tauri_plugin_dialog::init());
    if updater::enabled(context.config()) {
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    }
    builder
        .manage(core::CoreState::default())
        .invoke_handler(tauri::generate_handler![core::core_info])
        .setup(|app| {
            if let Err(err) = core::spawn(app.handle()) {
                eprintln!("failed to start solana-core: {err}");
            }
            if updater::enabled(app.config()) {
                updater::check_in_background(app.handle());
            }
            Ok(())
        })
        .build(context)
        .expect("error while building the Tauri app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                core::kill(app);
            }
        });
}
