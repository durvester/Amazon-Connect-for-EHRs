import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // E2E specs are driven by Playwright, not Vitest. See playwright.config.ts.
    exclude: ["node_modules/**", "tests/e2e/**"],
  },
});
