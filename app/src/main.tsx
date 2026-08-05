// React-Einstieg: ein Fenster, eine Wurzel.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// index.css zieht Schriften und tokens.css per @import mit — hier reicht
// dieser eine Einstieg.
import "./index.css";

import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
