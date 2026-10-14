/* global document */
// Start the API on :8000 and Vite on :5173 before running npm run screenshot.
import { chromium } from "playwright";
import assert from "node:assert/strict";
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox"],
});
try {
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(process.env.GALLERY_WEB_URL || "http://localhost:5173");
  await page.getByLabel("REPLAY SPEED").selectOption("50");
  await page
    .getByRole("region", { name: "ANALYST view" })
    .getByRole("heading", { name: "Passing under pressure" })
    .waitFor({ timeout: 60000 });
  await page
    .getByRole("region", { name: "FAN view" })
    .getByText("Sigue la emoción del partido.")
    .first()
    .waitFor({ timeout: 60000 });
  await page.waitForFunction(
    () => document.querySelector(".shared-clock")?.textContent !== "00:00",
  );
  await page.getByRole("button", { name: "Ⅱ Pause" }).click();
  await page.screenshot({
    path: new URL("../e2e-screenshot.png", import.meta.url).pathname,
    fullPage: false,
  });
  assert.equal(
    await page.locator(".scorebug time").nth(0).innerText(),
    await page.locator(".scorebug time").nth(1).innerText(),
    "panel clocks must match",
  );
  await page.getByRole("button", { name: "▶ Start" }).click();
  await page.getByRole("button", { name: /Kill Tactics/ }).click();
  for (const view of ["A", "F"]) {
    for (const action of [
      "agent down",
      "fallback on",
      "restarted from checkpoint",
      "caught up",
    ]) {
      await page
        .getByRole("log")
        .locator(".trace-row")
        .filter({ hasText: action })
        .filter({
          has: page.locator("b span", { hasText: new RegExp(`^${view}$`) }),
        })
        .first()
        .waitFor({ timeout: 60000 });
    }
  }
  await page.getByRole("link", { name: "Inside Gallery ↗" }).click();
  await page
    .getByRole("heading", { name: "One match. An entire AI crew." })
    .waitFor();
  assert.deepEqual(errors, [], "browser should have no uncaught errors");
  console.log(
    "Split view, SSE content, synced clocks, pause, kill/recover and /about passed; screenshot saved to web/e2e-screenshot.png",
  );
} finally {
  await browser.close();
}
