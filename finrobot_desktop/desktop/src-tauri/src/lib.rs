//! FinRobot Desktop — Tauri application entry point.
//!
//! Architecture:
//!   1. Tauri Rust shell (this process) — owns the window and menu bar.
//!   2. Python sidecar — spawned at startup via `tauri-plugin-shell`;
//!      runs the FastAPI server on 127.0.0.1:8321 (provides /api/* + /chat).
//!      Skipped when `FINROBOT_DEV_LIVE_BACKEND` is set, so a live source-tree
//!      backend can serve :8321 instead (see `dev.sh --app`).
//!   3. WebView — loads the React UI from Vite dev server (http://localhost:5173
//!      in dev) or the bundled frontendDist (../dist/index.html in build).
//!      React calls Python at 127.0.0.1:8321 via fetch — Vite proxy in dev,
//!      absolute URL in build.
//!
//! Communication is plain HTTP/SSE. No `invoke()` calls into Rust.

mod sidecar;

use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_shell::process::CommandChild;

/// Holds the spawned Python sidecar so we can terminate it when the app exits.
/// Without this the frozen server orphans on 127.0.0.1:8321 and the next launch
/// silently talks to the stale process.
#[derive(Default)]
struct SidecarHandle(Mutex<Option<CommandChild>>);

/// Per-launch capability token. Minted at startup, handed to the sidecar via
/// FINROBOT_CAPABILITY_TOKEN and to the WebView via the `capability_token`
/// command, so a *different* local process — which can reach loopback but
/// cannot drive this WebView's IPC — cannot read /api/settings or burn quota.
struct CapabilityToken(String);

/// Return the per-launch capability token to the WebView. The IPC boundary is
/// in-process: another OS process cannot inject into this WebView's JS to call
/// it, which is exactly what makes the token a usable shared secret.
#[tauri::command]
fn capability_token(state: tauri::State<'_, CapabilityToken>) -> String {
    state.0.clone()
}

/// Show a blocking error dialog explaining why the backend never started, then
/// return so the caller can exit. Without this the only failure signal was an
/// `eprintln!` followed by a silent `process::exit(1)` — on a packaged app with
/// no terminal attached the window simply never appeared, so a user with port
/// 8321 already taken (a leftover sidecar, or any other process) saw nothing.
///
/// `MessageDialogBuilder::blocking_show` must not run on the main-thread event
/// loop, and we are inside an async task here, so we hop onto a blocking worker
/// via `spawn_blocking` and await it.
async fn fatal_startup_dialog(handle: &tauri::AppHandle, detail: &str) {
    let handle = handle.clone();
    let detail = detail.to_string();
    let _ = tauri::async_runtime::spawn_blocking(move || {
        handle
            .dialog()
            .message(format!(
                "FinRobot could not start its backend.\n\n{detail}\n\nThis usually \
                 means port 8321 is already in use by another process (often a \
                 leftover FinRobot backend). Quit that process — or any app holding \
                 the port — and relaunch FinRobot."
            ))
            .title("FinRobot failed to start")
            .kind(MessageDialogKind::Error)
            .buttons(MessageDialogButtons::Ok)
            .blocking_show();
    })
    .await;
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        );

    builder
        .manage(SidecarHandle::default())
        .invoke_handler(tauri::generate_handler![capability_token])
        .setup(|app| {
            // Mint the per-launch capability token and expose it to the WebView
            // (capability_token command). Done before the dev-backend branch so
            // the command always resolves; only the spawned sidecar receives it
            // via env — in the live-backend posture the external server runs
            // auth-disabled (no env) and simply ignores any token the UI sends.
            let token = uuid::Uuid::new_v4().simple().to_string();
            app.manage(CapabilityToken(token.clone()));

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
                    let token = token.clone();
                    move || sidecar::spawn_and_wait_for_ready(&handle, &token)
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
                        fatal_startup_dialog(&handle, &e).await;
                        std::process::exit(1);
                    }
                    Err(e) => {
                        eprintln!("[desktop] fatal: join error: {e}");
                        fatal_startup_dialog(&handle, &e.to_string()).await;
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
