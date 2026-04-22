"""Blitztext Sidecar — Python backend for the Tauri desktop app.

Communicates with the Tauri shell via JSON-RPC 2.0 over stdin/stdout
(line-delimited JSON). Owns the SQLite store for meetings, runs the
transcription + diarization pipeline, and brokers calls to local Ollama
for LLM cleanup.

See sidecar/rpc_schema.md for the RPC contract.
"""

from sidecar.rpc import __version__

__all__ = ["__version__"]
