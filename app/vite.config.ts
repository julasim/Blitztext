import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Avoid multiple React instances — important when third-party libs
  // (zustand, @tauri-apps/*) sometimes pull in their own React ref.
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  // Tauri dev specifics — fixed port + no clearing the console so Rust
  // errors stay visible.
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: "127.0.0.1",
    hmr: {
      host: "127.0.0.1",
    },
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
});
