// Thin wrappers around Tauri's invoke + event system.
//
// The single `rpc` Tauri command delegates to the Python sidecar via
// JSON-RPC (see sidecar/rpc_schema.md). The sidecar can also push
// notifications — those arrive on the "sidecar-event" window event with
// a { event, params } envelope.

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

/**
 * Call a JSON-RPC method on the Python sidecar.
 *
 * @example
 *   const res = await call<{ok: boolean; version: string}>("ping");
 */
export async function call<T = unknown>(
  method: string,
  params: Record<string, unknown> | unknown[] | null = null,
): Promise<T> {
  return invoke<T>("rpc", { method, params });
}

export type SidecarEventEnvelope = {
  event: string; // e.g. "meeting.progress"
  params: Record<string, unknown>;
};

/**
 * Subscribe to sidecar-initiated notifications, filtered by event name.
 * Returns an unsubscribe function.
 */
export async function onEvent<P = Record<string, unknown>>(
  name: string,
  handler: (params: P) => void,
): Promise<UnlistenFn> {
  return listen<SidecarEventEnvelope>("sidecar-event", (evt) => {
    if (evt.payload.event === name) {
      handler(evt.payload.params as P);
    }
  });
}
