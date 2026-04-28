mod commands;
mod sidecar;

use sidecar::SidecarHandle;
use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    // Only fire on key-press, not key-release.
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    log::info!("global shortcut: {shortcut:?}");
                    handle_global_shortcut(app, shortcut);
                })
                .build(),
        )
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

            // Register the OS-wide shortcuts. Failure here is non-fatal —
            // the user can still use the app via the window UI.
            register_global_shortcuts(app.handle());

            // Show the main window now that the sidecar is up. We start
            // hidden in tauri.conf.json to avoid the brief unstyled flash
            // before the React app mounts.
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![commands::rpc])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

// --- Global shortcuts ------------------------------------------------------

/// Toggle-recording shortcut. The frontend listens for `bt://shortcut`
/// events and decides what to do based on the meaning string.
const TOGGLE_RECORDING_SHORTCUT: Shortcut =
    Shortcut::new(Some(Modifiers::CONTROL.union(Modifiers::SHIFT)), Code::Space);

/// Show the main window (Bibliothek) from anywhere in the OS.
const SHOW_LIBRARY_SHORTCUT: Shortcut =
    Shortcut::new(Some(Modifiers::CONTROL), Code::KeyO);

fn register_global_shortcuts<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    let manager = app.global_shortcut();
    for sc in [TOGGLE_RECORDING_SHORTCUT, SHOW_LIBRARY_SHORTCUT] {
        if let Err(e) = manager.register(sc) {
            log::warn!("failed to register shortcut {sc:?}: {e}");
        }
    }
}

fn handle_global_shortcut<R: tauri::Runtime>(app: &tauri::AppHandle<R>, sc: &Shortcut) {
    if *sc == SHOW_LIBRARY_SHORTCUT {
        bring_main_to_front(app);
        return;
    }
    if *sc == TOGGLE_RECORDING_SHORTCUT {
        // For now: surface the press to the frontend. Phase-2 step 2 will
        // wire the actual recording toggle (Mini-Widget + sidecar capture).
        bring_main_to_front(app);
        if let Err(e) = app.emit(
            "bt://shortcut",
            serde_json::json!({"action": "toggle_recording"}),
        ) {
            log::warn!("failed to emit shortcut event: {e}");
        }
    }
}

fn bring_main_to_front<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}
