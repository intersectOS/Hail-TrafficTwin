import { existsSync } from "node:fs";
import { defineConfig } from "vite";

// API target: VITE_API_TARGET, else the compose service name inside Docker, else localhost.
const target = process.env.VITE_API_TARGET || (existsSync("/.dockerenv") ? "http://api:8000" : "http://localhost:8000");

export default defineConfig({
  // React via esbuild's automatic JSX runtime (no plugin needed; no fast refresh).
  esbuild: { jsx: "automatic" },
  server: {
    port: 5173,
    proxy: {
      "/api": { target, changeOrigin: true },
      "/health": { target, changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      "/api": { target, changeOrigin: true },
      "/health": { target, changeOrigin: true },
    },
  },
  build: { chunkSizeWarningLimit: 3000, sourcemap: false },
});
