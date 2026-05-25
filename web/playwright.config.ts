import { defineConfig } from "@playwright/test";

// Session 0005 — Playwright config for the UI-E2E harness layer.
// The local API stack is started by ci/src/ci/start_local_stack.py, which
// sets PLAYWRIGHT_BASE_URL on the env it passes to `npx playwright test`.
// We do NOT use Playwright's own `webServer` because the harness owns the
// uvicorn lifecycle (it has to inject PF QA env vars first).

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8000",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [["list"]],
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
