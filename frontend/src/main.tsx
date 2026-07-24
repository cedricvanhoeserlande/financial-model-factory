import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { PaintShowcase } from "./showcase/PaintShowcase";
import "./styles.css";
import "./showcase/paintShowcase.css";

const isPaintShowcase = window.location.pathname.replace(/\/$/, "") === "/showcase/paint";

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {isPaintShowcase ? <PaintShowcase /> : <App />}
  </React.StrictMode>
);
