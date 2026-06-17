//! Python sidecar lifecycle manager.
//!
//! Spawns the bundled `finrobot-server` exe (a PyInstaller one-dir bundle
//! shipped under `Contents/Resources/finrobot-server/`) via
//! `tauri-plugin-shell`, waits up to `READINESS_TIMEOUT_SECS` for `/health`
//! to return 200, and returns the `CommandChild` handle so the caller can
//! kill it on exit.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

/// How many recent `[sidecar:err]` lines to keep in the ring buffer for
/// post-mortem reporting when the sidecar fails to become ready.
const STDERR_RING_CAPACITY: usize = 50;

/// How long to wait for the sidecar's `/health` to return 200 before giving up.
///
/// The sidecar is a PyInstaller one-dir bundle, so there is no per-launch
/// extraction: importing the dependency tree (pandas, edgartools, pydantic-ai)
/// takes ~1-5 s. The generous ceiling exists for the very first launch after
/// install, when Gatekeeper/antivirus may verify every bundled dylib once.
const READINESS_TIMEOUT_SECS: u64 = 90;

/// Spawn the bundled `finrobot-server` sidecar and block until it is ready.
///
/// The exe lives inside the resource bundle at
/// `sidecar/finrobot-server` (next to its `_internal/` runtime).
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

    // Resolve the one-dir exe from the bundled resources. In a packaged app
    // this is Contents/Resources/sidecar/finrobot-server; in `cargo tauri dev`
    // the resource dir sits next to the debug binary. The resource dir is
    // named `sidecar`, NOT `finrobot-server`: the legacy externalBin config
    // left a FILE called finrobot-server in old cargo target dirs, and the
    // resource copier dies with "Not a directory" on the name collision.
    // PyInstaller names the one-dir launcher after the spec's COLLECT `name`;
    // Windows appends `.exe`, macOS/Linux leave it bare. The bundled resource
    // DIR is `sidecar/` on every platform (tauri.conf.json `resources`); only
    // the launcher file inside it differs by OS.
    #[cfg(windows)]
    const SIDECAR_REL: &str = "sidecar/finrobot-server.exe";
    #[cfg(not(windows))]
    const SIDECAR_REL: &str = "sidecar/finrobot-server";

    let exe_path = app
        .path()
        .resolve(SIDECAR_REL, BaseDirectory::Resource)
        .map_err(|e| format!("sidecar resource not found: {e}"))?;
    if !exe_path.is_file() {
        return Err(format!(
            "sidecar exe missing at {} — run desktop/src-tauri/sidecar/build.sh",
            exe_path.display()
        ));
    }

    // The resource copy (bundler) and the updater's tar extraction are not
    // guaranteed to preserve the executable bit; restore it before spawning.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = std::fs::metadata(&exe_path) {
            let mut perms = meta.permissions();
            if perms.mode() & 0o111 == 0 {
                perms.set_mode(0o755);
                std::fs::set_permissions(&exe_path, perms)
                    .map_err(|e| format!("failed to mark sidecar executable: {e}"))?;
            }
        }
    }

    let (mut rx, child) = app
        .shell()
        .command(&exe_path)
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

    // Death flag: the only task that owns the CommandEvent stream is the
    // forwarder below, so it is the only place we learn the child has
    // Terminated. Bridge that signal to the readiness loop via an atomic so a
    // child that dies on bind failure (port 8321 already taken → SystemExit in
    // finrobot/cli.py) fails readiness *immediately* instead of letting the
    // loop poll a foreign backend that happens to answer 200 on the same port.
    let child_dead = Arc::new(AtomicBool::new(false));
    let child_dead_for_task = child_dead.clone();

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
                    // Tell the readiness loop the child is gone so it stops
                    // (or never starts) trusting a 200 from whatever else is on
                    // :8321.
                    child_dead_for_task.store(true, Ordering::SeqCst);
                    break;
                }
                _ => {}
            }
        }
    });

    // Poll /health until 200 OK or timeout.
    //
    // A bare "200 from :8321" is NOT proof our child is up: loopback is shared,
    // and if our child died on a bind clash (port already taken → SystemExit in
    // finrobot/cli.py) some *other* finrobot backend may be answering on the
    // same port. We close that hole two ways:
    //   1. If the child has Terminated (death flag set by the forward task),
    //      bail immediately — never return Ok holding a corpse handle.
    //   2. Match the capability token echoed by /health against the one we
    //      minted and handed the child via env. A foreign process cannot read
    //      our env, so it cannot echo our token. We only enforce this when we
    //      actually minted a token (it is always set in the spawned-sidecar
    //      posture; the live-backend dev posture never reaches this function).
    let deadline = Instant::now() + Duration::from_secs(READINESS_TIMEOUT_SECS);
    while Instant::now() < deadline {
        if child_dead.load(Ordering::SeqCst) {
            return Err(
                "sidecar process exited during startup (port 8321 may be occupied \
                 by another process). See replayed stderr above."
                    .to_string(),
            );
        }

        std::thread::sleep(Duration::from_millis(500));

        // Re-check after the sleep so a death during the wait short-circuits
        // before we trust a /health 200 from whatever else holds the port.
        if child_dead.load(Ordering::SeqCst) {
            return Err(
                "sidecar process exited during startup (port 8321 may be occupied \
                 by another process). See replayed stderr above."
                    .to_string(),
            );
        }

        let result = ureq::get("http://127.0.0.1:8321/health")
            .timeout(Duration::from_secs(2))
            .call();
        match result {
            Ok(resp) if resp.status() == 200 => {
                // When we minted a token, the backend answering must echo it
                // back — otherwise it is a port squatter, not our child.
                if !capability_token.is_empty() {
                    let body = resp.into_string().unwrap_or_default();
                    let echoed = serde_json::from_str::<serde_json::Value>(&body)
                        .ok()
                        .and_then(|v| v.get("token").and_then(|t| t.as_str()).map(str::to_owned));
                    match echoed {
                        Some(token) if token == capability_token => {
                            eprintln!("[sidecar] server ready on http://127.0.0.1:8321");
                            return Ok(child);
                        }
                        _ => {
                            // 200 but no matching token: a different backend is
                            // squatting :8321. Stop trusting it. Our child is
                            // already dead (bind clash) or about to be; the
                            // death-flag check above will turn the next loop
                            // into a clean Err, and the timeout Err is the
                            // backstop if the event is slow to arrive.
                            eprintln!(
                                "[sidecar] /health on :8321 answered without our \
                                 capability token — another process is occupying \
                                 the port; not trusting it"
                            );
                            continue;
                        }
                    }
                }
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
