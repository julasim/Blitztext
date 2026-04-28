// Single React entry; Tauri spawns this same bundle for every window.
// We branch on the ?widget= URL parameter so the floating recorder gets
// a much smaller component tree without dragging the full library along.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";

import "./styles/tokens.css";
import "./index.css";

import App from "./App.tsx";
import { MiniWidget } from "./components/MiniWidget";

const widget = new URLSearchParams(window.location.search).get("widget");

createRoot(document.getElementById("root")!).render(
  <StrictMode>{widget === "mini" ? <MiniWidget /> : <App />}</StrictMode>,
);
