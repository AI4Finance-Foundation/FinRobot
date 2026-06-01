//! FinRobot Desktop — Tauri application entry point.
//!
//! Architecture:
//!   1. Tauri Rust shell (this process) — owns the window and menu bar.
//!   2. Python sidecar — spawned at startup via `tauri-plugin-shell`;
//!      runs the FastAPI server on 127.0.0.1:8321 (provides /api/* + /chat).
//!      Skipped when `FINROBOT_DEV_LIVE_BACKEND` is set, so a live source-tree
//!      backend can serve :8321 instead (see `dev.sh --app`).
//!   3. WebView — loads the React UI from Vite dev server (http://localhost:5173
//!      in dev) or the bundled frontendDist (../ui/dist/index.html in build).
//!      React calls Python at 127.0.0.1:8321 via fetch — Vite proxy in dev,
//!      absolute URL in build.
//!
//! Communication is plain HTTP/SSE. No `invoke()` calls into Rust.

mod sidecar;

use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;

/// Holds the spawned Python sidecar so we can terminate it when the app exits.
/// Without this the frozen server orphans on 127.0.0.1:8321 and the next launch
/// silently talks to the stale process.
#[derive(Default)]
struct SidecarHandle(Mutex<Option<CommandChild>>);

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
        .manage(SidecarHandle::default())
        .setup(|app| {
            // Live-backend dev posture (see `dev.sh --app`): a `finrobot serve`
            // process from this machine's source tree is already running on :8321,
            // so backend edits take effect immediately. Skip the frozen PyInstaller
            // sidecar entirely — the WebView reaches the live backend through the
            // Vite proxy, exactly like the browser dev loop. Production launches
            // (env var unset) keep spawning the bundled sidecar as before.
            if std::env::var_os("FINROBOT_DEV_LIVE_BACKEND").is_some() {
                eprintln!(
                    "[desktop] FINROBOT_DEV_LIVE_BACKEND set — skipping bundled sidecar; \
                     WebView will use the live backend already on 127.0.0.1:8321"
                );
                return Ok(());
            }

            let handle = app.handle().clone();

            // Spawn the Python sidecar in a background task so the Tauri
            // event loop stays responsive while we wait for /health.
            tauri::async_runtime::spawn(async move {
                match tauri::async_runtime::spawn_blocking({
                    let handle = handle.clone();
                    move || sidecar::spawn_and_wait_for_ready(&handle)
                })
                .await
                {
                    Ok(Ok(child)) => {
                        // Keep the child so RunEvent::Exit can kill it — the
                        // frozen server would otherwise orphan on :8321. The
                        // parent-pid watchdog inside the sidecar is the backstop
                        // for crashes / the SIGKILL-can't-reach-the-grandchild case.
                        handle
                            .state::<SidecarHandle>()
                            .0
                            .lock()
                            .unwrap()
                            .replace(child);
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
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app_handle.state::<SidecarHandle>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
