//! Python-sidecar lifecycle and JSON-RPC transport.
//!
//! Owns the spawned `python -m sidecar` child process. Exposes `call()` for
//! request/response RPC and rebroadcasts sidecar-initiated notifications to
//! the frontend via `window.emit("sidecar-event", ...)`.
//!
//! Transport: line-delimited JSON over stdin/stdout. One reader thread
//! continuously consumes stdout, demultiplexes responses by `id`, and forwards
//! notifications (no `id`) to all listening windows.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter, Runtime};
use tokio::sync::oneshot;

// CREATE_NO_WINDOW — keeps a console from popping up on Windows when we
// spawn the Python child. (Only relevant in release builds; in debug the
// parent console is already attached.)
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Serialize)]
struct RpcRequest<'a> {
    jsonrpc: &'a str,
    id: u64,
    method: &'a str,
    params: &'a Value,
}

/// Reply shape — covers responses (id + result/error) AND notifications
/// (method + params, no id). We disambiguate at dispatch time.
#[derive(Debug, Deserialize)]
struct RpcMessage {
    #[allow(dead_code)]
    jsonrpc: Option<String>,
    id: Option<u64>,
    #[serde(default)]
    result: Option<Value>,
    #[serde(default)]
    error: Option<Value>,
    #[serde(default)]
    method: Option<String>,
    #[serde(default)]
    params: Option<Value>,
}

pub struct SidecarHandle {
    next_id: Mutex<u64>,
    stdin: Mutex<ChildStdin>,
    pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, Value>>>>>,
    // Kept alive for the life of the app; dropping would kill the child.
    _child: Mutex<Child>,
}

impl SidecarHandle {
    /// Spawn `python -m sidecar` from the project venv.
    ///
    /// In dev mode we locate the project root via `CARGO_MANIFEST_DIR` (which
    /// points at `app/src-tauri/`) and step up two directories. In production
    /// builds this will be replaced by an externalBin reference to the
    /// PyInstaller-bundled `blitztext-sidecar.exe`.
    pub fn spawn<R: Runtime>(app: &AppHandle<R>) -> Result<Self, String> {
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .ok_or_else(|| "cannot compute project root".to_string())?
            .to_path_buf();

        let python_exe = project_root.join(".venv-sidecar/Scripts/python.exe");
        if !python_exe.exists() {
            return Err(format!(
                "sidecar Python not found at {}; did you run `python -m venv .venv-sidecar`?",
                python_exe.display()
            ));
        }

        log::info!("spawning sidecar: {} -m sidecar", python_exe.display());

        #[allow(unused_mut)]
        let mut cmd = Command::new(&python_exe);
        cmd.args(["-m", "sidecar"])
            .current_dir(&project_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());

        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

        let stdin = child.stdin.take().ok_or("no stdin on child")?;
        let stdout = child.stdout.take().ok_or("no stdout on child")?;

        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, Value>>>>> =
            Arc::new(Mutex::new(HashMap::new()));

        // Reader thread: line-by-line JSON, demux by id.
        let pending_reader = pending.clone();
        let app_handle = app.clone();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                let line = match line {
                    Ok(l) => l,
                    Err(e) => {
                        log::warn!("sidecar stdout read error: {e}");
                        break;
                    }
                };
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                let msg: RpcMessage = match serde_json::from_str(trimmed) {
                    Ok(m) => m,
                    Err(e) => {
                        log::warn!("sidecar: invalid JSON line: {e}: {trimmed}");
                        continue;
                    }
                };
                dispatch_message(msg, &pending_reader, &app_handle);
            }
            log::warn!("sidecar reader thread exiting (stdout closed)");
        });

        Ok(Self {
            next_id: Mutex::new(1),
            stdin: Mutex::new(stdin),
            pending,
            _child: Mutex::new(child),
        })
    }

    /// Send an RPC request and await the response.
    pub async fn call(&self, method: &str, params: Value) -> Result<Value, String> {
        let id = {
            let mut guard = self.next_id.lock().unwrap();
            let id = *guard;
            *guard = guard.wrapping_add(1);
            id
        };

        let (tx, rx) = oneshot::channel();
        self.pending.lock().unwrap().insert(id, tx);

        let req = RpcRequest {
            jsonrpc: "2.0",
            id,
            method,
            params: &params,
        };
        let line = serde_json::to_string(&req).map_err(|e| e.to_string())?;

        {
            let mut stdin = self.stdin.lock().unwrap();
            writeln!(stdin, "{line}").map_err(|e| format!("sidecar stdin write: {e}"))?;
            stdin
                .flush()
                .map_err(|e| format!("sidecar stdin flush: {e}"))?;
        }

        let received = tokio::time::timeout(Duration::from_secs(30), rx)
            .await
            .map_err(|_| {
                // Clean up pending slot on timeout.
                self.pending.lock().unwrap().remove(&id);
                format!("sidecar RPC '{method}' timed out after 30s")
            })?
            .map_err(|_| format!("sidecar channel closed during '{method}'"))?;

        match received {
            Ok(value) => Ok(value),
            Err(err_obj) => Err(format!("sidecar error: {err_obj}")),
        }
    }
}

fn dispatch_message<R: Runtime>(
    msg: RpcMessage,
    pending: &Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, Value>>>>>,
    app: &AppHandle<R>,
) {
    // Response path: id present.
    if let Some(id) = msg.id {
        let Some(tx) = pending.lock().unwrap().remove(&id) else {
            log::warn!("sidecar: response for unknown id {id}");
            return;
        };
        let payload = if let Some(result) = msg.result {
            Ok(result)
        } else if let Some(err) = msg.error {
            Err(err)
        } else {
            Err(serde_json::json!({"code": -32603, "message": "empty response"}))
        };
        let _ = tx.send(payload);
        return;
    }

    // Notification path: method present, no id.
    if let Some(method) = msg.method {
        let params = msg.params.unwrap_or(Value::Null);
        let payload = serde_json::json!({
            "event": method,
            "params": params,
        });
        if let Err(e) = app.emit("sidecar-event", payload) {
            log::warn!("failed to emit sidecar-event: {e}");
        }
        return;
    }

    log::warn!("sidecar: message with neither id nor method (ignored)");
}
