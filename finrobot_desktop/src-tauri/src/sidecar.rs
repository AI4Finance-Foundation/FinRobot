//! Python sidecar lifecycle manager.
//!
//! Spawns the bundled `finagent-server` binary via `tauri-plugin-shell`,
//! waits up to 30 seconds for `/health` to return 200, and returns the
//! `CommandChild` handle so the caller can kill it on exit.

use std::time::{Duration, Instant};

use tauri::AppHandle;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

/// Spawn the bundled `finagent-server` sidecar and block until it is ready.
///
/// The sidecar is resolved by Tauri's platform-triple matcher, e.g.
/// `finagent-server-aarch64-apple-darwin` on Apple Silicon.
///
/// Stdout/stderr from the sidecar are forwarded to the host process's stderr
/// so they appear in the terminal during `cargo tauri dev`.
///
/// # Errors
///
/// Returns an error string if:
/// - The sidecar binary cannot be found or spawned.
/// - `/health` does not return 200 within 30 seconds.
pub fn spawn_and_wait_for_ready(
    app: &AppHandle,
) -> Result<tauri_plugin_shell::process::CommandChild, String> {
    let (mut rx, child) = app
        .shell()
        .sidecar("finagent-server")
        .map_err(|e| format!("sidecar not found: {e}"))?
        .args(["--host", "127.0.0.1", "--port", "8321"])
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

    // Forward sidecar output to our own stderr in a background task.
    // This keeps the log stream visible during development without blocking.
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    if let Ok(line) = std::str::from_utf8(&bytes) {
                        eprintln!("[sidecar] {}", line.trim_end());
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    if let Ok(line) = std::str::from_utf8(&bytes) {
                        eprintln!("[sidecar:err] {}", line.trim_end());
                    }
                }
                CommandEvent::Error(msg) => {
                    eprintln!("[sidecar:error] {msg}");
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!(
                        "[sidecar] process terminated (code={:?})",
                        payload.code
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    // Poll /health until 200 OK or timeout.
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(500));
        let result = ureq::get("http://127.0.0.1:8321/health")
            .timeout(Duration::from_secs(2))
            .call();
        match result {
            Ok(resp) if resp.status() == 200 => {
                eprintln!("[sidecar] server ready on http://127.0.0.1:8321");
                return Ok(child);
            }
            _ => continue,
        }
    }

    Err("sidecar did not become ready within 30 seconds".into())
}
