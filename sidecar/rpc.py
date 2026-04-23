"""JSON-RPC 2.0 server over stdin/stdout (line-delimited JSON).

This is the ONLY communication channel between the Tauri shell (Rust) and the
Python backend. Requests arrive on stdin, one JSON object per line. Responses
and server-initiated notifications go out on stdout, one JSON object per line.

Design notes
------------
* No ports, no sockets. Tied to process lifetime — Tauri spawns the sidecar,
  reads/writes its pipes, kills it on shutdown.
* Blocking dispatch for MVP. Long-running methods (e.g. `meeting.import_file`)
  should offload to a worker thread themselves and use `emit_event(...)` to
  push progress notifications to the Tauri side.
* No authentication — the pipe is a private process channel.

Methods are registered via the @method decorator. See sidecar/rpc_schema.md
for the authoritative list.
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
from typing import Any, Callable

__version__ = "0.1.0-alpha"

# -- Registry ---------------------------------------------------------------

_methods: dict[str, Callable[..., Any]] = {}


def method(name: str | None = None):
    """Register a function as a JSON-RPC method.

    Usage:
        @method("meeting.list")
        def list_meetings(limit: int = 50, offset: int = 0): ...
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        key = name or fn.__name__
        if key in _methods:
            raise RuntimeError(f"duplicate RPC method registration: {key}")
        _methods[key] = fn
        return fn

    return deco


# -- Errors -----------------------------------------------------------------

# Standard JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Application-specific codes (range -32000 .. -32099 is reserved for us)
APP_PIPELINE_FAILED = -32001
APP_NOT_FOUND = -32002
APP_DEPENDENCY_MISSING = -32003


class RpcError(Exception):
    """Raise from a method to return a structured JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# -- I/O --------------------------------------------------------------------

# Writes to stdout must be serialized — both dispatch responses and event
# notifications share the same pipe.
_write_lock = threading.Lock()


def _write(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    with _write_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def emit_event(name: str, payload: dict | None = None) -> None:
    """Push a server-initiated JSON-RPC notification to the Tauri side.

    Notifications have a `method` but NO `id`, per JSON-RPC spec. The Rust
    layer rebroadcasts these via `window.emit("sidecar-event", ...)` to the
    React frontend.
    """
    _write(
        {
            "jsonrpc": "2.0",
            "method": name,
            "params": payload or {},
        }
    )


def _error_response(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# -- Dispatch ---------------------------------------------------------------


def _dispatch(req: dict) -> dict | None:
    """Run one request. Returns the response dict, or None for notifications."""
    req_id = req.get("id")  # may be None (notification)
    method_name = req.get("method")
    params = req.get("params", {})

    if not isinstance(method_name, str) or not method_name:
        return _error_response(req_id, INVALID_REQUEST, "missing or invalid 'method'")

    fn = _methods.get(method_name)
    if fn is None:
        return _error_response(
            req_id, METHOD_NOT_FOUND, f"method '{method_name}' not found"
        )

    try:
        if isinstance(params, dict):
            result = fn(**params)
        elif isinstance(params, list):
            result = fn(*params)
        elif params is None:
            result = fn()
        else:
            return _error_response(
                req_id, INVALID_PARAMS, "'params' must be object, array, or omitted"
            )
    except RpcError as e:
        return _error_response(req_id, e.code, e.message, e.data)
    except TypeError as e:
        # Most often: bad arg names / arity
        return _error_response(req_id, INVALID_PARAMS, str(e))
    except Exception as e:  # noqa: BLE001 — we want to catch everything
        return _error_response(
            req_id,
            INTERNAL_ERROR,
            str(e) or e.__class__.__name__,
            data={"traceback": traceback.format_exc()},
        )

    if req_id is None:
        return None  # notification — spec says no response
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve_stdio() -> None:
    """Read requests from stdin forever, write responses to stdout.

    Exits cleanly when stdin is closed (i.e. parent process terminated the
    pipe). Errors during dispatch are converted to JSON-RPC errors and do
    not crash the server.
    """
    # Unbuffered line-mode on stdout is important — the Rust side reads
    # line-by-line and would deadlock if Python held lines in a buffer.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except AttributeError:
        pass

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _write(_error_response(None, PARSE_ERROR, f"invalid JSON: {e}"))
            continue
        if isinstance(req, list):
            # Batch — process each, emit array response (MVP: serial)
            responses = [r for r in (_dispatch(item) for item in req) if r is not None]
            if responses:
                _write(responses)  # type: ignore[arg-type]
        elif isinstance(req, dict):
            response = _dispatch(req)
            if response is not None:
                _write(response)
        else:
            _write(_error_response(None, INVALID_REQUEST, "top-level must be object or array"))


# -- Built-in methods -------------------------------------------------------


@method("ping")
def _ping() -> dict:
    """Health check. Returns sidecar version. Used by Tauri on startup."""
    return {"ok": True, "version": __version__}


# -- In-process invocation (for tests and pipeline internals) --------------


def call_method(name: str, params: dict | None = None) -> Any:
    """Call a registered RPC method synchronously, in the same process.

    Useful for:
    * smoke tests that want to exercise the same dispatch path as Tauri,
    * pipeline steps that want to reuse a method (e.g. run cleanup on
      turns that were just imported).

    Raises ``RpcError`` for RPC-level errors, or whatever the method itself
    raises for unexpected failures.
    """
    fn = _methods.get(name)
    if fn is None:
        raise RpcError(METHOD_NOT_FOUND, f"method '{name}' not found")
    params = params or {}
    return fn(**params)
