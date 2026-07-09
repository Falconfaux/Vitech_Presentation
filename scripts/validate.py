# -*- coding: utf-8 -*-
"""
Post-build QA pass for index.html. Run after `python3 scripts/build_site.py`:
    python3 scripts/validate.py
Checks image references resolve, slide ids/anchors/section counts stay
consistent, and flags slides that look empty or images with extreme aspect
ratios that may still look awkward even with object-fit: contain.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")

errors = []
warnings = []

with open(INDEX) as f:
    html = f.read()

slides = re.findall(r'<section class="slide ([^"]+)" id="s(\d+)" data-section="([^"]*)">(.*?)</section>', html, re.S)

# 1. Sequential id / anchor consistency -------------------------------------
ids = [int(sid) for _, sid, _, _ in slides]
expected = list(range(1, len(slides) + 1))
if ids != expected:
    missing = sorted(set(expected) - set(ids))
    errors.append(f"Slide id sequence broken. Missing: {missing}")
else:
    print(f"[OK] {len(slides)} slides, ids sequential 1..{len(slides)}")

# DOM order must match id order (main.js hash routing assumes index == id-1)
for i, (_, sid, _, _) in enumerate(slides):
    if int(sid) != i + 1:
        errors.append(f"Slide at DOM position {i} has id {sid}, expected {i+1}")

# 2. Image reference integrity ------------------------------------------------
img_srcs = re.findall(r'(?:data-src|src)="(assets/images/[^"]+)"', html)
missing_files = sorted(set(s for s in img_srcs if not os.path.exists(os.path.join(ROOT, s))))
if missing_files:
    errors.append(f"{len(missing_files)} referenced image file(s) do not exist: {missing_files}")
else:
    print(f"[OK] all {len(set(img_srcs))} unique referenced image files exist on disk")

# empty src (would happen if IMG()/IMGS() returned nothing for a slide_no) —
# scoped to slide bodies only; the lightbox's own <img src=""> is populated by JS on open.
empty_img_tags = sum(len(re.findall(r'<img[^>]*(?:data-src|src)=""', body)) for _, _, _, body in slides)
if empty_img_tags:
    errors.append(f"{empty_img_tags} <img> tag(s) inside a slide with an empty src/data-src")

# 3. Section jump-menu count parity -------------------------------------------
section_cards = re.findall(r'<div class="t">([^<]+)</div><div class="c">(\d+) slide', html)
section_counts_actual = {}
for _, _, section, _ in slides:
    section_counts_actual[section] = section_counts_actual.get(section, 0) + 1
_section_errors_before = len(errors)
for label, count_str in section_cards:
    count = int(count_str)
    actual = section_counts_actual.get(label)
    if actual is None:
        errors.append(f"Section card '{label}' has no matching slides")
    elif actual != count:
        errors.append(f"Section '{label}' card says {count} slides, actual is {actual}")
if len(errors) == _section_errors_before:
    print(f"[OK] section jump-menu counts match actual slide counts for {len(section_cards)} sections")

# 4. Blank-slide detector ------------------------------------------------------
for tpl, sid, section, body in slides:
    text = re.sub(r"<[^>]+>", "", body)
    text = re.sub(r"\s+", "", text)
    has_img = "<img" in body or "<svg" in body
    if len(text) < 3 and not has_img:
        warnings.append(f"Slide {sid} ({section}) looks empty: no visible text and no image/svg")

# 5. Extreme aspect ratio flag (informational only) ---------------------------
try:
    from PIL import Image
    have_pil = True
except ImportError:
    have_pil = False

if have_pil:
    extreme = []
    for src in sorted(set(img_srcs)):
        path = os.path.join(ROOT, src)
        if not os.path.exists(path):
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
            ratio = w / h
            if ratio > 2.2 or ratio < 0.45:
                extreme.append((src, w, h, round(ratio, 2)))
        except Exception:
            pass
    if extreme:
        warnings.append(f"{len(extreme)} image(s) with extreme aspect ratio (manual look recommended): " +
                         ", ".join(f"{s} ({w}x{h}, ratio {r})" for s, w, h, r in extreme))
else:
    warnings.append("Pillow not installed — skipped aspect-ratio extremes check")

# ------------------------------------------------------------------------------
print()
if warnings:
    print(f"{len(warnings)} warning(s):")
    for w in warnings:
        print(" -", w)
    print()

if errors:
    print(f"{len(errors)} ERROR(s):")
    for e in errors:
        print(" -", e)
    sys.exit(1)

print("Validation passed with no errors.")
