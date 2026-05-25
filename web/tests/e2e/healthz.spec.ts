import { test, expect } from "@playwright/test";

// Session 0005 placeholder UI-E2E. There is no dashboard yet; this test
// just asserts the harness's local API stack is reachable. Real UI
// specs land per-session from 0009 onward.

test("api /healthz responds 200 ok", async ({ request }) => {
  const r = await request.get("/healthz");
  expect(r.status()).toBe(200);
  expect(await r.json()).toEqual({ status: "ok" });
});
