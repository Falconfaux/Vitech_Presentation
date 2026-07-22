// Post-build overflow check for index.html.
// Loads the deck in headless Chromium at several representative window
// sizes and confirms no slide's .slide-inner content overflows its box
// (which would force a user to scroll to see the whole slide).
//
// Usage: node scripts/check_overflow.mjs   (after `npx playwright install chromium`)

import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const INDEX = "file://" + path.join(ROOT, "index.html");
const TOLERANCE = 3; // px

const VIEWPORTS = [
  { width: 1920, height: 1080 }, // 55" boardroom TV (1080p) — also the min-width:1900 TV breakpoint
  { width: 1728, height: 1117 }, // 16" MacBook Pro (16:10) default scaling
  { width: 1512, height: 982 },  // 16" MacBook Pro (16:10) more-space scaling / small 16"
  { width: 1600, height: 900 },
  { width: 1366, height: 768 },
  { width: 1280, height: 800 },
];

async function main() {
  const browser = await chromium.launch();
  let violations = [];

  for (const viewport of VIEWPORTS) {
    const page = await browser.newPage({ viewport });
    await page.goto(INDEX);
    await page.waitForFunction(() => document.body.classList.contains("ready"));
    // main.js re-runs its fit pass once web fonts finish swapping in (a
    // fallback-font measurement taken too early can under- or over-shrink
    // slides that sit close to the fit threshold) — wait for that same
    // signal so this check measures the settled layout, not a race.
    await page.evaluate(() => document.fonts && document.fonts.ready);
    await page.waitForTimeout(150);

    const results = await page.$$eval(".slide-inner", (nodes) =>
      nodes.map((inner) => {
        const slide = inner.closest(".slide");
        return {
          id: slide ? slide.id : "?",
          overflow: Math.round(inner.scrollHeight - inner.clientHeight),
        };
      })
    );

    for (const r of results) {
      if (r.overflow > TOLERANCE) {
        violations.push({ viewport: `${viewport.width}x${viewport.height}`, id: r.id, overflow: r.overflow });
      }
    }

    await page.close();
  }

  await browser.close();

  if (violations.length) {
    console.log(`${violations.length} violation(s):`);
    for (const v of violations) {
      console.log(` - ${v.viewport}  slide ${v.id}  overflow ${v.overflow}px`);
    }
    console.log(`\nOverflow check: ${violations.length} violation(s) across ${VIEWPORTS.length} viewports`);
    process.exit(1);
  }

  console.log(`Overflow check: PASS — 0 slides overflow at any of ${VIEWPORTS.length} tested viewports`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
