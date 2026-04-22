mod commands;
mod sidecar;

use sidecar::SidecarHandle;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Spawn the Python sidecar and hand it to Tauri's state container
            // so invoke handlers can reach it via `State<SidecarHandle>`.
            match SidecarHandle::spawn(app.handle()) {
                Ok(handle) => {
                    app.manage(handle);
                    log::info!("sidecar spawned and managed");
                }
                Err(e) => {
                    log::error!("FATAL: sidecar spawn failed: {e}");
                    // Don't panic — let the UI surface the error via a failing
                    // rpc command rather than an unstartable app.
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![commands::rpc])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
