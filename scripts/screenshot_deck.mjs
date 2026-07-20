// Full-deck visual screenshot crawler for design/QA review.
// Loads the deck in headless Chromium, navigates slide-by-slide via the
// app's own hash-based routing (so lazy-loaded images/videos populate
// correctly), and captures one PNG per slide plus a manifest (template
// classes, --fit value) and any console warnings/errors (including the
// [fit] overflow signal from assets/js/main.js).
//
// Usage:
//   node scripts/screenshot_deck.mjs [--viewport 3840x2160] [--out audit-scratch/screenshots-4k] [--only 2,47,63]
//   (after `npx playwright install chromium`)

import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const INDEX = "file://" + path.join(ROOT, "index.html");

function argFor(args, name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
}

function parseViewport(s) {
  const [width, height] = s.split("x").map(Number);
  return { width, height };
}

async function main() {
  const args = process.argv.slice(2);
  const OUT = path.resolve(ROOT, argFor(args, "--out") || "audit-scratch/screenshots");
  const ONLY = (argFor(args, "--only") || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number);
  const VIEWPORT = parseViewport(argFor(args, "--viewport") || "3840x2160");

  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 1 });

  const consoleEvents = [];
  page.on("console", (msg) => {
    if (msg.type() === "warning" || msg.type() === "error") {
      consoleEvents.push({ type: msg.type(), text: msg.text() });
    }
  });
  page.on("pageerror", (err) => consoleEvents.push({ type: "pageerror", text: String(err) }));

  await page.goto(INDEX);
  await page.waitForFunction(() => document.body.classList.contains("ready"));

  const total = await page.evaluate(() => document.querySelectorAll(".slide").length);
  const targets = ONLY.length ? ONLY : Array.from({ length: total }, (_, i) => i + 1);
  const manifest = [];

  for (const n of targets) {
    await page.evaluate((idx) => {
      location.hash = "#" + idx;
    }, n);
    await page.waitForFunction(
      (idx) => document.querySelectorAll(".slide")[idx - 1]?.classList.contains("active"),
      n
    );
    await page
      .waitForFunction(
        () => {
          const active = document.querySelector(".slide.active");
          if (!active) return false;
          const imgs = active.querySelectorAll("img[src]:not([src=''])");
          return Array.from(imgs).every((img) => img.complete && img.naturalWidth > 0);
        },
        { timeout: 5000 }
      )
      .catch(() => {});
    // The deck's own CSS animates the slide swap (--dur: 820ms opacity/transform
    // on .slide.active) and then staggers each .reveal/.reveal-d1..d4 content
    // block in on top of that (up to .38s delay + .8s duration, i.e. settles
    // ~1.18s after .active is applied). Screenshotting before this finishes
    // captures a mid-fade frame — ghosted previous-slide content and
    // near-invisible reveal text that look like bugs but aren't. Wait for the
    // deck to report itself fully settled before capturing.
    await page
      .waitForFunction(
        () => {
          const active = document.querySelector(".slide.active");
          if (!active || parseFloat(getComputedStyle(active).opacity) < 0.999) return false;
          const reveals = active.querySelectorAll(".reveal, .reveal-fast");
          return Array.from(reveals).every((el) => parseFloat(getComputedStyle(el).opacity) >= 0.98);
        },
        { timeout: 4000 }
      )
      .catch(() => {});
    await page.evaluate(() => {
      document.querySelectorAll(".slide.active video").forEach((v) => v.pause());
    });
    await page.waitForTimeout(250);

    const meta = await page.evaluate((idx) => {
      const slide = document.querySelectorAll(".slide")[idx - 1];
      const inner = slide.querySelector(".slide-inner");
      return {
        index: idx,
        id: slide.id,
        section: slide.getAttribute("data-section"),
        classes: Array.from(slide.classList),
        photoCount: slide.querySelectorAll(".media-full").length,
        fit: inner ? getComputedStyle(inner).getPropertyValue("--fit").trim() : null,
      };
    }, n);
    manifest.push(meta);

    const tplTag = meta.classes.find((c) => c.startsWith("tpl-")) || "tpl-unknown";
    const fname = `slide-${String(n).padStart(3, "0")}-${meta.id}-${tplTag}.png`;
    await page.screenshot({ path: path.join(OUT, fname) });
  }

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
  fs.writeFileSync(path.join(OUT, "console.json"), JSON.stringify(consoleEvents, null, 2));
  await browser.close();

  console.log(`Captured ${targets.length} slide(s) at ${VIEWPORT.width}x${VIEWPORT.height} -> ${OUT}`);
  const fitWarnings = consoleEvents.filter((e) => e.text.startsWith("[fit]"));
  if (fitWarnings.length) {
    console.log(`${fitWarnings.length} [fit] overflow warning(s) — see console.json`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
