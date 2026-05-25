import { test, expect } from "@playwright/test";

/**
 * Session 0008 — real SMART-on-FHIR authorization-code grant against
 * Practice Fusion QA.
 *
 * The local FastAPI is started by ``ci.start_local_stack --onboarding``
 * on http://localhost:8080 (the Veradigm-registered redirect URI).
 * The harness mocks AWS via moto and stubs the Connect DID claim — only
 * Practice Fusion is real.
 *
 * What this spec does:
 *   1. GET /oauth/start with the QA provider-app params → 302 to PF
 *   2. Fill in PF login (PF_QA_USERNAME / PF_QA_PASSWORD from env)
 *   3. Enter the QA 2FA code (hardcoded "12345" — QA-only)
 *   4. Click the consent / Allow button
 *   5. PF redirects to /oauth/callback with the auth code
 *   6. Our callback exchanges + persists, returning the stubbed DID
 *
 * Skipped when PF_QA_USERNAME / PF_QA_PASSWORD aren't set so the
 * unauthenticated CI lane stays green.
 */

const REQUIRED_ENV = [
  "PF_QA_USERNAME",
  "PF_QA_PASSWORD",
  "PF_FHIR_BASE_URL",
  "PF_CLIENT_ID",
] as const;

const missing = REQUIRED_ENV.filter((k) => !process.env[k]);

test.describe("OAuth onboarding against PF QA", () => {
  test.skip(
    missing.length > 0,
    `OAuth E2E skipped — missing env vars: ${missing.join(", ")}`,
  );

  test("full SMART code grant + onboarding callback", async ({ page }) => {
    // Slower than the default — the PF QA login + 2FA flow has multiple
    // page loads and the redirect chain is non-trivial.
    test.setTimeout(120_000);

    const PF_QA_USERNAME = process.env.PF_QA_USERNAME!;
    const PF_QA_PASSWORD = process.env.PF_QA_PASSWORD!;
    const PF_FHIR_BASE_URL = process.env.PF_FHIR_BASE_URL!;
    const PF_CLIENT_ID = process.env.PF_CLIENT_ID!;
    // The harness writes the moto-backed Secrets Manager ARN here.
    const PF_CLIENT_SECRET_ARN =
      process.env.LOCAL_PF_CLIENT_SECRET_ARN ??
      "arn:aws:secretsmanager:us-east-1:000000000000:secret:pf-voice-local-pf-client-secret";

    // ── Step 1: kick off /oauth/start ────────────────────────────────
    const params = new URLSearchParams({
      practice_id: "pf-qa-e2e-test",
      fhir_base_url: PF_FHIR_BASE_URL,
      pf_client_id: PF_CLIENT_ID,
      pf_client_secret_arn: PF_CLIENT_SECRET_ARN,
    });
    await page.goto(`/oauth/start?${params.toString()}`);

    // ── Step 2: PF login screen ──────────────────────────────────────
    // Generic selectors (works against most SMART login UIs).
    const userField = page
      .locator(
        'input[name="username"], input[name="email"], input[type="email"], input#username',
      )
      .first();
    await userField.waitFor({ state: "visible", timeout: 30_000 });
    await userField.fill(PF_QA_USERNAME);

    const passField = page
      .locator('input[name="password"], input[type="password"], input#password')
      .first();
    await passField.fill(PF_QA_PASSWORD);

    const signInBtn = page
      .locator(
        'button[type="submit"], input[type="submit"], button:has-text("Sign in"), ' +
          'button:has-text("Log in"), button:has-text("Continue")',
      )
      .first();
    await signInBtn.click();

    // ── Step 3: PF "Security check" — hash-routed multi-step SPA ─────
    // PF's auth UI is a hash-routed SPA. The flow we have to handle:
    //   #/securitycheck     → "We don't recognize this browser" + Send code btn
    //   (after Send code)    → "Security code" page with spinbutton + Log in
    //   #/securityconfirm   → confirm + continue (sometimes shown)
    // Trusted browsers may skip these entirely.
    try {
      await page.waitForURL(/#\/securitycheck/, { timeout: 15_000 });
      const sendCodeBtn = page.getByRole("button", { name: /^send code$/i });
      await sendCodeBtn.waitFor({ state: "visible", timeout: 15_000 });
      await sendCodeBtn.click();
    } catch {
      // Browser is already trusted — skip the security-check page.
    }

    // After "Send code", the "Security code" entry page appears. The
    // field is a <input type="number"> (ARIA spinbutton) labelled
    // "Security code"; submit is "Log in". QA delivers code "12345".
    try {
      const codeField = page.getByRole("spinbutton", { name: /security code/i });
      await codeField.waitFor({ state: "visible", timeout: 30_000 });
      await codeField.fill("12345");
      // Submit by pressing Enter inside the field — the "Log in"
      // button label collides with the original login page's button
      // and strict-mode matching is brittle across the two pages.
      await codeField.press("Enter");
    } catch {
      // Trusted browser path skipped the code field entirely.
    }

    // Some flows route through a "#/securityconfirm" confirmation page
    // before continuing. Click any "Continue"/"Confirm" button if shown.
    try {
      await page.waitForURL(/#\/securityconfirm/, { timeout: 10_000 });
      const confirmBtn = page
        .getByRole("button", { name: /continue|confirm|ok|proceed/i })
        .first();
      await confirmBtn.waitFor({ state: "visible", timeout: 10_000 });
      await confirmBtn.click();
    } catch {
      // Confirm page not shown — fine.
    }

    // ── Step 4: consent / Allow ──────────────────────────────────────
    const consentBtn = page
      .locator(
        'button:has-text("Allow"), button:has-text("Authorize"), ' +
          'button:has-text("Approve"), button:has-text("Accept"), ' +
          'button:has-text("Continue")',
      )
      .first();
    try {
      await consentBtn.waitFor({ state: "visible", timeout: 20_000 });
      await consentBtn.click();
    } catch {
      // Consent screen may not appear if previously granted.
    }

    // ── Step 5: land on /oauth/callback ──────────────────────────────
    await page.waitForURL(/\/oauth\/callback\b/, { timeout: 60_000 });

    // ── Step 6: assert the callback response shape ───────────────────
    const body = await page.textContent("body");
    expect(body, "callback response body").not.toBeNull();
    const parsed = JSON.parse(body!);
    expect(parsed.practice_id).toBe("pf-qa-e2e-test");
    expect(parsed.status).toBe("onboarded");
    expect(parsed.phone_number).toMatch(/^\+\d{10,15}$/);
  });
});
