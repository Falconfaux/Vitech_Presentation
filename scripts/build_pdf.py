# -*- coding: utf-8 -*-
"""
Assemble MOBILE/Vitech-Group-Presentation.pdf from the slide images captured by
scripts/capture_slides_for_pptx.mjs — a companion to build_pptx.py.

A PDF is the most universally viewable format on a phone: it opens cleanly in
every file preview, browser, mail app and reader with no app to install and no
rendering quirks. Each of the 140 web slides becomes one landscape 16:9 page
(the captured JPEG, which for a video slide already has a real frame + title
baked in), so it matches the static PPTX exactly.

Prereqs: Pillow. Run after the capture step:
    python3 scripts/build_pdf.py
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDES_DIR = os.path.join(ROOT, "MOBILE", "build", "slides")
OUT_PDF = os.path.join(ROOT, "MOBILE", "Vitech-Group-Presentation.pdf")

# 1920x1080 px at 144 DPI == 13.333in x 7.5in == the 16:9 widescreen slide.
DPI = 144.0


def main():
    files = sorted(
        f for f in os.listdir(SLIDES_DIR) if f.startswith("slide-") and f.endswith(".jpg")
    )
    if not files:
        print("No slide JPEGs found in %s — run the capture first." % SLIDES_DIR, file=sys.stderr)
        sys.exit(1)

    pages = []
    for f in files:
        im = Image.open(os.path.join(SLIDES_DIR, f))
        if im.mode != "RGB":
            im = im.convert("RGB")
        pages.append(im)

    os.makedirs(os.path.dirname(OUT_PDF), exist_ok=True)
    # RGB images are embedded with JPEG (DCTDecode) compression, so the PDF stays
    # about the same size as the source JPEGs. quality=90 matches the capture.
    pages[0].save(
        OUT_PDF, "PDF", save_all=True, append_images=pages[1:],
        resolution=DPI, quality=90,
    )

    size_mb = os.path.getsize(OUT_PDF) / (1024 * 1024)
    print("Wrote %s" % OUT_PDF)
    print("  pages: %d   size: %.1f MB" % (len(pages), size_mb))


if __name__ == "__main__":
    main()
