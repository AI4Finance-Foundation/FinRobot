//! Python sidecar lifecycle manager.
//!
//! Spawns the bundled `finrobot-server` binary via `tauri-plugin-shell`,
//! waits up to `READINESS_TIMEOUT_SECS` for `/health` to return 200, and
//! returns the `CommandChild` handle so the caller can kill it on exit.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::AppHandle;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

/// How many recent `[sidecar:err]` lines to keep in the ring buffer for
/// post-mortem reporting when the sidecar fails to become ready.
const STDERR_RING_CAPACITY: usize = 50;

/// How long to wait for the sidecar's `/health` to return 200 before giving up.
///
/// The sidecar is a PyInstaller one-file binary: on launch it unpacks ~140 MB
/// to a temp dir, then imports a heavy dependency tree (pandas, edgartools,
/// pydantic-ai) before FastAPI is ready. On the dev machine that is ~10-18 s,
/// but a slower/older Mac — or one whose antivirus scans the freshly-extracted
/// files — can take much longer. 30 s was too tight and surfaced as a bogus
/// "sidecar did not become ready" on exactly the end-user machines we ship to.
const READINESS_TIMEOUT_SECS: u64 = 90;

/// Spawn the bundled `finrobot-server` sidecar and block until it is ready.
///
/// The sidecar is resolved by Tauri's platform-triple matcher, e.g.
/// `finrobot-server-aarch64-apple-darwin` on Apple Silicon.
///
/// Stdout/stderr from the sidecar are forwarded to the host process's stderr
/// so they appear in the terminal during `cargo tauri dev`.
///
/// While the sidecar boots, the most recent `STDERR_RING_CAPACITY` lines of
/// its stderr are also stashed in a ring buffer. If `/health` does not
/// respond in time, those lines are replayed to our stderr so the
/// user (or the dev) can see the real Python traceback — historically this
/// information vanished because the Tauri window had no terminal attached
/// and the only visible failure was the generic "did not become ready"
/// message.
///
/// # Errors
///
/// Returns an error string if:
/// - The sidecar binary cannot be found or spawned.
/// - `/health` does not return 200 within `READINESS_TIMEOUT_SECS`.
pub fn spawn_and_wait_for_ready(
    app: &AppHandle,
    capability_token: &str,
) -> Result<tauri_plugin_shell::process::CommandChild, String> {
    // Pass our own PID so the sidecar self-terminates if this shell dies — see
    // the parent-death watchdog in finrobot/cli.py. Tauri kills the sidecar
    // bootloader with SIGKILL on a clean quit (handled in lib.rs), but SIGKILL
    // can't be forwarded to the Python grandchild; the watchdog is the backstop
    // that also covers a shell *crash*.
    let parent_pid = std::process::id().to_string();
    let (mut rx, child) = app
        .shell()
        .sidecar("finrobot-server")
        .map_err(|e| format!("sidecar not found: {e}"))?
        // Hand the capability token to the server via env (never argv — argv is
        // world-readable via `ps`). The middleware enforces it on every request;
        // the readiness /health poll below stays exempt. See finrobot/auth.py.
        .env("FINROBOT_CAPABILITY_TOKEN", capability_token)
        .args([
            "--host",
            "127.0.0.1",
            "--port",
            "8321",
            "--parent-pid",
            &parent_pid,
        ])
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

    // Ring buffer of recent stderr lines. Shared between the forward task
    // and the readiness-polling thread so we can dump it on timeout.
    let stderr_ring: Arc<Mutex<VecDeque<String>>> =
        Arc::new(Mutex::new(VecDeque::with_capacity(STDERR_RING_CAPACITY)));
    let stderr_ring_for_task = stderr_ring.clone();

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
                        let trimmed = line.trim_end().to_string();
                        eprintln!("[sidecar:err] {trimmed}");
                        // Keep at most STDERR_RING_CAPACITY lines.
                        if let Ok(mut buf) = stderr_ring_for_task.lock() {
                            if buf.len() == STDERR_RING_CAPACITY {
                                buf.pop_front();
                            }
                            buf.push_back(trimmed);
                        }
                    }
                }
                CommandEvent::Error(msg) => {
                    eprintln!("[sidecar:error] {msg}");
                    if let Ok(mut buf) = stderr_ring_for_task.lock() {
                        if buf.len() == STDERR_RING_CAPACITY {
                            buf.pop_front();
                        }
                        buf.push_back(format!("[sidecar:error] {msg}"));
                    }
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
    let deadline = Instant::now() + Duration::from_secs(READINESS_TIMEOUT_SECS);
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

    // Replay the captured stderr so the operator can see WHY the sidecar
    // never became ready. Without this, all they'd see in the Tauri shell
    // is the bare "did not become ready" string below.
    eprintln!(
        "[sidecar] -------- last {} stderr lines (replay) --------",
        STDERR_RING_CAPACITY
    );
    if let Ok(buf) = stderr_ring.lock() {
        if buf.is_empty() {
            eprintln!("[sidecar] (stderr ring buffer is empty)");
        } else {
            for line in buf.iter() {
                eprintln!("[sidecar:err] {line}");
            }
        }
    }
    eprintln!("[sidecar] ----------------------------------------------");

    Err(format!(
        "sidecar did not become ready within {READINESS_TIMEOUT_SECS} seconds"
    ))
}
