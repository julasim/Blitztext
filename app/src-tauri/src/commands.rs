//! Tauri invoke handlers exposed to the frontend.
//!
//! Intentionally thin: we expose ONE generic `rpc` command that proxies
//! any JSON-RPC method to the Python sidecar. Typed schemas live on the
//! Python side (source of truth) and in the TypeScript mirror —
//! Rust stays transport-only.

use serde_json::Value;
use tauri::State;

use crate::sidecar::SidecarHandle;

#[tauri::command]
pub async fn rpc(
    handle: State<'_, SidecarHandle>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    handle.call(&method, params.unwrap_or(Value::Null)).await
}
