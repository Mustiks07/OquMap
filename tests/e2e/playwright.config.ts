import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.OQUMAP_WEB_URL ?? "http://localhost:4173",
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    trace: "off",
  },
});
