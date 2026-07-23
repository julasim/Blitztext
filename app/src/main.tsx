// React-Einstieg. Ein Fenster, eine Wurzel — das schwebende Aufnahme-Widget
// ist mit dem Mikrofon-Modus entfallen.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Schriften kommen über index.css (@import) — nicht zusätzlich hier laden.
import "./styles/tokens.css";
import "./index.css";

import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
