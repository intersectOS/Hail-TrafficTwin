import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { App } from "./App";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
const cinema = new URLSearchParams(window.location.search).get("cinema");
// Cinema mode (Track E): film frames for the movie pipeline; the normal viewer is untouched.
if (cinema) import("./cinema").then((m) => m.mountCinema(root, cinema));
else createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
