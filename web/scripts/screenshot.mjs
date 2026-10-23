/* global document, window */
// Start the API on :8000 and Vite on :5173 before running npm run screenshot.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
const evidenceDir = process.env.PLAYMAKERS_SHOTS_DIR;
const shot = (name) =>
  evidenceDir
    ? join(evidenceDir, name)
    : fileURLToPath(new URL(name === "e2e-screenshot.png" ? `../${name}` : `../shots/${name}`, import.meta.url));
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--host-resolver-rules=MAP localhost 127.0.0.1"],
});
await mkdir(evidenceDir ?? new URL("../shots/", import.meta.url), { recursive: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(process.env.PLAYMAKERS_WEB_URL || "http://localhost:5173");
  assert.equal(await page.title(), "Playmakers — Inside the synthetic game");
  await page.getByRole("img", { name: "Playmakers", exact: true }).waitFor();
  await page.getByLabel("REPLAY SPEED").selectOption("50");
  await page.waitForFunction(
    () =>
      document.querySelector(".casual .lower-thirds h3")?.textContent?.startsWith("GOAL") &&
      Boolean(document.querySelector(".casual .whatif")),
    undefined,
    { timeout: 60000 },
  );
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    await checkLayout();
    await page.screenshot({ path: shot(`goal-whatif-${viewport.width}.png`) });
  }
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await page
    .getByRole("region", { name: "ANALYST view" })
    .getByRole("heading", { name: "Passing under pressure" })
    .waitFor({ timeout: 60000 });
  await page
    .getByRole("region", { name: "FAN view" })
    .getByText(/From events.*Verified/)
    .first()
    .waitFor({ timeout: 60000 });
  await page
    .locator(".rail-heading")
    .getByText(/Offline mock model/)
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
    path: shot("e2e-screenshot.png"),
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
    const overflowingPanels = await page.locator(".view-body:not(:has(.recap)):not(.explaining)").evaluateAll(
      (panels) => panels.flatMap((panel) =>
        panel.scrollHeight > panel.clientHeight + 1 ||
        panel.scrollWidth > panel.clientWidth + 1
          ? [panel.closest(".view").getAttribute("aria-label")]
          : [],
      ),
    );
    assert.deepEqual(overflowingPanels, [], "normal feed panels fit without internal scrolling");
  }
  await checkLayout();
  await page.setViewportSize({ width: 1440, height: 900 });
  await checkLayout();
  await page.screenshot({
    path: shot("main.png"),
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
    path: shot("kill.png"),
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
    .getByRole("heading", { name: "One match. A whole production crew." })
    .waitFor();
  await checkLayout();
  await page.screenshot({
    path: shot("about.png"),
  });
  assert.deepEqual(errors, [], "browser should have no uncaught errors");
  console.log(
    "Playing split view, persistent What-If, synced clocks, kill/recover and /about passed; screenshots saved to " + (evidenceDir ?? "web/"),
  );
} finally {
  await browser.close();
}
