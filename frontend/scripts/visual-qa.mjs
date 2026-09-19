import { mkdir, writeFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "playwright-core";

const baseUrl = process.env.QA_BASE_URL ?? "http://127.0.0.1:5173";
const executablePath = process.env.QA_BROWSER_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const outputDirectory = "artifacts/visual";
const viewports = [320, 375, 390, 430, 768, 1024, 1280, 1440, 1920];
const onePixelPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z4eIAAAAASUVORK5CYII=",
  "base64"
);

await mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const report = [];

async function configureApi(page) {
  let cardNumber = 0;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    if (request.url().endsWith("/api/batches") && request.method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "batch-qa",
          status: "UPLOADED",
          total_cards: 2,
          processed_cards: 0,
          successful_cards: 0,
          failed_cards: 0,
          created_at: "2026-09-19T00:00:00Z",
          completed_at: null
        })
      });
      return;
    }
    if (request.url().includes("/cards") && request.method() === "POST") {
      cardNumber += 1;
      const failed = cardNumber === 2;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: `lead-${cardNumber}`,
          batch_id: "batch-qa",
          source_filename: failed ? "low-contrast.png" : "mina-patel.png",
          first_name: failed ? null : "Mina",
          last_name: failed ? null : "Patel",
          job_title: failed ? null : "Design Director",
          company: failed ? null : "Northstar Studio",
          location: failed ? null : "Bengaluru",
          phone_number: failed ? null : "+919876543210",
          email: failed ? null : "mina@northstar.example",
          status: failed ? "FAILED" : "SUCCESS",
          warnings: failed ? ["Low contrast"] : [],
          error_message: failed ? "The text contrast is too low for a confident extraction." : null,
          created_at: "2026-09-19T00:00:00Z",
          updated_at: "2026-09-19T00:00:00Z"
        })
      });
      return;
    }
    await route.fulfill({ status: 204, body: "" });
  });
}

async function layoutResult(page, viewport, state, theme) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    theme: document.documentElement.dataset.theme
  }));
  const overflow = metrics.scrollWidth > metrics.clientWidth;
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const violations = axe.violations.filter((item) => item.impact === "serious" || item.impact === "critical");
  report.push({
    viewport,
    state,
    theme,
    overflow,
    seriousOrCriticalA11yViolations: violations.map((item) => item.id),
    ...metrics
  });
  if (overflow) throw new Error(`Horizontal overflow at ${viewport}px in ${state}/${theme}`);
  if (violations.length) {
    console.error(JSON.stringify(violations.map((item) => ({
      id: item.id,
      nodes: item.nodes.map((node) => ({ target: node.target, summary: node.failureSummary }))
    })), null, 2));
    throw new Error(`Accessibility violations at ${viewport}px in ${state}/${theme}: ${violations.map((item) => item.id).join(", ")}`);
  }
}

try {
  for (const width of viewports) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await configureApi(page);
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.screenshot({ path: `${outputDirectory}/empty-light-${width}.png`, fullPage: true });
    await layoutResult(page, width, "empty", "light");

    if (width === 390 || width === 1440) {
      await page.getByRole("button", { name: "Switch to dark theme" }).click();
      await page.waitForFunction(() => getComputedStyle(document.body).backgroundColor === "rgb(16, 23, 21)");
      await page.screenshot({ path: `${outputDirectory}/empty-dark-${width}.png`, fullPage: true });
      await layoutResult(page, width, "empty", "dark");
      await page.getByRole("button", { name: "Switch to light theme" }).click();
      await page.waitForFunction(() => getComputedStyle(document.body).backgroundColor === "rgb(241, 238, 231)");

      await page.getByLabel("Choose business card images").setInputFiles([
        { name: "mina-patel.png", mimeType: "image/png", buffer: onePixelPng },
        { name: "low-contrast.png", mimeType: "image/png", buffer: onePixelPng }
      ]);
      await page.screenshot({ path: `${outputDirectory}/selected-light-${width}.png`, fullPage: true });
      await layoutResult(page, width, "selected", "light");

      await page.getByRole("button", { name: "Extract leads" }).click();
      await page.getByText("1 lead ready").waitFor();
      await page.screenshot({ path: `${outputDirectory}/review-partial-${width}.png`, fullPage: true });
      await layoutResult(page, width, "partial-review", "light");
    }
    await context.close();
  }
  await writeFile(`${outputDirectory}/report.json`, `${JSON.stringify(report, null, 2)}\n`);
  console.log(`Visual QA passed for ${report.length} viewport/state/theme combinations.`);
} finally {
  await browser.close();
}
