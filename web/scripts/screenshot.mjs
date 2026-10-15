/* global document, window */
// Start the API on :8000 and Vite on :5173 before running npm run screenshot.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--host-resolver-rules=MAP localhost 127.0.0.1"],
});
await mkdir(new URL("../shots/", import.meta.url), { recursive: true });
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
  await page.waitForFunction(
    () =>
      Number(
        document.querySelector(".shared-clock")?.textContent?.split(":")[0],
      ) >= 20 &&
      document.querySelectorAll('[data-testid="cue-card"]').length >= 2,
    undefined,
    { timeout: 240000 },
  );
  await page.locator(".casual .whatif").waitFor({ timeout: 240000 });
  await page.getByRole("button", { name: "Pause", exact: true }).waitFor();
  await page.screenshot({
    path: new URL("../e2e-screenshot.png", import.meta.url).pathname,
    fullPage: false,
  });
  async function checkLayout() {
    assert.equal(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
            document.documentElement.clientWidth &&
          document.documentElement.scrollHeight <= window.innerHeight,
      ),
      true,
      "no horizontal overflow or vertical clipping",
    );
  }
  await checkLayout();
  await page.setViewportSize({ width: 1440, height: 900 });
  await checkLayout();
  await page.screenshot({
    path: new URL("../shots/main.png", import.meta.url).pathname,
  });

  await page.getByRole("button", { name: /Stop Tactics/ }).click();
  await page.waitForFunction(
    () => {
      return (
        Boolean(
          document.querySelector(".agent-grid > div:nth-child(3) .recovering"),
        ) && Boolean(document.querySelector(".casual .whatif"))
      );
    },
    undefined,
    { timeout: 60000 },
  );
  await checkLayout();
  await page.getByRole("button", { name: "Pause" }).waitFor();
  await page.screenshot({
    path: new URL("../shots/kill.png", import.meta.url).pathname,
  });
  await page.getByRole("button", { name: "Pause" }).waitFor();
  await page.getByText("Handoffs and recovery history").click();
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
  await page.getByRole("link", { name: "About" }).click();
  assert.equal(await page.getByLabel("Replay controls").count(), 0);
  assert.equal(
    await page.getByRole("button", { name: "Pause", exact: true }).count(),
    0,
  );
  assert.equal(
    await page.evaluate(() => {
      const card = document.querySelector(".about").getBoundingClientRect();
      const copy = document
        .querySelector(".about-copy")
        .getBoundingClientRect();
      return (
        Math.abs(card.left - (window.innerWidth - card.width) / 2) < 1 &&
        card.width <= 1392 &&
        copy.width <= 720
      );
    }),
    true,
    "About uses a centred full-width card and readable text column",
  );
  await page
    .getByRole("heading", { name: "One match. An entire AI crew." })
    .waitFor();
  await checkLayout();
  await page.screenshot({
    path: new URL("../shots/about.png", import.meta.url).pathname,
  });
  assert.deepEqual(errors, [], "browser should have no uncaught errors");
  console.log(
    "Playing split view, persistent What-If, synced clocks, kill/recover and /about passed; screenshot saved to web/e2e-screenshot.png",
  );
} finally {
  await browser.close();
}
