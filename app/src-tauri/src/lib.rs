mod core;

use tauri::RunEvent;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(core::CoreState::default())
        .invoke_handler(tauri::generate_handler![core::core_info])
        .setup(|app| {
            if let Err(err) = core::spawn(app.handle()) {
                eprintln!("failed to start solana-core: {err}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Tauri app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                core::kill(app);
            }
        });
}
