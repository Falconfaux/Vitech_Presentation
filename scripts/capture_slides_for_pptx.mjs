// Render every slide of the web deck to a still image for the mobile PPTX export.
//
// Drives the deck in headless Chromium exactly like scripts/screenshot_deck.mjs
// (hash-based navigation so lazy data-src media loads, waits for the reveal
// animation to settle), but tuned for building a PowerPoint:
//   * viewport is a clean 1920x1080 (scale=1.0 -> getBoundingClientRect() maps
//     1:1 to screenshot pixels, which map 1:1 to PPTX EMU at 6350 EMU/px),
//   * web-only chrome (nav arrows, counter, menu, hint) is hidden,
//   * on video slides every <video> is loaded + seeked to a real frame so the
//     captured JPEG shows a true poster (incl. the blurred backdrop), not black,
//   * a video_overlays.json is emitted giving, per slide, the exact on-screen
//     rectangle of each foreground video (object-fit: contain aware) plus the
//     rectangles of the text panels/titlebars that sit ON TOP of the video, so
//     the PPTX builder can lay the real MP4 under them and re-stamp the text.
//
// Usage: node scripts/capture_slides_for_pptx.mjs [--out MOBILE/build] [--only 9,29,105]

import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const INDEX = "file://" + path.join(ROOT, "index.html");
const VIEWPORT = { width: 1920, height: 1080 };

function argFor(args, name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
}

