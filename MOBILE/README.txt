VITECH GROUP OF COMPANIES — PRESENTATION (MOBILE / OFFLINE POWERPOINT)
=====================================================================

FILES (140 slides, all photos included; every slide is a crisp still image):
   • Vitech-Group-Presentation.pdf    (~47 MB)  <- easiest on a phone
   • Vitech-Group-Presentation.pptx   (~45 MB)

Both are a faithful copy of our web-app presentation, downloadable and viewable
on ANY phone or tablet — no internet needed once downloaded.


HOW TO OPEN IT ON A PHONE
-------------------------
1. Download / save either file to your phone (from WhatsApp, email, Google
   Drive, etc.).

2. Just tap it:
   • The PDF opens instantly in any phone — no app to install. Best if you
     just want to view the presentation. Recommended.
   • The PPTX opens in the free "Microsoft PowerPoint" app, Apple Keynote,
     Google Slides, or the built-in file preview.

3. Turn your phone sideways (landscape) for the biggest view, and swipe
   left / right to move through the slides.


ABOUT THE VIDEO SLIDES
----------------------
The live web presentation has 7 short background videos (factory fly-overs,
weld finishing, site erection, ODC dispatch). Phone file-previews cannot play
video reliably, so in this file those 7 slides are shown as a clear STILL FRAME
of the footage instead. This keeps the whole deck opening perfectly on every
phone. (The full moving videos remain in the live web presentation.)


NOTES
-----
• Horizontal (landscape, 16:9) — matches the web deck exactly.
• View-only visual copy; the text is not meant to be edited here.
• To re-generate these files after the web deck changes:
      node scripts/capture_slides_for_pptx.mjs
      python3 scripts/build_pdf.py                  (the PDF)
      python3 scripts/build_pptx.py                 (static PPTX, phone-friendly)
      python3 scripts/build_pptx.py --with-video    (optional: embed the videos
                                                     for PowerPoint-app viewing)
