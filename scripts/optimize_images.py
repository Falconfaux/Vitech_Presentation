#!/usr/bin/env python3
"""One-time pass: sharpen and, for undersized sources, upscale every image
actually referenced from index.html, then re-encode cleanly.

Non-transparent PNGs are converted to JPEG (lossless re-encoding of upscaled
photographic PNGs bloats file size 5-7x for no visible quality gain; JPEG at
q=90 is visually indistinguishable and much smaller). Converted files are
renamed .png -> .jpg, with image_manifest.json and the one hardcoded
build_site.py reference updated to match.

Run this, then `python3 scripts/build_site.py` to regenerate index.html
(aspect ratios are preserved exactly so slide layouts don't shift), then
`python3 scripts/validate.py`.
"""
import json
import os
import re
import sys

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(ROOT, "index.html")
MANIFEST_PATH = os.path.join(ROOT, "scripts", "image_manifest.json")
BUILD_SCRIPT = os.path.join(ROOT, "scripts", "build_site.py")

TARGET_LONG_EDGE = 1400
MAX_UPSCALE = 2.5
JPEG_QUALITY = 90
SKIP_DIR = "assets/images/brand/"

UNSHARP = ImageFilter.UnsharpMask(radius=1.4, percent=110, threshold=2)
UNSHARP_UPSCALED = ImageFilter.UnsharpMask(radius=2.0, percent=110, threshold=2)


def referenced_images():
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    paths = sorted(set(re.findall(
        r"assets/images/(?:slides|brand)/[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png)", html)))
    return [p for p in paths if not p.startswith(SKIP_DIR)]


def has_real_alpha(im):
    if im.mode in ("RGBA", "LA"):
        return im.getchannel("A").getextrema() != (255, 255)
    return False


def process(rel_path):
    abs_path = os.path.join(ROOT, rel_path)
    ext = os.path.splitext(abs_path)[1].lower()
    with Image.open(abs_path) as im:
        w, h = im.size
        long_edge = max(w, h)
        old_size = os.path.getsize(abs_path)
        convert_to_jpeg = ext == ".png" and not has_real_alpha(im)

        if long_edge < TARGET_LONG_EDGE:
            factor = min(TARGET_LONG_EDGE / long_edge, MAX_UPSCALE)
            new_w, new_h = round(w * factor), round(h * factor)
            im = im.resize((new_w, new_h), Image.LANCZOS)
            im = im.filter(UNSHARP_UPSCALED)
            upscaled = True
        else:
            new_w, new_h = w, h
            im = im.filter(UNSHARP)
            upscaled = False

        new_rel_path = rel_path
        if ext in (".jpg", ".jpeg") or convert_to_jpeg:
            if im.mode != "RGB":
                im = im.convert("RGB")
            if convert_to_jpeg:
                new_rel_path = rel_path[:-len(ext)] + ".jpg"
            im.save(os.path.join(ROOT, new_rel_path), "JPEG",
                     quality=JPEG_QUALITY, optimize=True, progressive=True)
            if convert_to_jpeg:
                os.remove(abs_path)
        else:
            im.save(abs_path, "PNG", optimize=True)

    new_size = os.path.getsize(os.path.join(ROOT, new_rel_path))
    return {
        "path": rel_path,
        "new_path": new_rel_path,
        "renamed": new_rel_path != rel_path,
        "old_dims": (w, h),
        "new_dims": (new_w, new_h),
        "upscaled": upscaled,
        "capped": upscaled and (new_w / w) < (TARGET_LONG_EDGE / long_edge) - 1e-6,
        "old_size": old_size,
        "new_size": new_size,
    }


def update_manifest(renames):
    if not renames:
        return
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    changed = 0
    for slide, files in manifest.items():
        for i, fname in enumerate(files):
            if fname in renames:
                files[i] = renames[fname]
                changed += 1
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    print(f"Updated {changed} filename(s) in image_manifest.json")


def update_build_script(renames):
    if not renames:
        return
    with open(BUILD_SCRIPT, encoding="utf-8") as f:
        src = f.read()
    changed = 0
    for old_name, new_name in renames.items():
        if old_name in src:
            src = src.replace(old_name, new_name)
            changed += 1
    if changed:
        with open(BUILD_SCRIPT, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"Updated {changed} hardcoded filename(s) in build_site.py")


def main():
    images = referenced_images()
    print(f"Processing {len(images)} referenced images (target long edge "
          f"{TARGET_LONG_EDGE}px, max upscale {MAX_UPSCALE}x, JPEG q={JPEG_QUALITY})\n")

    results = []
    renames = {}
    for rel_path in images:
        abs_path = os.path.join(ROOT, rel_path)
        if not os.path.exists(abs_path):
            print(f"  MISSING: {rel_path}")
            continue
        r = process(rel_path)
        results.append(r)
        if r["renamed"]:
            renames[os.path.basename(r["path"])] = os.path.basename(r["new_path"])
        tag = " [capped]" if r["capped"] else (" [upscaled]" if r["upscaled"] else "")
        tag += " [->jpg]" if r["renamed"] else ""
        print(f"  {r['path']:55s} {r['old_dims'][0]:5d}x{r['old_dims'][1]:<5d} -> "
              f"{r['new_dims'][0]:5d}x{r['new_dims'][1]:<5d}  "
              f"{r['old_size']/1024:7.1f}KB -> {r['new_size']/1024:7.1f}KB{tag}")

    update_manifest(renames)
    update_build_script(renames)

    total_old = sum(r["old_size"] for r in results)
    total_new = sum(r["new_size"] for r in results)
    upscaled_count = sum(1 for r in results if r["upscaled"])
    capped_count = sum(1 for r in results if r["capped"])
    print(f"\nDone. {len(results)} images processed, {upscaled_count} upscaled "
          f"({capped_count} capped at {MAX_UPSCALE}x — inherently resolution-limited), "
          f"{len(renames)} PNG->JPEG conversions.")
    print(f"Total size: {total_old/1024/1024:.1f}MB -> {total_new/1024/1024:.1f}MB")
    print("\nNow run: python3 scripts/build_site.py && python3 scripts/validate.py")


if __name__ == "__main__":
    sys.exit(main())
