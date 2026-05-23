//! FinAgent Desktop — Tauri application entry point.
//!
//! Architecture:
//!   1. Tauri Rust shell (this process) — owns the window and menu bar.
//!   2. Python sidecar — spawned at startup via `tauri-plugin-shell`;
//!      runs the FastAPI server on 127.0.0.1:8321 (provides /api/* + /chat).
//!   3. WebView — loads the React UI from Vite dev server (http://localhost:5173
//!      in dev) or the bundled frontendDist (../ui/dist/index.html in build).
//!      React calls Python at 127.0.0.1:8321 via fetch — Vite proxy in dev,
//!      absolute URL in build (TODO Phase 4c: inject base URL via build env).
//!
//! Communication is plain HTTP/SSE. No `invoke()` calls into Rust.

mod sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_os::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        );

    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_global_shortcut::Builder::new().build());
    }

    builder
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
