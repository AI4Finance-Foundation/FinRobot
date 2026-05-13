//! FinAgent Desktop — Tauri application entry point.
//!
//! Architecture:
//!   1. Tauri Rust shell (this process) — owns the window and menu bar.
//!   2. Python sidecar — spawned at startup via `tauri-plugin-shell`;
//!      runs the FastAPI server on 127.0.0.1:8321.
//!   3. WebView — loads http://127.0.0.1:8321 after the sidecar reports healthy.
//!
//! Communication is plain HTTP/SSE. No `invoke()` calls into Rust.

mod sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .setup(|app| {
            let handle = app.handle().clone();

            // Spawn the Python sidecar in a background task so the Tauri
            // event loop stays responsive while we wait for /health.
            tauri::async_runtime::spawn(async move {
                match tauri::async_runtime::spawn_blocking(move || {
                    sidecar::spawn_and_wait_for_ready(&handle)
                })
                .await
                {
                    Ok(Ok(_child)) => {
                        // Child handle intentionally dropped here — the sidecar
                        // process will be killed by the OS when the Tauri process
                        // exits. Explicit lifecycle management is Phase 4c.
                        eprintln!("[desktop] sidecar ready — window will load the UI");
                    }
                    Ok(Err(e)) => {
                        eprintln!("[desktop] fatal: sidecar failed to start: {e}");
                        std::process::exit(1);
                    }
                    Err(e) => {
                        eprintln!("[desktop] fatal: join error: {e}");
                        std::process::exit(1);
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
