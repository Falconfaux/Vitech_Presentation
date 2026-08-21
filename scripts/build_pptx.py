# -*- coding: utf-8 -*-
"""
Assemble MOBILE/Vitech-Group-Presentation.pptx from the slide images captured by
scripts/capture_slides_for_pptx.mjs.

Each web slide becomes one landscape 16:9 PowerPoint slide holding a single
full-bleed picture (pixel-identical to the web deck). On the 7 slides that carry
a foreground video, the original .mp4 is embedded in place — positioned over the
exact on-screen rectangle of the video (object-fit:contain aware) — with a poster
frame cropped from the slide image so it blends seamlessly. Any text panel /
titlebar that sits on top of that video is re-stamped above the movie so it stays
readable while the video plays.

Prereqs: python-pptx, Pillow. Run after the capture step:
    python3 scripts/build_pptx.py
"""
import json
import os
import sys

from PIL import Image
from pptx import Presentation
from pptx.util import Emu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "MOBILE", "build")
SLIDES_DIR = os.path.join(BUILD, "slides")
POSTERS_DIR = os.path.join(BUILD, "posters")
OVERLAYS = os.path.join(BUILD, "video_overlays.json")
OUT_PPTX = os.path.join(ROOT, "MOBILE", "Vitech-Group-Presentation.pptx")

# The capture viewport is 1920x1080; a 16:9 widescreen slide is 13.333in x 7.5in.
# 12192000 EMU / 1920 px == 6858000 EMU / 1080 px == exactly 6350 EMU per pixel.
STAGE_W, STAGE_H = 1920, 1080
SLIDE_W_EMU, SLIDE_H_EMU = 12192000, 6858000
EMU_PER_PX = 6350


def emu(px):
    return Emu(int(round(px * EMU_PER_PX)))


def clamp_rect(x, y, w, h):
    x = max(0, min(x, STAGE_W))
    y = max(0, min(y, STAGE_H))
    w = max(1, min(w, STAGE_W - x))
    h = max(1, min(h, STAGE_H - y))
    return x, y, w, h


def crop(slide_jpg, rect, out_path):
    x, y, w, h = rect
    with Image.open(slide_jpg) as im:
        im.convert("RGB").crop((x, y, x + w, y + h)).save(out_path, "JPEG", quality=92)
    return out_path


def main():
    with open(OVERLAYS) as f:
        data = json.load(f)
    overlays = data["overlays"]
    order = data["slides"]  # capture order == DOM/display order 1..N

    os.makedirs(POSTERS_DIR, exist_ok=True)

    prs = Presentation()
    prs.slide_width = Emu(SLIDE_W_EMU)   # 13.333in  -> horizontal / landscape
    prs.slide_height = Emu(SLIDE_H_EMU)  # 7.5in
    blank = prs.slide_layouts[6]

    movie_count = 0
    for n in order:
        jpg = os.path.join(SLIDES_DIR, "slide-%03d.jpg" % n)
        if not os.path.exists(jpg):
            print("  ! missing %s" % jpg, file=sys.stderr)
            continue

        slide = prs.slides.add_slide(blank)
        # Full-bleed slide image (bottom layer).
        slide.shapes.add_picture(jpg, Emu(0), Emu(0), width=Emu(SLIDE_W_EMU), height=Emu(SLIDE_H_EMU))

        ov = overlays.get(str(n))
        if not ov:
            continue

        # Embed each foreground video over its exact on-screen rectangle.
        for i, v in enumerate(ov["videos"]):
            x, y, w, h = clamp_rect(v["x"], v["y"], v["w"], v["h"])
            movie_path = os.path.join(ROOT, v["file"])
            if not os.path.exists(movie_path):
                print("  ! missing video %s" % movie_path, file=sys.stderr)
                continue
            poster = crop(jpg, (x, y, w, h), os.path.join(POSTERS_DIR, "poster-%03d-%d.jpg" % (n, i)))
            slide.shapes.add_movie(
                movie_path, emu(x), emu(y), emu(w), emu(h),
                poster_frame_image=poster, mime_type="video/mp4",
            )
            movie_count += 1

        # Re-stamp text panels / titlebars that overlap the video, on top of it.
        for j, c in enumerate(ov.get("chrome", [])):
            x, y, w, h = clamp_rect(c["x"], c["y"], c["w"], c["h"])
            strip = crop(jpg, (x, y, w, h), os.path.join(POSTERS_DIR, "chrome-%03d-%d.jpg" % (n, j)))
            slide.shapes.add_picture(strip, emu(x), emu(y), width=emu(w), height=emu(h))

    os.makedirs(os.path.dirname(OUT_PPTX), exist_ok=True)
    prs.save(OUT_PPTX)

    size_mb = os.path.getsize(OUT_PPTX) / (1024 * 1024)
    print("Wrote %s" % OUT_PPTX)
    print("  slides: %d   embedded videos: %d   size: %.1f MB" % (len(prs.slides._sldIdLst), movie_count, size_mb))


if __name__ == "__main__":
    main()