async function main() {
  const args = process.argv.slice(2);
  const OUT = path.resolve(ROOT, argFor(args, "--out") || "MOBILE/build");
  const SLIDES_DIR = path.join(OUT, "slides");
  const ONLY = (argFor(args, "--only") || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number);

  fs.mkdirSync(SLIDES_DIR, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 1 });

  await page.goto(INDEX);
  await page.waitForFunction(() => document.body.classList.contains("ready"));
  // Hide web-only chrome so each slide image is clean and full-bleed.
  await page.addStyleTag({
    content:
      "#chrome,#progress,#sections-panel,#lightbox,.scroll-cue{display:none !important;}",
  });
  // Let web fonts settle so text is measured/rendered with Archivo / IBM Plex.
  await page.evaluate(() => (document.fonts && document.fonts.ready) || null).catch(() => {});

  const total = await page.evaluate(() => document.querySelectorAll(".slide").length);
  const targets = ONLY.length ? ONLY : Array.from({ length: total }, (_, i) => i + 1);
  const overlays = {}; // slideIndex -> { videos: [...], chrome: [...] }

  for (const n of targets) {
    await page.evaluate((idx) => {
      location.hash = "#" + idx;
    }, n);
    await page.waitForFunction(
      (idx) => document.querySelectorAll(".slide")[idx - 1]?.classList.contains("active"),
      n
    );
    // Wait for all <img> on the active slide to finish decoding.
    await page
      .waitForFunction(
        () => {
          const active = document.querySelector(".slide.active");
          if (!active) return false;
          const imgs = active.querySelectorAll("img[src]:not([src=''])");
          return Array.from(imgs).every((img) => img.complete && img.naturalWidth > 0);
        },
        { timeout: 8000 }
      )
      .catch(() => {});
    // Wait for the slide-swap + staggered reveal animations to fully settle
    // (same signal scripts/screenshot_deck.mjs uses).
    await page
      .waitForFunction(
        () => {
          const active = document.querySelector(".slide.active");
          if (!active || parseFloat(getComputedStyle(active).opacity) < 0.999) return false;
          const reveals = active.querySelectorAll(".reveal, .reveal-fast");
          return Array.from(reveals).every((el) => parseFloat(getComputedStyle(el).opacity) >= 0.98);
        },
        { timeout: 5000 }
      )
      .catch(() => {});

    // Load + seek every video on the active slide to a real frame so the JPEG
    // captures a true poster (foreground AND blurred backdrop), then pause.
    // Returns the on-screen rectangles the PPTX builder needs.
    const rects = await page.evaluate(async () => {
      const active = document.querySelector(".slide.active");
      if (!active) return { videos: [], chrome: [] };
      const vids = Array.from(active.querySelectorAll("video"));
      await Promise.all(
        vids.map(
          (v) =>
            new Promise((resolve) => {
              let done = false;
              const finish = () => {
                if (done) return;
                done = true;
                resolve();
              };
              try {
                v.muted = true;
                if (!v.getAttribute("src")) {
                  const ds = v.getAttribute("data-src");
                  if (ds) v.setAttribute("src", ds);
                }
                const seekIt = () => {
                  v.addEventListener("seeked", finish, { once: true });
                  try {
                    v.currentTime = 0.05;
                  } catch (e) {
                    finish();
                  }
                };
                if (v.readyState >= 2) seekIt();
                else {
                  v.addEventListener("loadeddata", seekIt, { once: true });
                  v.addEventListener("error", finish, { once: true });
                  try {
                    v.load();
                  } catch (e) {
                    finish();
                  }
                }
                setTimeout(finish, 8000);
              } catch (e) {
                finish();
              }
            })
        )
      );
      vids.forEach((v) => {
        try {
          v.pause();
        } catch (e) {}
      });

      // Foreground videos only (skip decorative .media-blur backdrops, already
      // baked into the JPEG). Compute the visible video rect: object-fit:contain
      // of the intrinsic (videoWidth x videoHeight) inside the element content box.
      const videos = Array.from(active.querySelectorAll("video.media-full")).map((v) => {
        const cs = getComputedStyle(v);
        const r = v.getBoundingClientRect();
        const num = (x) => parseFloat(x) || 0;
        const bl = num(cs.borderLeftWidth),
          br = num(cs.borderRightWidth),
          bt = num(cs.borderTopWidth),
          bb = num(cs.borderBottomWidth);
        const pl = num(cs.paddingLeft),
          pr = num(cs.paddingRight),
          pt = num(cs.paddingTop),
          pb = num(cs.paddingBottom);
        const cx = r.left + bl + pl;
        const cy = r.top + bt + pt;
        const cw = r.width - bl - br - pl - pr;
        const ch = r.height - bt - bb - pt - pb;
        const vw = v.videoWidth || 1920;
        const vh = v.videoHeight || 1080;
        let x, y, w, h;
        if (cs.objectFit === "cover") {
          // fills the content box (cropped) -> overlay is the content box
          x = cx;
          y = cy;
          w = cw;
          h = ch;
        } else {
          // contain (the case for every video in this deck)
          const s = Math.min(cw / vw, ch / vh);
          w = vw * s;
          h = vh * s;
          x = cx + (cw - w) / 2;
          y = cy + (ch - h) / 2;
        }
        return {
          file: v.getAttribute("data-src") || v.getAttribute("src"),
          x: Math.round(x),
          y: Math.round(y),
          w: Math.round(w),
          h: Math.round(h),
        };
      });

      // Text overlays that render ON TOP of the video (titlebar / panel). The
      // builder re-stamps these (cropped from the JPEG) above the movie so the
      // text stays visible when the video plays.
      const chrome = Array.from(
        active.querySelectorAll(".slide-inner .showcase-titlebar, .slide-inner .showcase-panel")
      )
        .filter((el) => {
          const cr = el.getBoundingClientRect();
          return cr.width > 2 && cr.height > 2;
        })
        .map((el) => {
          const cr = el.getBoundingClientRect();
          return {
            x: Math.max(0, Math.round(cr.left)),
            y: Math.max(0, Math.round(cr.top)),
            w: Math.round(cr.width),
            h: Math.round(cr.height),
          };
        });

      return { videos, chrome };
    });

    // Small extra settle so the seeked frame is fully painted before capture.
    await page.waitForTimeout(200);

    const fname = `slide-${String(n).padStart(3, "0")}.jpg`;
    await page.screenshot({
      path: path.join(SLIDES_DIR, fname),
      type: "jpeg",
      quality: 90,
    });

    if (rects.videos.length) {
      // Only keep chrome rects that actually intersect a video rect.
      const intersects = (c, v) =>
        c.x < v.x + v.w && c.x + c.w > v.x && c.y < v.y + v.h && c.y + c.h > v.y;
      const chrome = rects.chrome.filter((c) => rects.videos.some((v) => intersects(c, v)));
      overlays[n] = { file: fname, videos: rects.videos, chrome };
    }
  }

  fs.writeFileSync(
    path.join(OUT, "video_overlays.json"),
    JSON.stringify({ viewport: VIEWPORT, slides: targets, overlays }, null, 2)
  );

  await browser.close();
  const vcount = Object.values(overlays).reduce((a, o) => a + o.videos.length, 0);
  console.log(
    `Captured ${targets.length} slide(s) -> ${SLIDES_DIR}\n` +
      `${vcount} foreground video overlay(s) across ${Object.keys(overlays).length} slide(s) -> video_overlays.json`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
