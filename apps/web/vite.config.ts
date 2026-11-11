/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.OQUMAP_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: { "/api": apiTarget, "/health": apiTarget },
  },
  preview: { host: "0.0.0.0", port: 4173, proxy: { "/api": apiTarget, "/health": apiTarget } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
