"""Blitztext Sidecar — Python backend for the Tauri desktop app.

Communicates with the Tauri shell via JSON-RPC 2.0 over stdin/stdout
(line-delimited JSON). Owns the SQLite store for meetings, runs the
transcription + diarization pipeline, and brokers calls to local Ollama
for LLM cleanup.

See sidecar/rpc_schema.md for the RPC contract.
"""

# Bewusst leer: der Re-Export von `__version__` hatte keinen Aufrufer und
# zog `sidecar.rpc` bei jedem `import sidecar` mit. Die Version steht in
# `sidecar/rpc.py` (und wird von `tests/test_rpc.py` gegen die drei anderen
# Stellen abgeglichen).
