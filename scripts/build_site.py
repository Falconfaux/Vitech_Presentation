# -*- coding: utf-8 -*-
"""
Build script for the Vitech Group presentation.
Reads structured slide content (transcribed from the converted .pptx) and
renders a single static index.html. Re-run with `python3 scripts/build_site.py`
whenever slide content changes.
"""
import json, os, html, functools
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "scripts", "image_manifest.json")) as f:
    MANIFEST = json.load(f)

def IMG(slide, n=1):
    key = str(slide)
    files = MANIFEST.get(key, [])
    if n - 1 < len(files):
        return "assets/images/slides/" + files[n - 1]
    return ""

def IMGS(slide):
    return ["assets/images/slides/" + f for f in MANIFEST.get(str(slide), [])]

def esc(s):
    return html.escape(str(s), quote=False)

def nb(s):
    return esc(s).replace("\n", "<br>")

SLIDES = []  # list of dicts: id, section, tpl, html

def next_id():
    return len(SLIDES) + 1

def add(id, section, tpl, body):
    SLIDES.append({"id": id, "section": section, "tpl": tpl, "html": body})

# ---------------------------------------------------------------------------
# Template renderers
# ---------------------------------------------------------------------------

def bg(slide_no, n=1):
    src = IMG(slide_no, n)
    if not src:
        return ""
    return '<div class="slide-bg" data-src="{0}" style="background-image:url({0})"></div><div class="slide-scrim"></div>'.format(src)

def lazybg(slide_no, n=1):
    # background applied via JS after data-src swap isn't trivial for CSS bg; instead use an <img> layer.
    src = IMG(slide_no, n)
    if not src:
        return ""
    return ('<img class="slide-bg-img" data-src="{0}" alt="" '
            'style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transform:scale(1.08);z-index:0;">'
            '<div class="slide-scrim"></div>').format(src)

def media_files(slide_no, count=None):
    if isinstance(slide_no, (list, tuple)):
        per_source = [IMGS(sn) for sn in slide_no]
        if count:
            # round-robin across sources so a hard cap doesn't erase any one source's photos
            files, i = [], 0
            while len(files) < count and any(per_source):
                src = per_source[i % len(per_source)]
                if src:
                    files.append(src.pop(0))
                i += 1
        else:
            files = [f for src in per_source for f in src]
    else:
        files = IMGS(slide_no)
        if count:
            files = files[:count]
    return files

@functools.lru_cache(maxsize=None)
def img_aspect(path):
    # width / height; landscape > 1, portrait < 1. Falls back to a landscape
    # guess (matches the vast majority of photos in this deck) if unreadable.
    try:
        with Image.open(os.path.join(ROOT, path)) as im:
            w, h = im.size
        return w / h
    except Exception:
        return 1.5

def resolve_stack(files, layout=None):
    """Decide whether a spec slide's media should use the full-width 'stack'
    treatment (compact content top-right, big image band below) or the
    classic 50/50 split (media column left, content right). Driven by the
    images' real aspect ratio: landscape/square sets read far better as a
    wide band; portrait-heavy sets (tall vessels/towers) still suit the
    classic tall column."""
    if layout == "split":
        return False
    if layout == "stack":
        return True
    n = len(files)
    if n == 0:
        return False
    avg_aspect = sum(img_aspect(f) for f in files) / n
    return avg_aspect >= (1.3 if n == 1 else 1.0)

def arrange_showcase(items):
    """Pick the cell arrangement for a 3-photo showcase canvas so wide photos
    render big instead of shrinking into tall column strips.
    items: list of (src, extra_html). All-landscape sets become 'grid3' (two
    cells up top, the widest photo spanning the full bottom row); sets with
    exactly one portrait become 'mosaic3' (portrait full-height on the left,
    the two landscape photos stacked on the right). Portrait-leaning sets
    keep the default columns. Returns (ordered_items, extra_class)."""
    if len(items) != 3:
        return items, ""
    aspects = [img_aspect(src) for src, _ in items]
    portraits = [i for i, a in enumerate(aspects) if a < 1.1]
    if not portraits and min(aspects) >= 1.15:
        widest = max(range(3), key=lambda i: aspects[i])
        ordered = [items[i] for i in range(3) if i != widest] + [items[widest]]
        return ordered, " grid3"
    if len(portraits) == 1 and all(a >= 1.15 for i, a in enumerate(aspects) if i not in portraits):
        p = portraits[0]
        ordered = [items[p]] + [items[i] for i in range(3) if i != p]
        return ordered, " mosaic3"
    return items, ""

def _fill_weight(a):
    # clamp a cell's fr weight so one extreme photo can't crush its neighbours
    return max(0.45, min(2.4, a))

def fill_style(files, arr_cls=""):
    """Inline grid-template-columns for a photo-fill canvas: column widths
    proportional to each photo's real aspect ratio, so cover-fit photos crop
    minimally (cells in a row share height, so width ∝ aspect makes each cell
    match its photo's shape). mosaic3 weighs the full-height portrait column
    against the stacked landscape pair; grid3 weighs its two top columns."""
    aspects = [img_aspect(f) for f in files]
    if "mosaic3" in arr_cls:
        cols = [_fill_weight(aspects[0]), _fill_weight(max(aspects[1], aspects[2]) / 2)]
    elif "grid3" in arr_cls:
        cols = [_fill_weight(aspects[0]), _fill_weight(aspects[1])]
    elif len(files) in (2, 3):
        cols = [_fill_weight(a) for a in aspects]
    else:
        return ""
    return ' style="grid-template-columns:{0}"'.format(
        " ".join("{0:.2f}fr".format(c) for c in cols))

def _panel_clear_cells(n, arr_cls):
    """Indices (display order) of showcase cells that touch the slide's lower
    edge and must reserve clearance for the bottom panel strip."""
    if "grid3" in arr_cls:
        return {2}
    if "mosaic3" in arr_cls:
        return {0, 2}
    if n == 4:
        return {2, 3}
    return set(range(n))

def media_frame(src, extra_cls=""):
    """Uncropped media frame: the full photo (object-fit: contain) layered
    over a blurred, darkened cover copy of itself, so an aspect-ratio
    mismatch never crops the photo or leaves the frame looking empty."""
    return ('<div class="media-frame{1}">'
            '<img class="media-blur" data-src="{0}" alt="" aria-hidden="true" loading="lazy">'
            '<img class="media-full" data-src="{0}" alt="" loading="lazy">'
            '</div>').format(src, (" " + extra_cls) if extra_cls else "")

def media_grid(files, stack, media_layout=None):
    n = len(files)
    cls = "n" + str(min(n, 4)) if n else "n1"
    # Frames sit side by side (columns) whenever there are several photos:
    # in the stack band the strip is wide, and in the classic split the
    # photos are portrait-leaning (that's why split was chosen), so tall
    # narrow cells fit them whole without shrinking.
    if n >= 2:
        cls += " row" + str(min(n, 4))
    frames = "".join(media_frame(f) for f in files)
    return '<div class="spec-media-grid {0}">{1}</div>'.format(cls, frames)

def hero_img(files):
    """A single accent image that fills the strip the 'stack' layout otherwise
    leaves blank beside the compact content card, shown whole against a
    blurred fill rather than cropped."""
    if not files:
        return ""
    return ('<div class="spec-hero media-frame reveal reveal-d2">'
            '<img class="media-blur" data-src="{0}" alt="" aria-hidden="true" loading="lazy">'
            '<img class="media-full" data-src="{0}" alt="" loading="lazy">'
            '</div>').format(files[0])

def cover(section, title_html, locations, contact_lines, bg_img, tagline=None, stats=None):
    id = next_id()
    # locations render as a quiet inline meta row: bold company name + city,
    # separated by amber dots
    loc_parts = []
    for i, l in enumerate(locations):
        if i:
            loc_parts.append('<span class="sep"></span>')
        loc_parts.append('<span><b>{0}</b> {1}</span>'.format(esc(l[0]), nb(l[1])))
    loc_html = '<div class="cover-meta reveal reveal-d3">{0}</div>'.format("".join(loc_parts)) if locations else ""
    tagline_html = '<p class="cover-tagline reveal reveal-d1">{0}</p>'.format(esc(tagline)) if tagline else ""
    stats_html = ""
    if stats:
        tiles = "".join(
            '<div class="stat"><div class="num">{v}</div><div class="lbl">{l}</div></div>'.format(v=esc(v), l=esc(l))
            for v, l in stats
        )
        stats_html = '<div class="cover-statbar reveal reveal-d2">{0}</div>'.format(tiles)
    body = '''
    <section class="slide tpl-cover" id="s{id}" data-section="{section}">
      {bg}
      <div class="slide-inner">
        <div class="cover-top">
          <img class="cover-logo reveal" src="assets/images/brand/vitech-lockup.png" alt="Vitech Group of Companies">
          <h1 class="reveal reveal-d1">{title}</h1>
          <div class="cover-rule reveal reveal-d1"></div>
          {tagline}
        </div>
        <div class="cover-bottom">
          {stats}
          {loc}
          <div class="cover-contact reveal reveal-d3">{contact}</div>
        </div>
      </div>
      <div class="scroll-cue"><span>Scroll to begin</span><span class="dot"></span></div>
    </section>'''.format(id=id, section=esc(section), bg=lazybg(bg_img), title=title_html,
                          tagline=tagline_html, stats=stats_html,
                          loc=loc_html, contact="  ·  ".join(esc(c) for c in contact_lines))
    add(id, section, "cover", body)

def divider(section, title_html, sub, bg_img=None, index_label=""):
    id = next_id()
    body = '''
    <section class="slide tpl-divider" id="s{id}" data-section="{section}">
      {bg}
      <div class="slide-inner">
        <div class="divider-index">{idx}</div>
        <div class="eyebrow reveal">{section}</div>
        <h2 class="reveal reveal-d1">{title}</h2>
        <div class="divider-rule reveal reveal-d2"></div>
        <p class="divider-sub reveal reveal-d3">{sub}</p>
      </div>
    </section>'''.format(id=id, section=esc(section),
                          bg=(lazybg(*bg_img) if isinstance(bg_img, tuple) else lazybg(bg_img)) if bg_img else "",
                          idx=esc(index_label), title=title_html, sub=nb(sub) if sub else "")
    add(id, section, "divider", body)

def prose(section, eyebrow, title, paragraphs, stats=None, side_title=None, side_items=None, chips=None, bg_img=None,
          fact_rows=None, labeled_chips=None, center=False):
    id = next_id()
    stats_html = ""
    if stats:
        tiles = "".join(
            '<div class="stat-tile"><div class="num" data-count="{c}" data-suffix="{sfx}">0{sfx}</div>'
            '<div class="lbl">{lbl}</div></div>'.format(c=s.get("count",""), sfx=esc(s.get("suffix","")), lbl=esc(s["label"]))
            if "count" in s else
            '<div class="stat-tile"><div class="num">{val}</div><div class="lbl">{lbl}</div></div>'.format(val=esc(s["value"]), lbl=esc(s["label"]))
            for s in stats
        )
        stats_html = '<div class="stat-row reveal reveal-d2">{0}</div>'.format(tiles)
    fact_rows_html = ""
    if fact_rows:
        rows = "".join(
            '<div class="spec-row"><div class="k">{0}</div><div class="v">{1}</div></div>'.format(esc(k), nb(v))
            for k, v in fact_rows
        )
        fact_rows_html = '<div class="spec-list reveal reveal-d2">{0}</div>'.format(rows)
    labeled_chips_html = ""
    if labeled_chips:
        groups = "".join(
            '<div class="labeled-chip-group"><h4>{0}</h4><div class="chip-row">{1}</div></div>'.format(
                esc(g["label"]),
                "".join('<span class="chip">{0}</span>'.format(esc(t)) for t in g["items"])
            ) for g in labeled_chips
        )
        labeled_chips_html = '<div class="reveal reveal-d3">{0}</div>'.format(groups)
    chips_html = ""
    if chips:
        chips_html = '<div class="chip-row reveal reveal-d3">{0}</div>'.format(
            "".join('<span class="chip{0}">{1}</span>'.format(" on" if c.get("on") else "", esc(c["t"])) for c in chips)
        )
    p_html = "".join('<p>{0}</p>'.format(nb(p)) for p in paragraphs)
    side_html = ""
    if side_items:
        items = "".join('<li>{0}</li>'.format(nb(i)) for i in side_items)
        wide_cls = " wide" if len(side_items) > 10 else ""
        side_html = '''<div class="side-panel{2} reveal reveal-d2"><h3>{0}</h3><ul>{1}</ul></div>'''.format(esc(side_title or ""), items, wide_cls)
    body = '''
    <section class="slide tpl-prose" id="s{id}" data-section="{section}">
      {bg}
      <div class="slide-inner{centercls}">
        <div class="eyebrow reveal">{eyebrow}</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        <div class="content-grid">
          <div class="reveal reveal-d2">{paras}{facts}{stats}{labchips}{chips}</div>
          {side}
        </div>
      </div>
    </section>'''.format(id=id, section=esc(section), bg=lazybg(bg_img) if bg_img else "", eyebrow=esc(eyebrow),
                          centercls=" centered" if center else "",
                          title=title, paras=p_html, facts=fact_rows_html, stats=stats_html,
                          labchips=labeled_chips_html, chips=chips_html, side=side_html)
    add(id, section, "prose", body)

def visual(section, eyebrow, title, sub, slide_no, images_count=1, row=False, captions=None, stat_row=None):
    id = next_id()
    if isinstance(slide_no, (list, tuple)):
        files = []
        for sn in slide_no:
            files.extend(IMGS(sn))
        row = True
    else:
        files = IMGS(slide_no)[:images_count] if images_count else IMGS(slide_no)
    if row and len(files) > 1:
        frames = "".join(media_frame(f, "visual-frame") for f in files)
        media = '<div class="visual-row reveal reveal-d2">{0}</div>'.format(frames)
    else:
        f = files[0] if files else ""
        media = media_frame(f, "visual-frame reveal reveal-d2")
    cap = '<p class="visual-caption reveal reveal-d3">{0}</p>'.format(esc(captions)) if captions else ""
    stats_html = ""
    has_stats_cls = ""
    if stat_row:
        has_stats_cls = " has-stats"
        tiles = "".join(
            '<div class="stat-tile"><div class="num">{v}</div><div class="lbl">{l}</div></div>'.format(v=esc(v), l=esc(l))
            for v, l in stat_row
        )
        stats_html = '<div class="stat-row reveal reveal-d3">{0}</div>'.format(tiles)
    body = '''
    <section class="slide tpl-visual{has_stats}" id="s{id}" data-section="{section}">
      <div class="slide-inner">
        <div class="eyebrow reveal">{eyebrow}</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        {sub}
        {media}
        {cap}
        {stats}
      </div>
    </section>'''.format(id=id, has_stats=has_stats_cls, section=esc(section), eyebrow=esc(eyebrow), title=title,
                          sub='<p class="slide-sub reveal reveal-d1">{0}</p>'.format(nb(sub)) if sub else "",
                          media=media, cap=cap, stats=stats_html)
    add(id, section, "visual", body)

def _org_card(role, names, cls="org-card"):
    names_html = '<small>{0}</small>'.format("<br>".join(esc(n) for n in names)) if names else ""
    return '<div class="{0}">{1}{2}</div>'.format(cls, esc(role), names_html)

def _org_column(col, style):
    """One department column: manager card at top, then each subordinate as its
    own card joined by short vertical connectors (mirrors the original chart)."""
    parts = [_org_card(col["role"], col.get("names", []), "org-card org-card-mgr")]
    for sub in col.get("chain", []):
        parts.append('<div class="org-vline"></div>')
        parts.append(_org_card(sub["role"], sub.get("names", []), "org-card org-card-sub"))
    return '<div class="org-col" style="{0}">{1}</div>'.format(style, "".join(parts))

def _org_branch(columns_before, gm, gm_peer, gm_branches, columns_after):
    """One bus + department-column grid hanging under a single exec card.
    Optionally nests the General Manager + Technical Manager pair one level
    above the gm_branches columns (as in the original chart)."""
    n_before = len(columns_before)
    n_gm = len(gm_branches)
    cols = []
    for i, col in enumerate(columns_before):
        cols.append(_org_column(col, "grid-column:{0};grid-row:1/3".format(i + 1)))
    if gm:
        cols.append(
            '<div class="org-gm-head" style="grid-column:{0}/{1};grid-row:1">{2}{3}</div>'.format(
                n_before + 1, n_before + 1 + n_gm,
                _org_card(gm["role"], gm.get("names", []), "org-card org-card-gm"),
                _org_card(gm_peer["role"], gm_peer.get("names", []), "org-card org-card-peer"))
        )
        for i, col in enumerate(gm_branches):
            cols.append(_org_column(col, "grid-column:{0};grid-row:2".format(n_before + 1 + i)))
    for i, col in enumerate(columns_after):
        cols.append(_org_column(col, "grid-column:{0};grid-row:1/3".format(n_before + n_gm + 1 + i)))
    total = n_before + n_gm + len(columns_after)
    return '''<div class="org-branch">
      <div class="org-connector"></div>
      <div class="org-bus"></div>
      <div class="org-grid" style="grid-template-columns:repeat({0},1fr)">{1}</div>
    </div>'''.format(total, "".join(cols))

def org_chart(section, eyebrow, title, exec_chain, director_columns, vp_columns, gm, gm_peer, gm_branches, right_columns, footnote=None):
    """Replicates the original Quality Manual chart: a vertical executive chain
    (MD → Director → VP), then TWO independent department trees hanging one
    beneath Director and one beneath VP — the General Manager + Technical
    Manager pair sits one level above the four columns that report to the GM,
    within the VP's branch."""
    id = next_id()
    def _exec_card(role, name):
        return '<div class="org-card org-card-exec">{0}<small>{1}</small></div>'.format(esc(role), esc(name))
    if len(exec_chain) >= 3:
        # Top execs stack vertically (MD); the final two — Director then VP —
        # sit side by side (Director on the LEFT of the VP), with each one's
        # own department tree hanging directly beneath that person's card.
        top = exec_chain[:-2]
        director, vp = exec_chain[-2], exec_chain[-1]
        exec_html = "".join(
            _exec_card(role, name) + '<div class="org-connector"></div>'
            for role, name in top
        ) + (
            '<div class="org-exec-pair">{0}{1}</div>'.format(
                _exec_card(*director), _exec_card(*vp))
        )
    else:
        exec_html = "".join(
            _exec_card(role, name) + '<div class="org-connector"></div>'
            for role, name in exec_chain
        )
    director_branch = _org_branch(director_columns, None, None, [], [])
    vp_branch = _org_branch(vp_columns, gm, gm_peer, gm_branches, right_columns)
    foot_html = '<div class="org-footnote reveal reveal-d3">{0}</div>'.format(esc(footnote)) if footnote else ""
    body = '''
    <section class="slide tpl-orgchart" id="s{id}" data-section="{section}">
      <div class="slide-inner">
        <div class="eyebrow reveal">{eyebrow}</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        <div class="org-tree reveal reveal-d2">
          {exec_html}
          <div class="org-branches">
            {director_branch}
            {vp_branch}
          </div>
        </div>
        {foot}
      </div>
    </section>'''.format(id=id, section=esc(section), eyebrow=esc(eyebrow), title=title,
                          exec_html=exec_html, director_branch=director_branch, vp_branch=vp_branch,
                          foot=foot_html)
    add(id, section, "orgchart", body)

def site_plan(section, eyebrow, title, img_src, legend, stat=None):
    """Full-bleed site plan: the CAD drawing owns the whole slide (uncropped,
    letterboxed just above a slim glass legend bar docked to the bottom edge,
    so no map marker is covered). Title and plot-area stat float as compact
    frosted chips in the top corners."""
    id = next_id()
    # split the flat legend list into groups (each starts with a ("group", …))
    groups, cur = [], None
    for num, txt in legend:
        if num == "group":
            cur = {"title": txt, "items": []}
            groups.append(cur)
        else:
            (cur or groups.setdefault(0, {"title": "", "items": []}))["items"].append((num, txt))
    cols = []
    for g in groups:
        items = "".join(
            '<div class="legend-item"><span class="legend-num">{0}</span>'
            '<span class="legend-txt">{1}</span></div>'.format(esc(num), nb(txt))
            for num, txt in g["items"])
        cols.append('<div class="legend-col"><div class="legend-group-header">{0}</div>{1}</div>'.format(
            esc(g["title"]), items))
    legend_html = "".join(cols)
    stat_html = ""
    if stat:
        v, l = stat
        stat_html = '<div class="siteplan-stat reveal reveal-d1">{0} <span>{1}</span></div>'.format(esc(v), esc(l))
    body = '''
    <section class="slide tpl-siteplan" id="s{id}" data-section="{section}">
      <div class="siteplan-canvas site-plan-map">
        <img class="media-full" data-src="{img}" alt="" loading="lazy">
        <p class="site-plan-hint">Click to enlarge</p>
      </div>
      <div class="slide-inner">
        <div class="siteplan-titlebar reveal reveal-d1">
          <div class="eyebrow">{eyebrow}</div>
          <h2 class="slide-title">{title}</h2>
        </div>
        {stat}
        <aside class="siteplan-legend reveal reveal-d2">{legend}</aside>
      </div>
    </section>'''.format(id=id, section=esc(section), eyebrow=esc(eyebrow), title=title,
                          img=img_src, legend=legend_html, stat=stat_html)
    add(id, section, "siteplan", body)

_LOCATION_MAP_SVG = '''
<svg class="location-map-svg" viewBox="0 0 1000 600" xmlns="http://www.w3.org/2000/svg">
  <!-- Rabale railway station above the main road -->
  <rect class="lm-landmark-box" x="120" y="26" width="240" height="40" rx="3"/>
  <text class="lm-label-box" x="240" y="51" text-anchor="middle">RABALE RAILWAY STATION</text>

  <!-- Thane Belapur Road with two roundabouts -->
  <rect class="lm-road-main" x="30" y="98" width="940" height="32"/>
  <line class="lm-road-dash" x1="30" y1="114" x2="970" y2="114"/>
  <text class="lm-road-title" x="545" y="92" text-anchor="middle">THANE BELAPUR ROAD</text>
  <ellipse class="lm-roundabout" cx="358" cy="114" rx="24" ry="17"/>
  <ellipse class="lm-roundabout" cx="748" cy="114" rx="24" ry="17"/>
  <path class="lm-arrow" d="M60,114 L94,100 L94,128 Z"/>
  <rect class="lm-arrow" x="94" y="110" width="38" height="8"/>
  <text class="lm-dir" x="140" y="90" text-anchor="start">TOWARDS (NEW MUMBAI)</text>
  <path class="lm-arrow" d="M940,114 L906,100 L906,128 Z"/>
  <rect class="lm-arrow" x="868" y="110" width="38" height="8"/>
  <text class="lm-dir" x="930" y="90" text-anchor="end">TOWARDS (THANE)</text>

  <!-- Nhava Sheva Port callout (left) -->
  <path class="lm-arrow" d="M48,166 L86,152 L86,180 Z"/>
  <rect class="lm-arrow" x="86" y="162" width="42" height="8"/>
  <text class="lm-callout-title" x="150" y="200" text-anchor="start">( TOWARDS MUMBAI )</text>
  <text class="lm-callout-dist" x="40" y="226" text-anchor="start">NHAVA SHEVA PORT</text>
  <text class="lm-callout" x="40" y="248" text-anchor="start">Via — Thane–Belapur Rd. (NH 348A)</text>
  <text class="lm-callout" x="40" y="266" text-anchor="start">Distance — 38.4 KM</text>

  <!-- internal vertical roads -->
  <rect class="lm-road-minor" x="345" y="130" width="26" height="470"/>
  <rect class="lm-road-minor" x="735" y="130" width="26" height="248"/>
  <path class="lm-arrow" d="M358,152 L346,180 L370,180 Z"/>
  <path class="lm-arrow" d="M748,152 L736,180 L760,180 Z"/>

  <!-- Vrushali Hotel on the first vertical road -->
  <rect class="lm-hotel" x="374" y="176" width="24" height="38"/>
  <path class="lm-arrow" d="M398,195 L424,183 L424,207 Z" style="opacity:.85"/>
  <text class="lm-landmark" x="452" y="178" text-anchor="start">VRUSHALI HOTEL</text>

  <!-- Internal MIDC Road -->
  <rect class="lm-road-minor" x="345" y="246" width="625" height="26"/>
  <text class="lm-road-title-sm" x="560" y="240" text-anchor="middle">INTERNAL MIDC ROAD</text>

  <!-- Shankar Hotel below the internal road -->
  <rect class="lm-hotel" x="374" y="292" width="24" height="38"/>
  <path class="lm-arrow" d="M398,311 L424,299 L424,323 Z" style="opacity:.85"/>
  <text class="lm-landmark" x="452" y="296" text-anchor="start">SHANKAR HOTEL</text>

  <!-- MIDC Road -->
  <rect class="lm-road-minor" x="130" y="350" width="840" height="26"/>
  <text class="lm-road-title-sm" x="248" y="344" text-anchor="middle">MIDC ROAD</text>
  <path class="lm-arrow" d="M262,363 L292,351 L292,375 Z"/>
  <rect class="lm-arrow" x="292" y="359" width="30" height="8"/>
  <path class="lm-arrow" d="M846,363 L816,351 L816,375 Z"/>
  <rect class="lm-arrow" x="786" y="359" width="30" height="8"/>

  <!-- MIDC plot blocks (lower-right quadrant) -->
  <rect class="lm-plot-area" x="530" y="392" width="120" height="48"/>
  <rect class="lm-plot-area" x="672" y="392" width="120" height="48"/>
  <rect class="lm-plot-area" x="814" y="392" width="76" height="48"/>
  <rect class="lm-plot-area" x="912" y="392" width="58" height="48"/>
  <rect class="lm-plot-area" x="530" y="456" width="120" height="48"/>
  <rect class="lm-plot-area" x="672" y="456" width="120" height="48"/>
  <rect class="lm-plot-area" x="912" y="456" width="58" height="48"/>
  <rect class="lm-plot-area" x="530" y="520" width="120" height="48"/>
  <rect class="lm-plot-area" x="672" y="520" width="120" height="48"/>

  <!-- Vitech Equipments plot -->
  <rect class="lm-plot-vitech" x="404" y="404" width="112" height="76" rx="3"/>
  <text class="lm-plot-label-sm" x="460" y="437" text-anchor="middle">VITECH</text>
  <text class="lm-plot-label-sm" x="460" y="454" text-anchor="middle">EQUIPMENTS</text>
  <path class="lm-arrow" d="M415,388 L403,360 L427,360 Z" style="opacity:.85"/>

  <!-- Vitech Fabricators plot -->
  <rect class="lm-plot-vitech" x="814" y="516" width="156" height="56" rx="3"/>
  <text class="lm-plot-label-sm" x="892" y="539" text-anchor="middle">VITECH</text>
  <text class="lm-plot-label-sm" x="892" y="556" text-anchor="middle">FABRICATORS</text>

  <!-- route arrows toward Vitech Fabricators -->
  <path class="lm-arrow" d="M358,498 L346,470 L370,470 Z"/>
  <path class="lm-arrow" d="M800,545 L770,533 L770,557 Z"/>
  <rect class="lm-arrow" x="740" y="541" width="30" height="8"/>
  <path class="lm-arrow" d="M802,466 L793,444 L811,444 Z"/>
  <path class="lm-route" d="M358,272 V350"/>
  <path class="lm-route" d="M748,272 V350"/>
</svg>
'''

_LOCATION_MAP_SVG_SHAHAPUR = '''
<svg class="location-map-svg" viewBox="0 0 1000 600" xmlns="http://www.w3.org/2000/svg">
  <!-- top estate road linking the left corridors to the Shirol road -->
  <rect class="lm-road-minor" x="105" y="84" width="716" height="24"/>
  <!-- two left access corridors with two-way arrows -->
  <rect class="lm-road-minor" x="105" y="84" width="24" height="300"/>
  <rect class="lm-road-minor" x="185" y="84" width="24" height="300"/>
  <path class="lm-arrow" d="M117,150 L107,176 L127,176 Z"/>
  <path class="lm-arrow" d="M117,300 L107,274 L127,274 Z"/>
  <path class="lm-arrow" d="M197,150 L187,176 L207,176 Z"/>
  <path class="lm-arrow" d="M197,300 L187,274 L207,274 Z"/>

  <!-- shirol access road (right side, north of highway) -->
  <rect class="lm-road-minor" x="795" y="52" width="26" height="332"/>
  <path class="lm-arrow" d="M808,64 L794,94 L822,94 Z"/>
  <text class="lm-road-title-sm" x="808" y="42" text-anchor="middle">SHIROL</text>

  <!-- vitech compound with V.H.E.P.L. plot inside -->
  <rect class="lm-plot-area" x="310" y="148" width="270" height="140" rx="4"/>
  <rect class="lm-plot-vitech" x="345" y="182" width="165" height="72" rx="4"/>
  <text class="lm-plot-label" x="427" y="224" text-anchor="middle">V.H.E.P.L</text>

  <!-- Cliffkumar Heavy Engg plot, right of the compound -->
  <rect class="lm-landmark-box" x="600" y="160" width="185" height="54" rx="4"/>
  <text class="lm-label-box" x="692" y="182" text-anchor="middle" style="font-size:12.5px">CLIFFKUMAR HEAVY ENGG.</text>
  <text class="lm-label-box" x="692" y="200" text-anchor="middle" style="font-size:12.5px">PVT. LTD.</text>

  <!-- feeder road from the top estate road, with entry arrows toward VHEPL -->
  <rect class="lm-road-minor" x="735" y="108" width="22" height="106"/>
  <path class="lm-arrow" d="M746,126 L736,152 L756,152 Z"/>
  <path class="lm-arrow" d="M600,242 L632,230 L632,254 Z"/>
  <rect class="lm-arrow" x="632" y="238" width="34" height="8"/>
  <path class="lm-arrow" d="M690,242 L722,230 L722,254 Z"/>
  <rect class="lm-arrow" x="722" y="238" width="34" height="8"/>
  <path class="lm-route" d="M580,242 H512"/>

  <!-- Aman Hotel -->
  <text class="lm-landmark" x="632" y="306" text-anchor="middle">AMAN HOTEL</text>
  <rect class="lm-landmark-box" x="585" y="318" width="95" height="26" rx="3"/>
  <path class="lm-arrow" d="M686,331 L710,319 L710,343 Z" style="opacity:.85"/>

  <!-- Hotel Dalvi -->
  <text class="lm-landmark" x="898" y="306" text-anchor="middle">HOTEL DALVI</text>
  <rect class="lm-landmark-box" x="850" y="318" width="95" height="26" rx="3"/>
  <path class="lm-arrow" d="M840,331 L816,319 L816,343 Z" style="opacity:.85"/>

  <!-- route from VHEPL down to the highway -->
  <path class="lm-route" d="M427,288 V384"/>

  <!-- NH 160 highway (bottom) -->
  <rect class="lm-road-main" x="30" y="384" width="940" height="32"/>
  <line class="lm-road-dash" x1="30" y1="400" x2="970" y2="400"/>
  <text class="lm-road-title" x="500" y="374" text-anchor="middle">NH 160 — MUMBAI–NASHIK HIGHWAY</text>
  <path class="lm-arrow" d="M352,446 L384,434 L384,458 Z"/>
  <rect class="lm-arrow" x="384" y="442" width="36" height="8"/>
  <text class="lm-dir" x="432" y="452" text-anchor="start">MUMBAI</text>
  <path class="lm-arrow" d="M760,446 L728,434 L728,458 Z"/>
  <rect class="lm-arrow" x="692" y="442" width="36" height="8"/>
  <text class="lm-dir" x="682" y="452" text-anchor="end">KASARA – NASHIK</text>

  <!-- Ombermali Railway Station with flanking track hatching -->
  <line class="lm-rail" x1="655" y1="502" x2="742" y2="502"/>
  <line class="lm-rail-tick" x1="668" y1="492" x2="668" y2="512"/>
  <line class="lm-rail-tick" x1="686" y1="492" x2="686" y2="512"/>
  <line class="lm-rail-tick" x1="704" y1="492" x2="704" y2="512"/>
  <line class="lm-rail-tick" x1="722" y1="492" x2="722" y2="512"/>
  <rect class="lm-landmark-box" x="742" y="470" width="216" height="62" rx="4"/>
  <text class="lm-callout-title" x="850" y="496" text-anchor="middle">OMBERMALI</text>
  <text class="lm-callout-title" x="850" y="514" text-anchor="middle">RAILWAY STATION</text>
  <line class="lm-rail" x1="958" y1="502" x2="1000" y2="502"/>
  <line class="lm-rail-tick" x1="970" y1="492" x2="970" y2="512"/>
  <line class="lm-rail-tick" x1="988" y1="492" x2="988" y2="512"/>
</svg>
'''

def location_map(section, eyebrow, title, note=None, svg=None, distances=None):
    id = next_id()
    note_html = '<p class="slide-sub reveal reveal-d1">{0}</p>'.format(nb(note)) if note else ""
    dist_html = ""
    if distances:
        rows = "".join(
            "<tr><td>{0}</td><td>{1} km</td></tr>".format(esc(loc), esc(km)) for loc, km in distances
        )
        dist_html = ('<div class="table-wrap location-map-distances reveal reveal-d3">'
                      '<table class="spec-table"><thead><tr><th>Location</th><th>Distance</th></tr></thead>'
                      '<tbody>{0}</tbody></table></div>').format(rows)
    body = '''
    <section class="slide tpl-locationmap" id="s{id}" data-section="{section}">
      <div class="slide-inner">
        <div class="eyebrow reveal">{eyebrow}</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        {note}
        <div class="location-map reveal reveal-d2">{svg}{dist}</div>
      </div>
    </section>'''.format(id=id, section=esc(section), eyebrow=esc(eyebrow), title=title, note=note_html,
                          svg=svg or _LOCATION_MAP_SVG, dist=dist_html)
    add(id, section, "locationmap", body)

def _cell(c):
    """A cell is normally a string; a list renders as stacked itemised rows
    — (dimension, name, area) triples in the three-colour scheme — so long
    multi-entry values (covered bays, crane fleets) never collapse into a
    semicolon run-on paragraph."""
    if not isinstance(c, (list, tuple)):
        return "<td>{0}</td>".format(nb(c))
    items = []
    for entry in c:
        dim, name, area = (tuple(entry) + ("", ""))[:3]
        items.append(
            '<div class="cell-item"><span class="ci-dim">{0}</span>{1}{2}</div>'.format(
                esc(dim),
                '<span class="ci-name">{0}</span>'.format(esc(name)) if name else "",
                '<span class="ci-area">{0}</span>'.format(esc(area)) if area else ""))
    return '<td class="cell-list">{0}</td>'.format("".join(items))

def data_table(section, eyebrow, title, tables, note=None, sub=None, columns=1, dense=False, headers=None):
    id = next_id()
    if headers is None:
        headers = [True] * len(tables)
    blocks = []
    for t, has_header in zip(tables, headers):
        if has_header:
            thead = "<thead><tr>" + "".join("<th>{0}</th>".format(nb(c)) for c in t[0]) + "</tr></thead>"
            body_rows = t[1:]
        else:
            thead = ""
            body_rows = t
        rows = "".join(
            "<tr>" + "".join(_cell(c) for c in row) + "</tr>" for row in body_rows
        )
        blocks.append('<div class="table-wrap reveal reveal-d2"><table class="spec-table">{0}<tbody>{1}</tbody></table></div>'.format(thead, rows))
    note_html = '<p class="table-note reveal reveal-d3">{0}</p>'.format(nb(note)) if note else ""
    tables_html = "".join(blocks)
    if columns and columns > 1:
        tables_html = '<div class="table-grid-{0}col">{1}</div>'.format(columns, tables_html)
    tpl_cls = "tpl-table dense" if dense else "tpl-table"
    body = '''
    <section class="slide {tpl_cls}" id="s{id}" data-section="{section}">
      <div class="slide-inner">
        <div class="eyebrow reveal">{eyebrow}</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        {sub}
        {tables}
        {note}
      </div>
    </section>'''.format(id=id, tpl_cls=tpl_cls, section=esc(section), eyebrow=esc(eyebrow), title=title,
                          sub='<p class="slide-sub reveal reveal-d1">{0}</p>'.format(nb(sub)) if sub else "",
                          tables=tables_html, note=note_html)
    add(id, section, "table", body)

def spec(section, eyebrow, title, client, specs, slide_no, images_count=None, extra=None, table=None, milestone=None, media_layout=None, layout=None, files=None, fill=False, panel_pos=None, emphasis=False):
    id = next_id()
    if files is None:
        files = media_files(slide_no, images_count)
    stack = resolve_stack(files, layout)
    tpl_cls = "tpl-spec layout-stack" if stack else "tpl-spec"
    rows = "".join(
        '<div class="spec-row"><div class="k">{0}</div><div class="v">{1}</div></div>'.format(esc(k), nb(v))
        for k, v in specs
    )
    client_html = ""
    if client:
        client_html = '<div class="client-badge reveal reveal-d2"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m-1 4h1m4-4h1m-1 4h1M9 21v-4h6v4"/></svg>{0}</div>'.format(esc(client))
    extra_html = '<p class="slide-sub reveal reveal-d3">{0}</p>'.format(nb(extra)) if extra else ""
    milestone_html = ""
    if milestone:
        milestone_html = '<div class="spec-milestone reveal reveal-d3">{0}</div>'.format(nb(milestone))
    table_html = ""
    if table:
        thead = "<thead><tr>" + "".join("<th>{0}</th>".format(nb(c)) for c in table[0]) + "</tr></thead>"
        trows = "".join("<tr>" + "".join("<td>{0}</td>".format(nb(c)) for c in row) + "</tr>" for row in table[1:])
        table_html = ('<div class="table-wrap spec-extra-table reveal reveal-d3">'
                       '<table class="spec-table">{0}<tbody>{1}</tbody></table></div>').format(thead, trows)
    # Single-photo slides become a full-bleed showcase: the photo owns the
    # whole slide (uncropped, over a blurred fill) and the spec card floats
    # over its lower portion as a bottom strip — so the one photo is shown
    # once, as large as possible, instead of duplicated into hero + band.
    # With layout="showcase" the same treatment tiles 2–4 photos into
    # full-height cells (n2 = 2 cols, n3 = 3 cols, n4 = 2×2), each photo
    # uncropped over its own blurred fill.
    if files and layout != "split" and (len(files) == 1 or layout == "showcase"):
        shown = files[:4]
        style = ""
        if len(shown) == 1:
            blur = "" if fill else '<img class="media-blur" data-src="{f}" alt="">'.format(f=shown[0])
            canvas = blur + '<img class="media-full" data-src="{f}" alt="">'.format(f=shown[0])
            n_cls = ""
        else:
            cell_items, arr_cls = arrange_showcase([(f, "") for f in shown])
            if fill:
                clear = _panel_clear_cells(len(shown), arr_cls) if not table else set()
                canvas = "".join(
                    '<div class="showcase-cell{pc}">'
                    '<img class="media-full" data-src="{f}" alt="">'
                    '</div>'.format(f=f, pc=" panel-clear" if i in clear else "")
                    for i, (f, _) in enumerate(cell_items))
                style = fill_style([f for f, _ in cell_items], arr_cls)
                # emphasis: give the first (main) photo the lion's share of the row
                if emphasis and len(cell_items) == 2:
                    style = ' style="grid-template-columns:2.4fr 1fr"'
            else:
                canvas = "".join(
                    '<div class="showcase-cell">'
                    '<img class="media-blur" data-src="{f}" alt="">'
                    '<img class="media-full" data-src="{f}" alt="">'
                    '</div>'.format(f=f) for f, _ in cell_items)
            n_cls = " n{0}{1}".format(len(shown), arr_cls)
        # a spec table is too tall for the bottom strip — dock the panel on the
        # right edge instead so it never covers the photos
        side_cls = " panel-side" if table else ""
        # short-spec showcase slides (a headline + a couple of spec pairs) get a
        # compact panel: it shrinks to fit-content and docks bottom-left instead
        # of stretching a full-width blurred band across the photos.
        if not table and not extra and len(specs) <= 3:
            side_cls += " panel-compact"
        if fill:
            side_cls += " photo-fill"
        if panel_pos:
            side_cls += " panel-" + panel_pos
        body = '''
    <section class="slide tpl-spec layout-showcase{side_cls}" id="s{id}" data-section="{section}">
      <div class="showcase-canvas{n_cls}"{style} aria-hidden="true">
        {canvas}
      </div>
      <div class="slide-inner">
        <div class="showcase-panel reveal reveal-d1">
          <div class="eyebrow">{eyebrow}</div>
          <div class="showcase-head">
            <h2 class="slide-title">{title}</h2>
            {client}
          </div>
          {extra}
          <div class="spec-list reveal reveal-d2">{rows}</div>
          {milestone}
          {table}
        </div>
      </div>
    </section>'''.format(id=id, section=esc(section), canvas=canvas, n_cls=n_cls, side_cls=side_cls, style=style,
                          eyebrow=esc(eyebrow), title=title, client=client_html, extra=extra_html,
                          rows=rows, milestone=milestone_html, table=table_html)
        add(id, section, "spec", body)
        return
    # The stack layout puts a compact content card beside a full-width image
    # band, which otherwise leaves the strip next to the card empty. Peel one
    # image off into a "hero" that fills exactly that strip. Single-image
    # slides never reach here (they take the showcase branch above), so the
    # band always has at least one photo of its own.
    hero_html = ""
    band_files = files
    if stack:
        hero_html = hero_img(files)
        band_files = files[1:]
    body = '''
    <section class="slide {tpl_cls}" id="s{id}" data-section="{section}">
      <div class="slide-inner">
        <div class="eyebrow reveal">{eyebrow}</div>
        <div class="spec-grid">
          {hero}
          <div class="spec-media reveal reveal-d2">{media}</div>
          <div class="spec-content">
            <h2 class="slide-title reveal reveal-d1">{title}</h2>
            {client}
            {extra}
            <div class="spec-list reveal reveal-d3">{rows}</div>
            {milestone}
          </div>
        </div>
        {table}
      </div>
    </section>'''.format(id=id, tpl_cls=tpl_cls, section=esc(section), eyebrow=esc(eyebrow), title=title, hero=hero_html,
                          media=media_grid(band_files, stack, media_layout), client=client_html, extra=extra_html, rows=rows,
                          milestone=milestone_html, table=table_html)
    add(id, section, "spec", body)

def photo_showcase(section, eyebrow, title, items, sub=None, fill=False):
    """Full-bleed photo slide: 2–4 full-height cells, each photo shown whole
    over its own blurred fill (same recipe as the spec showcase), with the
    title overlaid on a top scrim and an optional caption chip pinned to the
    bottom of each cell. items: list of (img_src, caption-or-None).
    fill=True drops the blurred backdrop: photos fill their aspect-weighted
    cells edge-to-edge (object-fit: cover, minimal crop)."""
    id = next_id()
    cell_items, arr_cls = arrange_showcase(list(items))
    blur_tpl = '' if fill else '<img class="media-blur" data-src="{f}" alt="" aria-hidden="true">'
    cells = "".join(
        ('<div class="showcase-cell">' + blur_tpl +
         '<img class="media-full" data-src="{f}" alt="">'
         '{cap}</div>').format(
            f=src,
            cap='<div class="showcase-cap">{0}</div>'.format(nb(cap)) if cap else "")
        for src, cap in cell_items)
    sub_html = '<p class="slide-sub">{0}</p>'.format(nb(sub)) if sub else ""
    fill_cls = " photo-fill" if fill else ""
    style = fill_style([src for src, _ in cell_items], arr_cls) if fill else ""
    body = '''
    <section class="slide tpl-spec layout-showcase showcase-photos{fill_cls}" id="s{id}" data-section="{section}">
      <div class="showcase-canvas n{n}{arr_cls}"{style}>
        {cells}
      </div>
      <div class="slide-inner">
        <div class="showcase-titlebar reveal reveal-d1">
          <div class="eyebrow">{eyebrow}</div>
          <h2 class="slide-title">{title}</h2>
          {sub}
        </div>
      </div>
    </section>'''.format(id=id, section=esc(section), n=min(len(items), 4), arr_cls=arr_cls, cells=cells,
                          fill_cls=fill_cls, style=style, eyebrow=esc(eyebrow), title=title, sub=sub_html)
    add(id, section, "spec", body)

def gallery_cols(n):
    """Pick a column count (3 or 4) that leaves the fewest empty cells in the
    last row, so galleries never end with a stray blank tile."""
    if n <= 4:
        return max(n, 1)
    def empty_cells(c):
        return (c - n % c) % c
    return min((4, 3), key=lambda c: (empty_cells(c), -c))

def gallery(section, eyebrow, title, slide_no, caption=None, sub=None):
    id = next_id()
    if isinstance(slide_no, (list, tuple)):
        files = []
        for sn in slide_no:
            files.extend(IMGS(sn))
    else:
        files = IMGS(slide_no)
    imgs = "".join(media_frame(f) for f in files)
    cap = '<p class="gallery-caption reveal reveal-d3">{0}</p>'.format(nb(caption)) if caption else ""
    cols = gallery_cols(len(files))
    body = '''
    <section class="slide tpl-gallery" id="s{id}" data-section="{section}">
      <div class="slide-inner">
        <div class="eyebrow reveal">{eyebrow}</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        {sub}
        <div class="gallery-grid reveal reveal-d2" style="grid-template-columns: repeat({cols}, 1fr)">{imgs}</div>
        {cap}
      </div>
    </section>'''.format(id=id, section=esc(section), eyebrow=esc(eyebrow), title=title,
                          sub='<p class="slide-sub reveal reveal-d1">{0}</p>'.format(nb(sub)) if sub else "",
                          imgs=imgs, cap=cap, cols=cols)
    add(id, section, "gallery", body)

_WATER_SVG = '''
<svg class="water-svg" viewBox="0 0 920 640" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Rainwater harvesting flow: roof runoff is piped to an underground filtration plant, stored in a 400,000 litre tank and pumped to campus uses; overflow recharges groundwater">
  <!-- below-grade band -->
  <rect class="ws-underground" x="0" y="400" width="920" height="240"/>
  <line class="ws-ground" x1="20" y1="400" x2="900" y2="400"/>
  <text class="ws-sub" x="24" y="424">BELOW GROUND</text>

  <!-- rain cloud + drops -->
  <path class="ws-cloud" d="M110 118a34 34 0 0 1 33-26 40 40 0 0 1 76-8 30 30 0 0 1 41 28 24 24 0 0 1-4 47H132a30 30 0 0 1-22-41z"/>
  <g class="ws-rain">
    <line x1="112" y1="182" x2="104" y2="204"/><line x1="152" y1="176" x2="144" y2="198"/>
    <line x1="192" y1="184" x2="184" y2="206"/><line x1="232" y1="174" x2="224" y2="196"/>
    <line x1="268" y1="182" x2="260" y2="204"/><line x1="138" y1="212" x2="130" y2="234"/>
    <line x1="212" y1="214" x2="204" y2="236"/><line x1="252" y1="208" x2="244" y2="230"/>
  </g>

  <!-- workshop building -->
  <polygon class="ws-build" points="58,258 186,214 314,258 314,400 58,400"/>
  <polyline class="ws-roof" points="48,262 186,214 324,262"/>
  <rect class="ws-band" x="58" y="300" width="256" height="16"/>
  <text class="ws-label" x="186" y="340" text-anchor="middle">WORKSHOP ROOF</text>
  <text class="ws-sub" x="186" y="362" text-anchor="middle">rain collection</text>

  <!-- downpipe: roof -> filtration -->
  <path class="ws-pipe" d="M318 262 L336 262 L336 470 L364 470"/>
  <path class="ws-flow" d="M318 262 L336 262 L336 470 L364 470"/>

  <!-- filtration plant -->
  <rect class="ws-node" x="364" y="434" width="112" height="76" rx="10"/>
  <line class="ws-filter" x1="380" y1="458" x2="460" y2="458"/>
  <line class="ws-filter" x1="380" y1="472" x2="460" y2="472"/>
  <line class="ws-filter" x1="380" y1="486" x2="460" y2="486"/>
  <text class="ws-label" x="420" y="536" text-anchor="middle">FILTRATION PLANT</text>

  <!-- pipe: filtration -> tank -->
  <path class="ws-pipe" d="M476 470 L532 470"/>
  <path class="ws-flow" d="M476 470 L532 470"/>

  <!-- storage tank -->
  <rect class="ws-node" x="532" y="424" width="204" height="106" rx="12"/>
  <path class="ws-water" d="M540 462 q17 -8 34 0 t34 0 t34 0 t34 0 t34 0 t17 0 v60 a10 10 0 0 1 -10 10 h-167 a10 10 0 0 1 -10 -10 z"/>
  <text class="ws-label" x="634" y="500" text-anchor="middle">STORAGE TANK</text>
  <text class="ws-strong" x="634" y="521" text-anchor="middle">400,000 L</text>
  <text class="ws-label" x="634" y="556" text-anchor="middle">UNDERGROUND STORAGE</text>

  <!-- pump riser + distribution -->
  <path class="ws-pipe" d="M660 424 L660 132 L688 132"/>
  <path class="ws-flow" d="M660 424 L660 132 L688 132"/>
  <path class="ws-pipe" d="M660 212 L688 212"/><path class="ws-flow" d="M660 212 L688 212"/>
  <path class="ws-pipe" d="M660 292 L688 292"/><path class="ws-flow" d="M660 292 L688 292"/>
  <path class="ws-pipe" d="M660 372 L688 372"/><path class="ws-flow" d="M660 372 L688 372"/>
  <circle class="ws-pump" cx="660" cy="404" r="9"/>
  <text class="ws-sub" x="676" y="409">pump</text>

  <!-- use chips -->
  <g class="ws-chip"><rect x="688" y="110" width="212" height="44" rx="22"/><text x="794" y="137" text-anchor="middle">GARDENS &amp; LANDSCAPING</text></g>
  <g class="ws-chip"><rect x="688" y="190" width="212" height="44" rx="22"/><text x="794" y="217" text-anchor="middle">LIVESTOCK WATER</text></g>
  <g class="ws-chip"><rect x="688" y="270" width="212" height="44" rx="22"/><text x="794" y="297" text-anchor="middle">CAR &amp; DOG WASHING</text></g>
  <g class="ws-chip"><rect x="688" y="350" width="212" height="44" rx="22"/><text x="794" y="377" text-anchor="middle">FIRE &amp; EMERGENCY WATER</text></g>

  <!-- overflow -> groundwater -->
  <path class="ws-pipe" d="M736 500 L790 500 L790 574"/>
  <path class="ws-flow" d="M736 500 L790 500 L790 574"/>
  <polygon class="ws-arrow" points="790,590 782,574 798,574"/>
  <text class="ws-label" x="790" y="614" text-anchor="middle">OVERFLOW → GROUNDWATER</text>
</svg>'''

def water_slide(section, eyebrow, title):
    """Merged sustainability slide: custom SVG flow diagram of the rainwater
    harvesting system (replacing the stock clip-art photo) beside typeset
    process copy and the wastewater-recycling summary."""
    id = next_id()
    body = '''
    <section class="slide tpl-water" id="s{id}" data-section="{section}">
      <div class="slide-inner">
        <div class="eyebrow reveal">{eyebrow}</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        <div class="water-grid">
          <div class="water-diagram reveal reveal-d2">{svg}</div>
          <div class="water-content reveal reveal-d3">
            <h3>Rainwater Harvesting</h3>
            <ol class="water-steps">
              <li>Rain falling on the workshop roofs is channelled through collection piping to an underground filtration plant.</li>
              <li>The filtered water is stored in an underground tank with a <b>400,000-litre</b> capacity and pumped out for use across the campus.</li>
            </ol>
            <h3>Wastewater Recycling Plant</h3>
            <p>Wastewater is collected and treated in our on-site recycling plant; the treated water is reused for drip irrigation, garden watering and toilet flushing — cutting fresh-water demand across the campus.</p>
            <div class="chip-row">
              <span class="chip on">Reduced water pollution</span>
              <span class="chip on">No water transport needed</span>
              <span class="chip on">Improved sustainability</span>
            </div>
          </div>
        </div>
      </div>
    </section>'''.format(id=id, section=esc(section), eyebrow=esc(eyebrow), title=esc(title), svg=_WATER_SVG)
    add(id, section, "water", body)

_CLOSER_ICONS = {
    "phone": '<path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.24 11 11 0 0 0 3.5.56 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1 11 11 0 0 0 .56 3.5 1 1 0 0 1-.24 1z"/>',
    "email": '<path d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/><path d="m3.5 6.5 8.5 6 8.5-6" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    "web": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3 12h18M12 3c2.5 2.6 2.5 15.4 0 18M12 3c-2.5 2.6-2.5 15.4 0 18" fill="none" stroke="currentColor" stroke-width="1.6"/>',
}

def _closer_icon(text):
    t = text.lower()
    if "@" in t:
        return "email"
    if "www" in t or ".com" in t:
        return "web"
    return "phone"

def closer(section, title_html, contact_lines, bg_img, locations=None):
    id = next_id()
    chips = "".join(
        '<a class="closer-chip" href="{href}">'
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{icon}</svg>'
        '<span>{label}</span></a>'.format(
            icon=_CLOSER_ICONS[_closer_icon(c)],
            label=esc(c.replace("TEL: ", "")),
            href=("mailto:" + c if _closer_icon(c) == "email"
                  else "https://" + c if _closer_icon(c) == "web"
                  else "tel:" + c.replace("TEL: ", "").replace(" ", "")))
        for c in contact_lines)
    loc_html = ""
    if locations:
        loc_parts = []
        for i, l in enumerate(locations):
            if i:
                loc_parts.append('<span class="sep"></span>')
            loc_parts.append('<span><b>{0}</b> {1}</span>'.format(esc(l[0]), nb(l[1])))
        loc_html = '<div class="closer-locations reveal reveal-d3">{0}</div>'.format("".join(loc_parts))
    body = '''
    <section class="slide tpl-closer" id="s{id}" data-section="{section}">
      {bg}
      <div class="slide-inner">
        <img class="cover-logo reveal" src="assets/images/brand/vitech-lockup.png" alt="Vitech Group of Companies">
        <h1 class="reveal reveal-d1">{title}</h1>
        <div class="cover-rule reveal reveal-d1"></div>
        <div class="closer-contact reveal reveal-d2">{chips}</div>
        {loc}
      </div>
    </section>'''.format(id=id, section=esc(section), bg=lazybg(bg_img), title=title_html,
                          chips=chips, loc=loc_html)
    add(id, section, "closer", body)

# ===========================================================================
# SLIDE CONTENT
# ===========================================================================

# ---- 1. Cover ---------------------------------------------------------
cover("Cover",
      'VITECH <span>GROUP</span> OF COMPANIES',
      [
        ("Vitech Heavy Equipments Pvt. Ltd.", "Shahapur, Maharashtra, India"),
        ("Vitech Equipments Pvt. Ltd.", "Rabale, Navi Mumbai, Maharashtra, India"),
        ("Vitech Fabricators Pvt. Ltd.", "Rabale, Navi Mumbai, Maharashtra, India"),
      ],
      ["TEL: +91-9372766457 / 58 / 60", "sales@vitechgroupindia.com  ·  www.vitechgroupindia.com"],
      1,
      tagline="Mechanical Design & Fabrication of Critical Static & Process Equipment",
      stats=[
        ("1992", "Established"),
        ("33+", "Years of Experience"),
        ("3", "Manufacturing Units"),
        ("ISO · ASME", "Certified & Approved"),
      ])

# ---- 2. Company Introduction -------------------------------------------
prose("Company Overview", "Since 1992", "Company Introduction",
      [
        "VITECH GROUP was established in the year 1992 and is a professionally managed engineering company.",
        "VITECH is specialized in mechanical design & fabrication of equipment catering to Oil/Gas, Water & "
        "Desalination, Petrochemical, Paper & Pulp, Fertilizer, Edible Oil, Pharmaceutical, Dairy & other industries, "
        "across all grades of materials — for the last 33 years, adapting to change and working with total dedication.",
      ],
      labeled_chips=[
        {"label": "Material Grades We Fabricate",
         "items": ["Carbon Steel", "Cladded Steel", "SS 304/304L", "316/316L", "310S", "321", "347",
                   "6% Moly", "Duplex & Super Duplex SS", "Inconel 600/601/625", "Incoloy 800",
                   "Titanium (SB 265 Gr.1 & 2)", "Hastelloy C-276"]},
      ],
      fact_rows=[
        ("Certifications", "ISO 9001:2015 · ISO 14001:2015 · ISO 45001:2018"),
        ("Approvals & Stamps", "ASME U, U2, NB, R Stamp · EIL-Approved Pressure Vessels (CS up to 75 mm, SS up to 18 mm) · "
                                "IBR Certified Class 1 (pressure up to 125 kg/cm²)"),
        ("Cladded Capability", "CS + Austenitic SS Clad (304/304L/316/316L/317/317L/321/347) — vessels & columns up to 25 mm"),
        ("Piping Spool Capability", "CS up to 10″ (12.7mm) & 12–24″ (6.35mm) · SS up to 24″ (6.35mm)"),
      ],
      side_title="We specialize in",
      side_items=[
        "Critical large-size equipment (factory-cum-site fabrication)",
        "Cladded / non-cladded pressure vessels",
        "Heat exchangers",
        "Skid mounted packages",
        "Columns & reactors",
        "Storage tanks",
        "Piping spools (CS, SS, DSS/SDSS)",
      ])

# ---- 3. Engineering Capability -----------------------------------------
prose("Company Overview", "Design & Engineering", "Engineering Capability",
      ["Our design team comprises qualified & experienced design engineers and draughtsmen well versed with Indian & "
       "international codes — giving us the capability to design and fabricate both static & process equipment "
       "meeting design conditions and fabrication standards."],
      side_title="Mechanical design standards",
      side_items=["ASME Sec. I", "ASME Sec. VIII Div. 1", "ASME Sec. VIII Div. 2", "API 650", "API 660", "PD 5500", "AD 2000", "EN 13445"],
      chips=[{"t": t, "on": True} for t in ["PV Elite", "AutoCAD", "Nozzle PRO"]] +
            [{"t": t} for t in ["ANSYS Mechanical", "STAAD Pro"]],
      stats=[
        {"value": "5", "label": "Design Software Platforms"},
        {"value": "8", "label": "Design Codes & Standards"},
      ],
      center=True, bg_img=13)

# ---- 4. Industries we cater to (recovered from flattened image) -------
_industry_icons = {
  "Oil & Gas": '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M6 10h12M6 15h12"/>',
  "Paper & Pulp": '<path d="M6 3h9l3 3v15H6z"/><path d="M15 3v3h3"/><path d="M9 12h6M9 15h6M9 9h3"/>',
  "Pharmaceutical": '<rect x="9" y="3" width="6" height="18" rx="3"/><path d="M9 12h6"/>',
  "Fertilizer & Petrochemicals": '<path d="M4 21V10l5-4 5 4v11"/><path d="M14 21v-7l4-3 3 3v7"/><path d="M4 21h17"/>',
  "Water & Desalination": '<path d="M12 3s6 7 6 11a6 6 0 1 1-12 0c0-4 6-11 6-11z"/>',
  "Chemical": '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/><path d="M8 15h8"/>',
  "Edible Oil & Food": '<path d="M4 3s0 5 4 5 4-5 4-5M8 8v13M15 3c-2 0-3 2-3 4s1 4 3 4 3-2 3-4-1-4-3-4z"/><path d="M15 11v10"/>',
  "Power": '<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>',
  "Zero Liquid Discharge": '<path d="M17 3a2 2 0 0 1 2 2v2h-4V5a2 2 0 0 1 2-2z"/><path d="M12 8h9l-2 4h-9z"/><path d="M15 12v3a2 2 0 0 1-2 2H7l3 3M7 17l3-3"/>',
  "Lithium": '<rect x="3" y="8" width="16" height="10" rx="2"/><path d="M19 11v4"/><path d="M7 11v4M10 11v4"/>',
}
# Best available equipment photo per industry, cross-referenced from the project spec slides.
_industry_photos = {
  "Oil & Gas": "assets/images/slides/slide086_img02.jpg",
  "Paper & Pulp": "assets/images/slides/slide094_img02.jpg",
  "Pharmaceutical": "assets/images/slides/slide033_img02.jpg",
  "Fertilizer & Petrochemicals": "assets/images/slides/slide046_img02.jpg",
  "Water & Desalination": "assets/images/slides/slide068_img02.jpg",
  "Chemical": "assets/images/slides/slide036_img02.jpg",
  "Edible Oil & Food": "assets/images/slides/slide031_img02.jpg",
  "Power": "assets/images/slides/slide095_img02.jpg",
  "Zero Liquid Discharge": "assets/images/slides/slide072_img01.jpg",
  "Lithium": "assets/images/slides/slide082_img02.jpg",
}
def industries_slide(title, keys):
    """One 'Industries We Cater To' slide rendering the given industry tiles.
    Splitting the ten markets across three slides keeps each equipment photo
    large and legible instead of cropping ten tiles into a dense grid."""
    tiles = "".join(
      '<div class="industry-tile has-photo">'
      '<img class="industry-tile-bg" data-src="{photo}" alt="" loading="lazy">'
      '<div class="industry-tile-scrim"></div>'
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{icon}</svg>'
      '<span>{label}</span></div>'.format(
        photo=_industry_photos[t], icon=_industry_icons[t], label=esc(t)
      ) for t in keys
    )
    iid = next_id()
    body = '''
    <section class="slide tpl-visual industry-slide" id="s{id}" data-section="Company Overview">
      <div class="slide-inner">
        <div class="eyebrow reveal">Markets We Serve</div>
        <h2 class="slide-title reveal reveal-d1">{title}</h2>
        <div class="industry-grid reveal reveal-d2" style="grid-template-columns:repeat({cols},1fr)">{tiles}</div>
      </div>
    </section>'''.format(id=iid, title=title, tiles=tiles, cols=len(keys))
    add(iid, "Company Overview", "visual", body)

# Core process sectors lead; specialty and energy/advanced follow.
# Two tiles per slide (rather than 3-4) so each background photo reads at a
# much larger, far less cropped size.
industries_slide("Industries We Cater To",
    ["Oil & Gas", "Water & Desalination"])
industries_slide("Industries We Cater To — cont.",
    ["Fertilizer & Petrochemicals", "Edible Oil & Food"])
industries_slide("Industries — Process & Specialty",
    ["Chemical", "Paper & Pulp"])
industries_slide("Industries — Process & Specialty — cont.",
    ["Pharmaceutical"])
industries_slide("Industries — Energy & Advanced Materials",
    ["Power", "Zero Liquid Discharge"])
industries_slide("Industries — Energy & Advanced Materials — cont.",
    ["Lithium"])

# ---- 5. Organisation Chart (1:1 with the Quality Manual Annex-D2 chart) ----
org_chart("Company Overview", "Structure · Quality Manual Annex-D2, Rev. 4", "Organisation Chart",
    exec_chain=[
        ("Managing Director", "Mr. Charles Dsouza"),
        ("Director", "Mr. Vivek Charles Dsouza"),
        ("Vice President", "Mr. T.N. Shetty"),
    ],
    director_columns=[
        {"role": "Manager QA & QC", "names": ["Mr. Samir P.", "Mr. Deepak K."], "chain": [
            {"role": "QC Engineers **"},
            {"role": "Welding Engineer", "names": ["Mr. Samir P.", "Mr. Deepak K."]},
            {"role": "NDT Level 1 & 2 **"},
        ]},
        {"role": "Manager Accounts", "names": ["Mr. Vishwas Yadav"], "chain": [
            {"role": "Asst. Accounts", "names": ["Mrs. Usha Bisht", "Mrs. Rekha Shetty"]},
        ]},
        {"role": "HRD Officer", "names": ["Mr. Navnath", "Ms. Ruchika"]},
        {"role": "Purchase Incharge", "names": ["Mr. Yashwant S.", "Mr. Rajendra T."], "chain": [
            {"role": "Purchase Engineer", "names": ["Mr. Hitesh P.", "Mr. Ganesh R."]},
        ]},
    ],
    vp_columns=[
        {"role": "Project Manager", "names": ["Mr. Mayur B.", "Mr. Dharmendra J."], "chain": [
            {"role": "Project Engineer", "names": ["Mr. Samir G.", "Mr. Mayur D."]},
            {"role": "Mechanical Draughtsmans / CNC Programer **"},
            {"role": "CNC Operators **"},
        ]},
    ],
    gm={"role": "General Manager", "names": ["Mr. Pramod Dubey"]},
    gm_peer={"role": "Technical Manager", "names": ["Varghes Nadar"]},
    gm_branches=[
        {"role": "HSE Committee", "chain": [
            {"role": "Stores Incharge", "names": ["Mr. Mehraj S."]},
            {"role": "Stores Assistants", "names": ["Mr. Sandeep K.", "Mr. Edvin D."]},
        ]},
        {"role": "EHS Officer", "names": ["Mr. Priyesh Kumar"], "chain": [
            {"role": "Maintenance Incharge", "names": ["Mr. Milind P."]},
            {"role": "Maintenance Assistants **"},
        ]},
        {"role": "Manager Production", "names": ["1. Mr. Arun W.", "2. Mr. Chetan K."], "chain": [
            {"role": "Production Engineers **"},
            {"role": "Fitters, Welders, Grinders, Helpers & Others"},
        ]},
        {"role": "Manager Business Development", "names": ["Mr. Anthony Dsouza", "Mr. Ryan Fernandes"], "chain": [
            {"role": "Estimation Engineers **"},
        ]},
    ],
    right_columns=[
        {"role": "Manager Engineering", "names": ["Mr. Sourabh K."], "chain": [
            {"role": "Design Engineers", "names": ["Mr. Ankit Shetty", "Mr. Moreshwar"]},
            {"role": "Mechanical Draughtsmans **"},
        ]},
    ],
    footnote="** Refer list as per attached Annexure-1")

# ---- 6-8. Company Layout & Plot Overview (full-bleed, photos fill their
#           aspect-weighted cells edge-to-edge) ------------------------------
# CAD plot-layout drawing gets its own slide, shown whole (uncropped) so the
# bay tables & dimensions stay readable; the two site photos share the next.
photo_showcase("Company Overview", "Facilities", "Company Layout & Plot Overview",
    [(IMG(6, 1), None)])
photo_showcase("Company Overview", "Facilities", "Plant & Yard — Site Views",
    [(IMG(7, 1), None), (IMG(8, 1), None)])

# ---- 9. Company Layout (annotated site plan + legend) --------------------
site_plan("Company Overview", "Facilities · Vitech Heavy Equipments Pvt. Ltd, Shahapur", "Company Layout",
    "assets/images/slides/slide009_img02_final.jpg",
    legend=[
        ("group", "Operations & Workshops"),
        ("1", "Main Gate"),
        ("2", "Admin Building"),
        ("3", "Workshop — Bay 1, 2, 3"),
        ("4", "Workshop — Bay 4"),
        ("5", "Material Storage Yard"),
        ("6", "Workshop — Bay 5"),
        ("7", "Blasting & Painting Booth"),
        ("8", "Picking Passivation Bay"),
        ("group", "Sustainability & Grounds"),
        ("9", "Vegetable Garden (600 sq.mtr)"),
        ("10", "A–D — Fruit Orchard"),
        ("15", "A–B — Rain Water Harvesting"),
        ("16", "Worker Room with Recycling Plant"),
        ("group", "Animals"),
        ("11", "Japanese Koi Fish Tank"),
        ("12", "Dogs Kennel"),
        ("13", "Farm Animals (Turtle, Hen, Geese)"),
        ("14", "Cow Shed"),
        ("group", "Safety"),
        ("17", "Emergency Evacuation Area"),
    ],
    stat=("104,000", "Total Plot Area (sq. mtr.)"))

# ---- 10-15. Workshop Overview (three full-bleed slides, groupings and
#             captions follow the original deck's slides 10-12) -------------
photo_showcase("Workshop & Facilities", "Infrastructure", "Workshop Overview — Shahapur Campus",
    [(IMG(10, 4), "Workshop with Admin Building"),
     (IMG(10, 1), "Open Yard — 6,000 sq.mtr · Goliath Crane 25 MT × 39 mtr span"),
     (IMG(10, 3), "Stainless / Exotic Steel Bay — 22 × 120 mtr × 2 Nos.")], fill=True)

photo_showcase("Workshop & Facilities", "Infrastructure", "Workshop Overview — Stainless & Exotic Steel Bays",
    [(IMG(11, 1), "Stainless / Exotic Steel Bay 1 — 22 × 120 mtr"),
     (IMG(11, 2), "Stainless / Exotic Steel Bay 2 — 22 × 120 mtr")], fill=True)

photo_showcase("Workshop & Facilities", "Infrastructure", "Workshop Overview — Carbon & Cladded Steel Bays",
    [(IMG(11, 3), "Carbon Steel / Cladded Steel Bay 3 — 22 × 120 mtr"),
     (IMG(10, 2), "Carbon Steel / Cladded Steel Bay — 22 × 120 mtr")], fill=True)

photo_showcase("Workshop & Facilities", "Infrastructure", "Workshop Overview — Piping & Skid Bays",
    [(IMG(12, 1), "Piping Spool Bay 4 — 25 × 100 mtr"),
     (IMG(12, 2), "Skid Module Bay 5 — 25 × 50 mtr")], fill=True)

data_table("Workshop & Facilities", "Group Capability", "Group Infrastructure — Plot & Covered Bays",
      [
        [
          ["Manufacturing Units", "VHEPL — Shahapur, Thane", "VEPL — Rabale, Navi Mumbai", "VFPL — Rabale, Navi Mumbai"],
          ["Total Plot Area (sq. mtr.)", "104,000", "3,300", "1,000"],
          ["Covered Bays",
           [("22 × 120 mtr ×3", "Bay 3–5", "7,920 sq.mtr"),
            ("25 × 100 mtr ×1", "Skid & Piping", "2,500 sq.mtr"),
            ("25 × 50 mtr ×1", "Skid Assembly", "1,250 sq.mtr"),
            ("25 × 20 mtr ×1", "CNC Bay", "500 sq.mtr"),
            ("20 × 50 mtr ×1", "Light Fabrication", "1,000 sq.mtr")],
           [("20 × 80 mtr ×1", "Main Bay", ""),
            ("6 × 80 mtr ×1", "Auxiliary Bay", ""),
            ("8 × 80 mtr ×1", "Auxiliary Bay", "")],
           [("20 × 40 mtr ×1", "Main Bay", "")]],
          ["Open Yard / Material Storage",
           [("5,950 sq.mtr", "Open Yard", ""),
            ("2,000 sq.mtr", "Material Storage", "")],
           "—", "—"],
        ],
      ],
      note="All indications in red on the original plant plan denote provisions under construction (target completion 31 Dec 2026).")

data_table("Workshop & Facilities", "Group Capability", "Group Infrastructure — Cranes, Workforce & Capability",
      [
        [
          ["Manufacturing Units", "VHEPL — Shahapur, Thane", "VEPL — Rabale, Navi Mumbai", "VFPL — Rabale, Navi Mumbai"],
          ["EOT Crane (hook clearance 13 mtr.)",
           [("35/5T ×4", "", ""), ("15T ×2", "Bay 3 & 4", ""), ("50T/10T ×2", "", ""), ("15T ×1", "Bay 5", "")],
           [("30/10T, 20T", "", ""), ("10T, 5T ×1 each", "", "")],
           [("20T, 10T", "", "")]],
          ["Goliath Crane (hook clearance 12 mtr., span 39 mtr.)",
           [("25/5T ×1, 25T ×1", "", ""), ("15T ×4, 10T ×4", "", ""), ("7.5T ×1", "", "")], "—", "—"],
          ["Material Transfer Car",
           [("5T ×1, 25T ×3", "", ""), ("30T ×2, 25T ×1", "", ""), ("5T ×1", "", "")], "—", "—"],
          ["Skilled & Unskilled Workers, Employees", "345", "97", "30"],
        ],
        [["Group Workforce", "472 Total"], ["Single-Piece Jobs Up To", "500 tons"],
         ["Planned Combined Production", "700 MT / month"], ["Shifts", "3 / day, 6 days a week"],
         ["Capability", "Max job size: 5.5 × 55 mtr (single pc.) · Max diameter: 6 × 15 mtr length · 125 mm thk."]],
      ],
      note="We can also manufacture larger jobs in sections and reassemble in a single piece close to the port.",
      columns=1, dense=True, headers=[True, False])

# ---- 16-17. Location Map --------------------------------------------------
location_map("Workshop & Facilities", "Location", "Location Map — Vitech Heavy Equipments Pvt. Ltd. (V.H.E.P.L.)",
    svg=_LOCATION_MAP_SVG_SHAHAPUR,
    distances=[
        ("Mumbai Airport", "95"),
        ("Mumbai Port", "110"),
        ("Nhava Sheva Port", "120"),
        ("V.E.P.L. Rabale", "83"),
    ])
location_map("Workshop & Facilities", "Location", "Location Map — Vitech Equipments & Vitech Fabricators Pvt. Ltd.",
    note="Off Thane–Belapur Road (NH 348A), Rabale MIDC, Navi Mumbai — 38.4 km from Nhava Sheva Port.")

# ---- 18. Divider: Workshop Facilities ------------------------------------
divider("Workshop & Facilities", "Workshop<br><span>Facilities</span>",
        "Machinery and process capability across the Vitech Group's three manufacturing units.", bg_img=13, index_label="II")

# ---- 19-22. Workshop Facilities machinery tables --------------------------
data_table("Workshop & Facilities", "Machinery", "Workshop Facilities — Material Cutting & Preparation",
      [[
        ["Major Machinery", "VHEPL", "VEPL", "VFPL"],
        ["CNC Plasma Cutting M/C w/ bevel arrangement (SS 80mm / CS 200mm thk.)", "✓", "✓", "—"],
        ["Fully Automatic Double Column CNC Band Saw M/C", "✓", "—", "—"],
        ["Pipe Bevelling", "✓", "✓", "—"],
        ["Edge Planner Machine (declad + bevel)", "✓", "—", "—"],
      ],[
        ["Forming & Bending", "VHEPL", "VEPL", "VFPL"],
        ["Hydraulic Power Press", "200T / 1000T", "—", "300T"],
        ["Plate Bending M/C (3000mm width)", "FACCIN Italy – 125mm; Himalaya – 25mm; Himalaya – 16mm", "Himalaya – 25mm", "Himalaya – 10mm"],
      ]],
      note="All indications in red on the original machinery list denote future provisions.")

data_table("Workshop & Facilities", "Machinery", "Workshop Facilities — Automated Welding Systems",
      [[
        ["Automated Systems", "VHEPL", "VEPL", "VFPL"],
        ["Orbital Pipe Welding", "✓", "✓", "—"],
        ["Automated Tube-to-Tube Welding Head (GTAW)", "✓", "✓", "—"],
        ["Automated Pipe Spool Welding System (SAW, GTAW, GMAW, FCAW)", "✓", "—", "—"],
        ["Force TIG (German make, GTAW)", "✓", "—", "—"],
        ["Automated GMAW System (Canadian make)", "✓", "—", "—"],
        ["Automated Pipe Spool Cutting, Bevelling & Setup Stations", "✓", "—", "—"],
        ["Station for Shell Cir-Seam Quick Setup", "✓", "—", "—"],
      ]])

data_table("Workshop & Facilities", "Machinery", "Workshop Facilities — Weld Overlay, Blasting & PWHT",
      [
        [["Automated Systems", "VHEPL", "VEPL", "VFPL"],
         ["Weld Overlay Machine (2″ dia & above)", "✓", "✓", "✓"],
         ["Automated Welding Machine — Long Seam & Cir Seam (SAW, GTAW, GMAW, FCAW)", "✓", "—", "—"]],
        [["Blasting, Painting, PWHT & Pickling", "VHEPL", "VEPL", "VFPL"],
         ["Blasting & Painting Booth", "✓", "Outsourced", "Outsourced"],
         ["Modular PWHT Electric Furnace", "✓", "Outsourced", "Outsourced"],
         ["Pickling & Passivation Bath", "✓", "✓", "✓"]],
        [["In-House Capability", ""],
         ["Blasting & Painting", "5.5 mtr X 40 mtr"],
         ["Pickling & Passivation Methods", "Paste cleaning & spraying"]],
      ],
      columns=2, dense=True)

data_table("Workshop & Facilities", "Machinery", "Workshop Facilities — Machining & Auxiliary Equipment",
      [
        [["Semi-Automatic Welding & Machining", "VHEPL", "VEPL", "VFPL"],
         ["Submerged Arc Welding", "✓", "✓", "—"],
         ["GTAW & GMAW", "✓", "✓", "✓"],
         ["Radial Drilling Machine", "✓", "✓", "✓"],
         ["Vertical Turret Lathe", "✓", "—", "—"],
         ["Lathe Machine", "✓", "—", "—"]],
        [["Auxiliary Machines", "VHEPL", "VEPL", "VFPL"],
         ["Welding Positioners", "15T", "—", "—"],
         ["Tank Rotators", "35T ×10, 40T ×5, 50T ×4, 60T ×4, 100T ×4", "35T ×8, 40T ×3, 50T ×2, 100T ×4", "—"]],
      ])

# ---- 23. Divider: Automation Systems --------------------------------------
divider("Automation & Welding", "Automation<br><span>Systems</span>",
        "PLC-controlled and automated welding, cutting & overlay systems purpose-built for repeatable, high-integrity fabrication.",
        bg_img=24, index_label="III")

# ---- 24-29. Automated welding / overlay / pipe systems --------------------
spec("Automation & Welding", "Automated Welding", "Tube-to-Tube Sheet Welding on Automated Welding Head", "",
     [("Process", "Titanium Gr.1 tube to Titanium Gr.2 tubesheet — GTAW welding in process")],
     24, layout="showcase")

spec("Automation & Welding", "Weld Overlay", "Weld Overlay Capability", "",
     [("Overlay A", "SA 516 Gr. 70 + SA 240 Gr. 317L overlay"),
      ("Overlay B", "SA 240 Gr. 316 + Hastelloy C 276 overlay")],
     25, layout="showcase", fill=True,
     table=[
        ["Sr.", "Description", "Process", "Material", "Layers"],
        ["01", "Shell: min. ID 300mm (& above) × 40mm thk. × 1000mm lg. (max.)", "GTAW & FCAW", "SS 304/316/317L/Hastelloy C276", "3"],
        ["02", "LWNRF: 2″ (50.8mm ID, & above) × 1000mm lg. (max.)", "SMAW & GTAW", "SS 304/316/317L/Hastelloy C276", "3"],
        ["03", "90° Elbow: 2″ ID (& above)", "SMAW", "SS 304/316/317L/Hastelloy C276", "3"],
        ["04", "Pipe: 3″ Sch. 80 (& above) × 1,000mm lg. (max.)", "SMAW, GTAW, GMAW & FCAW", "SS 304/316/317L/Hastelloy C276", "3"],
        ["05", "Pipe: 2″ Sch. 80 (& above) × 1000mm lg. (max.)", "GTAW & FCAW", "SS 304/316/317L/Hastelloy C276", "3"],
     ])

spec("Automation & Welding", "PLC Controlled", "Pipe Spool Bevelling, Cutting & Setup Stations", "",
     [("Capability", "Up to 24″ NB"), ("Length", "12 mtr.")],
     None, layout="showcase", files=[IMG(27, 1), IMG(27, 2)])

spec("Automation & Welding", "PLC Controlled", "Pipe Spool Setup Station — Detail", "",
     [("Capability", "Up to 24″ NB"), ("Length", "12 mtr.")],
     None, layout="showcase", files=[IMG(27, 3)])

spec("Automation & Welding", "Automated Systems", "Pipe Welding on Automated System / Orbital Pipe Machine", "",
     [("Automated system", "3″ NB to 20″ NB pipe, length 12 mtr."),
      ("Orbital pipe machine", "19mm OD – 77mm OD")],
     28, layout="showcase")

spec("Automation & Welding", "Automated Machines", "Welding on Automated Machines", "",
     [("Force TIG (German make)", "Square butt joint welding up to 10mm in single pass"),
      ("Automated GMAW system (Canadian make)", "Specialised for GMAW & FCAW in 1G, 2G & 3G positions, carbon steel & stainless steel")],
     29, layout="showcase", fill=True)

# ---- 82. Lithium ----------------------------------------------------------
spec("Oil, Gas, Lithium & Aerospace", "Lithium", "Tanks and Vessels", "Lithium Nevada Thacker Pass Project (USA)",
     [("Material", "Duplex SST 2205 / SA240 Gr 316L"),
      ("Total qty / weight", "15 Nos. / 30 MT")],
     82, layout="showcase", fill=True)

# ---- 83. Divider: Oil & Petrochemical --------------------------------------
divider("Oil, Gas, Lithium & Aerospace", "Oil &<br><span>Petrochemical</span>",
        "Heavy towers, reflux drums and static mixers delivered for Reliance, HPCL, Cairn Energy and more.",
        bg_img=84, index_label="IV")

spec("Oil, Gas, Lithium & Aerospace", "Oil & Petrochemical", "Tube Bundle for Heat Exchanger", "Reliance Industries, Nagothane",
     [("Tubesheet", "SA965-F304/304L TP304/304L"),
      ("Tube material", "SA213 TP304/304L"),
      ("Size", "Ø 1350/1917mm × 10258mm overall length"),
      ("Qty / Weight", "4 / 105 MT")],
     84)

spec("Oil, Gas, Lithium & Aerospace", "Oil & Petrochemical", "Ethane Tower Heat Pump Compressor Reflux Drum", "Reliance Industries, Nagothane",
     [("Material", "SA 240 Gr. 304/304L dual certified"),
      ("Size", "Ø 4000mm ID × 13,809mm L × 52mm thk"),
      ("Total qty / weight", "1 No. / 97 MT")],
     85, layout="showcase", fill=True)

spec("Oil, Gas, Lithium & Aerospace", "Oil & Gas", "Demethanizer Prestripper No.2 — New SS Tower", "Reliance Industries — Nagothane Refinery",
     [("Material", "SA 240 Gr. 304/304L dual certified"),
      ("Size", "Ø 1600/2500mm ID × 46,000mm L"),
      ("Total qty / weight", "1 No. / 82.5 MT")],
     86)

spec("Oil, Gas, Lithium & Aerospace", "Oil & Gas", "Produced Water Skids", "Cairn Energy, Rajasthan, India",
     [("Material", "Carbon Steel / Duplex"),
      ("Qty", "22 Nos."),
      ("Scope", "Procurement + fabrication of piping spools + structure + assembly + E&I procurement & installation + heat tracing + insulation + FAT")],
     87, layout="showcase", fill=True)

spec("Oil, Gas, Lithium & Aerospace", "Oil & Gas", "Produced Water Skids — Fabrication Progress", "Cairn Energy, Rajasthan, India",
     [("Material", "Carbon Steel / Duplex"),
      ("Qty", "22 Nos."),
      ("Scope", "Procurement + fabrication of piping spools + structure + assembly + E&I procurement & installation + heat tracing + insulation + FAT")],
     88, layout="showcase", fill=True, files=[IMG(88, 1), IMG(88, 3)])

spec("Oil, Gas, Lithium & Aerospace", "Oil & Gas", "Static Mixer (ASME U Stamp — EIL)", "HPCL Visakhapatnam (EIL)",
     [("Material", "Carbon steel body (SA 106 Gr.B) with SS 316 steam tracing tubes"),
      ("Thickness", "Sch. 160"),
      ("Total qty", "1 No.")],
     89)

spec("Oil, Gas, Lithium & Aerospace", "Oil & Petrochemical", "Inlet & Outlet Distributors", "L&T, India",
     [("Material", "Inconel 601 (UNS06601)"),
      ("Size", "Ø 2.1 mtr × 2.08 mtr L"),
      ("Qty / Weight", "10 sets / 2 tons")],
     90, layout="showcase")

spec("Oil, Gas, Lithium & Aerospace", "Oil & Gas", "Storage Tank — Insulation + Sacrificial Anode + Internal Glass Flake Lining", "Cairn Energy, India",
     [("Material", "SA 516 Gr.70 NACE"),
      ("Size", "Ø 5.55 mtr × 9.5 mtr length"),
      ("Qty / Weight", "2 Nos. / 28 tons")],
     91)

spec("Oil, Gas, Lithium & Aerospace", "Oil & Gas / Petrochemical", "Static Mixers (ASME U Stamp) with Grayloc Connectors", "NRL Expansion Project, Sulzer Chemtech India Pvt Ltd",
     [("Mixer A", "SA 182 F347 & SA 182 F321 — Ø 466.7 & 482.7mm OD × 4000mm lg. × 50mm thk — 8 tons, 1 No."),
      ("Mixer B", "SA 183 F321 — Ø 457.2mm OD × 4000mm lg. × 50mm thk — 7 tons, 1 No.")],
     92, layout="showcase", fill=True)

spec("Oil, Gas, Lithium & Aerospace", "Aerospace", "Exhaust Collector — U Stamp", "Pratt & Whitney, Canada",
     [("Material", "SS 321"),
      ("Size", "Ø 1.176 mtr × 32mm thk × 1 mtr L"),
      ("Qty / Weight", "1 No. / 5 tons")],
     93, layout="showcase", fill=True)

spec("Oil, Gas, Lithium & Aerospace", "Paper & Pulp", "Evaporator — Effect 7", "APL, India",
     [("Material", "SA 240 Gr. 304 & SA 516 Gr. 70; tubesheets SA 240 Gr. 304L; tubes SA 249 TP 304L"),
      ("Size", "Ø 3.7/4.4 mtr × 20.2 mtr L"),
      ("Tubes", "50.8mm OD × 1.2mm min. thk × 11.5 mtr L — qty 2,199 Nos."),
      ("Qty / Weight", "1 No. / 100 tons")],
     94)

spec("Oil, Gas, Lithium & Aerospace", "Paper & Pulp · Flue Gas Desulphurisation", "Titanium Clad Ducts", "NTPC Ltd (GE Power) — Sipat & Simhadri, India",
     [("Duct set A", "IS2062 + Ti Gr.1 (7+2mm) — Ø 9.8 mtr — 50 tons each, 2 Nos."),
      ("Duct set B", "IS2062 + Ti Gr.1 (7+2mm) — Ø 8.45 mtr — 40 tons, 1 No.")],
     95)

# ---- 30. Divider: Food Processing -----------------------------------------
divider("Food Processing & Oleo Chemical", "Food<br><span>Processing</span>",
        "Spiral heat exchangers, evaporators and reactors engineered for the world's leading food & agri-processing clients.",
        bg_img=31, index_label="V")

spec("Food Processing & Oleo Chemical", "Food Processing", "Spiral Heat Exchangers", "",
     [("Material", "SS 304L with high & low pressure steam coils, under PED"),
      ("Size", "1.6 mtr to 4.8 mtr dia. × up to 40 mtr length"),
      ("Quantity", "150+ such jobs manufactured to date"),
      ("Weight", "60 – 120 tons")],
     None, layout="showcase", fill=True, files=[IMG(31, 1)],
     extra="For Europe, Russia, South America, USA, Africa, Asia")

spec("Food Processing & Oleo Chemical", "Food Processing", "Spiral Heat Exchangers — Coil Detail", "",
     [("High pressure", "Steam coils"), ("Low pressure", "Clamping coils")],
     None, layout="showcase", fill=True, files=[IMG(32, 1), IMG(32, 2)])

spec("Food Processing & Oleo Chemical", "Food Processing", "Soft Flex U-Tube Heat Exchanger", "For a project in India",
     [("Material", "SA 240 Gr. 304; tubesheets SA 240 Gr. 304; tubes SA 213 TP 304"),
      ("Size", "Ø 1.8 mtr × 20.3 mtr L"),
      ("U-tubes", "30mm OD × 2mm thk."),
      ("Qty / Weight", "1 No. / 35 tons")],
     None, layout="showcase", fill=True, files=[IMG(33, 3), IMG(33, 2)], emphasis=True)

spec("Food Processing & Oleo Chemical", "Oleo Chemical", "Cladded Splitter Columns — Column 1", "Adani Wilmar Ltd, India",
     [("Material", "SA 516 Gr. 70 + SS 317L clad"),
      ("Size", "Ø 1.75 mtr (45+3mm thk) × 52 mtr L"),
      ("Qty / Weight", "1 No. / 150 tons")],
     None, layout="showcase", fill=True, files=[IMG(34, 1), IMG(35, 1)], panel_pos="tl")

spec("Food Processing & Oleo Chemical", "Oleo Chemical", "Cladded Splitter Columns — Column 2", "Adani Wilmar Ltd, India",
     [("Material", "SA 516 Gr.70 + SA 240 Gr.317L clad, SS 317L internals"),
      ("Size", "Ø 1.92 mtr × (50+3mm thk) × 55 mtr L"),
      ("Qty / Weight", "2 Nos. / 150 tons each")],
     None, layout="showcase", fill=True, files=[IMG(35, 2)], panel_pos="right")

spec("Food Processing & Oleo Chemical", "Oleo Chemical", "Cladded Columns with Trays", "PTSOI, Indonesia",
     [("Material", "SA 516 Gr. 70 + SS 317L"),
      ("Size", "Ø 2.15 mtr × 55 mtr L"),
      ("Qty / Weight", "1 No. / 200 MT")],
     36)

spec("Food Processing & Oleo Chemical", "Oleo Chemical", "Dephlegmator of 5-C-1 (5-CE-1)", "Adani Wilmar Ltd, India",
     [("Material", "SA 240 Gr. 317L & SS 317L (shell & tubes)"),
      ("Size", "Ø 3.750/4.100 mtr × 4.75 mtr L"),
      ("Qty / Weight", "1 No. / 28 tons")],
     37)

spec("Food Processing & Oleo Chemical", "Oleo Chemical", "Distillation Column (5-C-1)", "Adani Wilmar Ltd, India",
     [("Material", "SA 240 Gr. 316L/317L"),
      ("Size", "Ø 3.2/3.75 mtr × 30.148 mtr L"),
      ("Qty / Weight", "1 No. / 50 tons")],
     38)

spec("Food Processing & Oleo Chemical", "Oleo Chemical", "Distillation Column & Dephlegmator (5-C-2 & 5-CE-2)", "Adani Wilmar Ltd, India",
     [("Material", "SS 316L & 317L"),
      ("Size", "Ø 3.3/3.920 mtr × 26.78 mtr L"),
      ("Qty / Weight", "1 No. / 56 tons")],
     39)

spec("Food Processing & Oleo Chemical", "Food Processing", "First Stage Evaporator", "CHS Inc., USA",
     [("Material", "SA 240 Gr. 304/304L & IS 2062 Gr.B"),
      ("Size", "Ø 2.305/3.426 mtr × 18.39 mtr L"),
      ("Tubes", "OD 31.75 × 1.25 thk. — qty 2,196 Nos."),
      ("Qty / Weight", "1 No. / 56 tons")],
     None, layout="showcase", fill=True, files=[IMG(40, 2)])

spec("Food Processing & Oleo Chemical", "Food Processing", "Vacuum Condenser", "CHS Inc., USA",
     [("Material", "SA 516 Gr. 70"),
      ("Size", "Ø 2.272/3.372 mtr × 11.32 mtr L"),
      ("Tubes", "OD 19.05 × 1.05 thk. — qty 6,317 Nos."),
      ("Qty / Weight", "1 No. / 50 tons")],
     41)

spec("Food Processing & Oleo Chemical", "Food Processing", "Second Stage Evaporator — U Stamp", "CHS Inc., USA",
     [("Material", "SA 240 Gr. 304 / SA 516 Gr. 70"),
      ("Size", "Ø 0.930 mtr × 7.805 mtr L; tube 25.4 OD × 1.24mm thk. — qty 607 Nos."),
      ("Qty / Weight", "1 No. / 10 tons")],
     42)

spec("Food Processing & Oleo Chemical", "Food Processing", "Heat Exchangers (U Stamp) — 9 Vessel Program", "Budest 5, USA",
     [("Material", "SS 304/304L / SA 516 Gr. 70; tubesheets SS 304/304L; tubes SS 304 & 304L (19.05 & 25.04 OD)"),
      ("Sizes", "Ø 1.026×7.55m · Ø 2.272/3.4×11.36m · Ø 0.934/1.33×6.23m · Ø 1.06×7.55m · Ø 0.457×4.32m · Ø 0.9×7.43m · Ø 1.96×8.75m · Ø 0.323×3.622m · Ø 0.406×7.12m"),
      ("Total qty / weight", "9 Nos. / 120 MT")],
     43)

spec("Food Processing & Oleo Chemical", "Food Processing", "Hydrogenation Reactor — U Stamp", "CHS Inc., USA",
     [("Material", "SA 516 Gr. 70"),
      ("Size", "Ø 2.3 mtr × 7 mtr L"),
      ("Coil pipes", "Duplex SA 790 S32205 — 4″ NB × 40S × 330 mtr L"),
      ("Qty / Weight", "2 Nos. / 20 tons & 12 tons")],
     44)

# ---- 45. Divider: Fertilizer ------------------------------------------
divider("Fertilizer", "Fertilizer",
        "Prill towers, converters and heat exchangers for the world's largest fertilizer producers — including a 305 MT Prill Tower for Chambal Fertilizer & Chemicals Ltd.",
        bg_img=(51, 4), index_label="VI")

spec("Fertilizer", "Coromandel International Ltd", "Acid Cooler", "",
     [("Material", "Shell side SA 240 Type 304L; channel side SA 516 Gr 70"),
      ("Tubesheet", "SA 240 Type 304L"),
      ("Tubes", "ASTM A-249 TP316L with Hastelloy cathodic protection"),
      ("Size", "Ø 1346mm × 11,812mm overall length"),
      ("Qty / Weight", "1 No. / 24 MT")],
     46, layout="showcase")

spec("Fertilizer", "Fertilizer", "Tail Gas Stack", "Chambal Fertilizer & Chemicals Ltd., Rajasthan",
     [("Material", "SA 240 Gr 304"),
      ("Size", "Ø 1220mm × 56 mtr (dispatched in 2 pieces)"),
      ("Qty / Weight", "1 No. / 20 tons")],
     47)

spec("Fertilizer", "Fertilizer · Shop Fabrication", "Prill Tower — Fabrication: Skirt & Top Plenum", "Chambal Fertilizer & Chemicals Ltd., Rajasthan",
     [("Material", "SA 240 Gr. 304L"),
      ("Size", "Ø 5.3/7.1/8.9 × 68.17 mtr length"),
      ("Qty / Weight", "1 No. / 305.25 MT"),
      ("Stage", "Skirt & top plenum sections fabricated")],
     48, layout="showcase", fill=True, files=[IMG(48, 1), IMG(48, 2)])

spec("Fertilizer", "Fertilizer · Shop Fabrication", "Prill Tower — Fabrication: Hopper & Shell Rolling", "Chambal Fertilizer & Chemicals Ltd., Rajasthan",
     [("Material", "SA 240 Gr. 304L"),
      ("Size", "Ø 5.3/7.1/8.9 × 68.17 mtr length"),
      ("Qty / Weight", "1 No. / 305.25 MT"),
      ("Stages", "Hopper (polished to 0.4Ra finish) · Shell rolling")],
     49, layout="showcase", fill=True, files=[IMG(49, 1), IMG(50, 1)])

spec("Fertilizer", "Site Installation", "Prill Tower — Installation at Site", "Chambal Fertilizer & Chemicals Ltd., Rajasthan",
     [("Stage", "Tower sections delivered — top plenum lifted into the supporting structure")],
     51, layout="showcase", fill=True, files=[IMG(51, 1), IMG(51, 2)])

spec("Fertilizer", "Site Installation", "Prill Tower — Erection Complete", "Chambal Fertilizer & Chemicals Ltd., Rajasthan",
     [("Milestone", "Full tower erected and commissioned on site")],
     51, layout="showcase", fill=True, files=[IMG(51, 3), IMG(51, 4)])

spec("Fertilizer", "Fertilizer · Shop Fabrication", "Hot Interpass Heat Exchanger", "IFFCO, Paradip, Odisha",
     [("Material", "SA 240 Gr. 304 (shell & channel side); tubesheets SA 240 Gr. 304; tubes SA 213 TP 304"),
      ("Size", "Ø 6.03 mtr × 15 mtr L"),
      ("Tubes", "50.8mm OD × 2.1mm thk. × 6.1 mtr L — qty 2,808 Nos."),
      ("Qty / Weight", "1 No. / 85 tons")],
     None, layout="showcase", files=[IMG(52, 1), IMG(52, 2)])

spec("Fertilizer", "Fertilizer · Site Assembly", "Hot Interpass Heat Exchanger — Site Erection", "IFFCO, Paradip, Odisha",
     [("Transport", "3 pieces — (1st) Ø 6.9×6.1m, (2nd) Ø 5.6×3.85m, (3rd) Ø 5.6×3m; all large nozzles shipped loose")],
     None, layout="showcase", files=[IMG(53, 1)],
     milestone="Site Assembly — erected at IFFCO site")

spec("Fertilizer", "Fertilizer · Shop Fabrication", "Cold Interpass Heat Exchanger", "IFFCO, Paradip, Odisha",
     [("Material", "SA 240 Gr. 316L (shell & channel side); tubesheets & tubes SA 213 TP 316L"),
      ("Size", "Ø 4.5 mtr shell (Ø 6.9 mtr with bustle) × 16 mtr L"),
      ("Tubes", "50.8mm OD × 2.41mm thk. × 10.1 mtr L — qty 2,841 Nos."),
      ("Qty / Weight", "1 No. / 135 tons")],
     None, layout="showcase", files=[IMG(54, 1), IMG(54, 2)])

spec("Fertilizer", "Fertilizer · Site Assembly", "Cold Interpass Heat Exchanger — Site Erection", "IFFCO, Paradip, Odisha",
     [("Transport", "3 pieces — (1st) Ø 5.4×10.5m, (2nd & 3rd) Ø 5.4×2.5m, bustle Ø 6.9m ×2 dispatched in halves; large nozzles shipped loose")],
     None, layout="showcase", files=[IMG(55, 1)],
     milestone="Site Assembly — erected at IFFCO site")

spec("Fertilizer", "Fertilizer · Shop + Site Fabricated", "Converter", "IFFCO, Paradip, Odisha",
     [("Material", "SA 240 Gr. 304H"),
      ("Size", "Ø 12 mtr × 20 mtr L"),
      ("Qty / Weight", "1 No. / 330 tons")],
     [56, 57], layout="showcase", milestone="After Insulation at Site — insulated and erected at IFFCO site")

gallery("Fertilizer", "Client Recognition", "IFFCO Project-Specific Approval Letter", 58)

spec("Fertilizer", "Fertilizer", "Ducts", "Ma’aden (Saudi Arabia) — Phosphate 3 Project",
     [("Material", "SS 304, SS304L, SS304H, SS316L, IS2062 Gr B"),
      ("Size", "~2,700mm each"),
      ("Total qty / weight", "23 Nos. / 520 MT")],
     59, layout="showcase", fill=True)

spec("Fertilizer", "Fertilizer", "K-COT Converter — Regenerator Support Structure", "K-COT Converter (KBR Inc.), USA",
     [("Material", "SA 240 Gr. 304H"),
      ("Size", "3450×17250×100mm ×4 pcs & Ø 1975×100mm ×4 Nos."),
      ("Qty", "8 Nos. (7 tons each)"),
      ("Weight", "30 MT")],
     60, layout="showcase")

spec("Fertilizer", "Fertilizer", "Partition Plates for Ammonia Converter Baskets", "KBR Inc., USA",
     [("Material", "SA 240 Gr. 304"),
      ("Size", "Up to 3 mtr dia."),
      ("Qty / Weight", "32 Nos. / 10 MT")],
     61, layout="showcase", fill=True)

spec("Fertilizer", "Fertilizer", "KBR Distributor Grids — Ammonia Basket Converter Internals", "Talcher Fertilizers Ltd., Odisha, India (KBR Inc.)",
     [("Material", "SA 240 Gr. 304"),
      ("Size", "2.6 mtr × 9.35 mtr L"),
      ("Qty / Weight", "8 Nos. / 65 tons")],
     62, layout="showcase")

spec("Fertilizer", "Sulphuric Acid Plant", "ZECOR Z — Piping Spools & Pipe Fittings (Shop + Site)", "Hindalco Industries Ltd, India",
     [("Material", "ZECOR Z"),
      ("Size", "2″ NB to 30″ NB"),
      ("Qty", "7,500 inch-dia & 5,000 inch-mtr"),
      ("Weight", "30 tons")],
     63, layout="showcase")

# ---- 64. Divider: Water & Desalination ------------------------------------
divider("Water & Desalination", "Water &<br><span>Desalination</span>",
        "Evaporators, ZLD systems and heat exchangers for desalination and zero-liquid-discharge plants worldwide.",
        bg_img=65, index_label="VII")

spec("Water & Desalination", "Water & Desalination", "Evaporator (2×3000 T/D, 5 Effects)", "Baten Suralaya Power Station, Indonesia",
     [("Material", "SS 316L with Titanium Gr.2 tubes; Duplex UNS S32205 with Titanium Gr.2 tubes"),
      ("Size", "Ø 4.4 mtr × 30 mtr L"),
      ("Qty / Weight", "2 Nos. / 125 tons each")],
     65)

spec("Water & Desalination", "Zero Liquid Discharge", "Dual Media Filter (Rubber Lined)", "Saudi Aramco, Zuluf Water Treatment Plant",
     [("Material", "SA 516 Gr. 70N"),
      ("Size", "Ø 3000mm × 13,000mm TL-TL"),
      ("Total qty / weight", "15 Nos. / 418 MT")],
     66)

spec("Water & Desalination", "Zero Liquid Discharge", "Flash / Distillate Tank & Hotwell for FCHX + Vapour Condenser", "Qatar Fertilizer Company (QAFCO)",
     [("Tank material", "SA 240 UNS S32205 & SS 316L"),
      ("Tank size", "2000mm OD × 7350mm L; 750mm OD × 2500mm L; 14″ SCH 10s × 1375mm L — 3 Nos. each"),
      ("Condenser material", "SA 240 UNS S32205 (shell) & SA 240 UNS S32750 (channel)"),
      ("Condenser tubes", "SB 338 Gr.2, 25.4mm OD × 0.72mm — qty 212 Nos."),
      ("Condenser size / qty", "640mm OD × 3172mm to tubesheet face / 1 No.")],
     67, layout="showcase")

spec("Water & Desalination", "Zero Liquid Discharge", "Forced Circulation Heat Exchanger (FCHX)", "Qatar Fertilizer Company (QAFCO)",
     [("Material", "SA 240 UNS S32205 (shell & channel side)"),
      ("Tubes", "SB 338 Gr.2, 31.8mm OD × 0.711mm — qty 306 Nos."),
      ("Size", "940mm OD × 3172mm to tubesheet face"),
      ("Qty", "3 Nos. each")],
     68)

spec("Water & Desalination", "Zero Liquid Discharge", "Heat Exchanger", "Grasim Industries Ltd, Nagda, MP, India",
     [("Material", "SA 516 Gr.70 (shell) & SA 240 UNS S31254 (tube); tubesheets SA 516 Gr.70 + Ti.Gr.1 explosion bonded; tubes Titanium Gr.2 (welded)"),
      ("Size", "Ø 1.85/2.1 mtr × 8mm thk × 14 mtr L"),
      ("Tubes", "38.1mm OD × 0.711mm thk × 10.7 mtr L — qty 1,100 Nos."),
      ("Qty / Weight", "1 No. / 25 tons")],
     69, layout="showcase", fill=True)

spec("Water & Desalination", "Zero Liquid Discharge", "Heat Exchanger — Twin Units", "Hindustan Zinc Ltd & Hindalco Industries Ltd, India",
     [("Material", "SA 516 Gr.70 (shell) & SA 240 UNS S31254 (tube); tubesheets SA 516 Gr.70 + Ti.Gr.1 explosion bonded; tubes Titanium Gr.2 (welded)"),
      ("Size A", "Ø 1.9 mtr × 10mm thk × 11.78 mtr L"),
      ("Size B", "Ø 1.8 mtr × 10mm thk × 11.2 mtr L"),
      ("Tubes", "31.75mm OD × 0.711mm thk × 7.5m (qty 1,350) and ×8m (qty 1,600) Nos."),
      ("Qty / Weight", "1 No. each — A) 18 tons  B) 20 tons")],
     70, layout="showcase", fill=True)

spec("Water & Desalination", "Zero Liquid Discharge", "Crystallizer", "Hindustan Zinc Ltd, Hindalco Industries Ltd, Grasim Industries Ltd (Nagda, MP), India",
     [("Material", "SA 240 Gr. 31254 (6% Moly)"),
      ("Size / Qty / Weight", "Ø 3.66 mtr × 9.75 mtr L / 1 No. / 12 tons")],
     None, layout="showcase", fill=True, files=[IMG(71, 1)])

spec("Water & Desalination", "Zero Liquid Discharge", "Deaerator", "Hindustan Zinc Ltd, Hindalco Industries Ltd, Grasim Industries Ltd (Nagda, MP), India",
     [("Material", "SA 240 Gr. 31254 (6% Moly)"),
      ("Size / Qty / Weight", "Ø 0.6 mtr × 4.2 mtr L / 2 Nos. / 2 tons")],
     None, layout="showcase", fill=True, files=[IMG(71, 2)])

spec("Water & Desalination", "Zero Liquid Discharge", "Brine Concentrator", "Grasim Industries Ltd, Nagda, MP, India",
     [("Material", "SA 240 Gr. 316L (shell & tube side); tubesheets SA 240 Gr. 316L; tubes SA 179 UNS S31803 (welded)"),
      ("Size", "Ø 1.85/2.1 mtr × 8mm thk × 24 mtr L"),
      ("Tubes", "50.8mm OD × 1mm thk × 9.4 mtr L — qty 616 Nos."),
      ("Qty / Weight", "1 No. / 25 tons")],
     72)

spec("Water & Desalination", "Water & Desalination", "Piping Spools — PDO", "Petroleum Development Oman",
     [("Material", "SS 316L & Super Duplex 32750"),
      ("Size", "1″ to 6″ × 12 mtr length"),
      ("Qty", "12,500 inch-dia.")],
     73, layout="showcase")

spec("Water & Desalination", "Water & Desalination", "Piping Spools — KOC", "Kuwait Oil Company",
     [("Material", "Duplex 32205 / Super Duplex 32750"),
      ("Size", "2″ to 10″ × 12 mtr length")],
     None, layout="showcase", fill=True, files=[IMG(74, 1), IMG(74, 2)])

spec("Water & Desalination", "Water & Desalination", "Piping Spools — KOC — Fabrication", "Kuwait Oil Company",
     [("Qty", "40,000 inch-dia.")],
     None, layout="showcase", fill=True, files=[IMG(74, 3)])

spec("Water & Desalination", "Water & Desalination", "Pre-Fabricated Piping Spools", "Pertamina, Indonesia",
     [("Material", "SS 316L / UNS S32750 / CS"),
      ("Size", "2″ to 20″ NB"),
      ("Qty", "80,000 inch-dia.")],
     75)

spec("Water & Desalination", "Water Treatment", "Skid Mounted Packages", "H2 Green Steel, Sweden",
     [("Scope", "Procurement + fabrication of piping spools + structure + assembly + E&I procurement & installation + heat tracing + insulation + FAT"),
      ("Material", "SA 106 Gr.B (rubber lining) & SA 312 TP 316L"),
      ("Size", "6.6m L × 4.1m W × 3.75m H"),
      ("Qty / Wt.", "10 Nos. / 110 tons")],
     77, layout="showcase", fill=True, files=[IMG(77, 1), IMG(77, 2)])

spec("Water & Desalination", "Water Treatment", "ZLD Softeners (Rubber Lined), PED + CE Marking", "H2 Green Steel, Sweden",
     [("Material", "SA 516 Gr. 70N"),
      ("Size", "Ø 3000mm × 3,353mm TL-TL"),
      ("Total qty / weight", "3 Nos. / 25 MT")],
     78, layout="showcase")

spec("Water & Desalination", "Water Treatment", "Rapid Mix & Flocculation Tank", "H2 Green Steel, Sweden",
     [("Material", "SA 240 Gr. 304"),
      ("Size", "3,848mm L × 2,311mm W × 3,912mm H"),
      ("Total qty / weight", "2 Nos. / 5 MT")],
     79)

spec("Water & Desalination", "Water Treatment", "Multimedia Filter (Internal Coating)", "H2 Green Steel, Sweden",
     [("Material", "SA 516 Gr. 70N"),
      ("Size", "Ø 3000mm × 10,102mm TL-TL"),
      ("Total qty / weight", "7 Nos. / 108 MT")],
     80, layout="showcase")

spec("Water & Desalination", "Water Treatment", "Cartridge Filter", "Saudi Aramco, Zuluf Water Treatment Plant",
     [("Material", "SA 516 Gr 70; tubesheet Super Duplex S32750 (30mm thk.)"),
      ("Size", "Ø 1460mm ID × 1750mm TS-TS"),
      ("Total qty / weight", "12 Nos. / 3.8 MT each")],
     81, layout="showcase")

# ---- 96. Electrical & Instrumentation ---------------------------------------
prose("Electrical & Instrumentation", "In-House Team", "Electrical & Instrumentation Capability",
      ["We have an in-house Electrical & Instrumentation team comprising technicians and engineers for supervision, "
       "capable of carrying out FAT complying with project and client specifications for skid mounted packages."],
      side_title="Capabilities",
      side_items=[
        "Preparation of cable tray routing drawings",
        "Knowledge of instrument loop drawings",
        "Knowledge of instrument hook-up & installation drawings",
        "Full continuity and mega testing of all instruments and earthing cabling",
        "Panel testing / power up",
        "Preparation of datasheets — instruments / control valves / actuated valves / PSV / PRV from customer process data",
        "Measurement of response of electronic transmitters",
        "Check of control valve operation by injecting 4-20mA signal to valve positioners and recording response",
        "Check on failure action of control valves",
        "Piping and instrument tubing air leak test of the assembled package",
        "Preparation of as-built drawings",
        "Preparation of MTO of instrument hookup drawing from customer's hookup drawing",
        "Procurement of E&I related items",
        "Earthing drawing up to skid battery limit",
        "Instrument cable schedule up to skid battery limit",
        "Cable glands specifications and BOM",
        "Junction box specifications",
        "BOM of electrical accessories",
        "Instrument cable specifications",
      ])

# ---- 98. Divider: Health & Safety ------------------------------------------
divider("Health, Safety & Environment", "Health<br>&<br><span>Safety</span>",
        "ISO 14001:2015 & ISO 45001:2018 certified — occupational health, safety and environment integrated into every operation.",
        bg_img=100, index_label="VIII")

prose("Health, Safety & Environment", "HSE Policy", "Health, Safety & Environment Policy",
      ["Vitech Heavy Equipments Pvt. Ltd. (VHEPL) is in the business of design and manufacturing of pressure vessels, "
       "heat exchangers, storage tanks, skid mounted packages, cladded columns & process equipment as per international "
       "standards and customer specifications.",
       "We are committed to maintaining occupational health and safety of our employees and to minimize or eliminate "
       "adverse environmental impact due to our operations. Management and employees are committed to continual "
       "improvement of OHSE performance, integrated with VHEPL's business operations."],
      side_title="Use of Personal Protective Equipment (PPE)",
      side_items=["During cutting", "During grinding", "During welding"],
      chips=[{"t": "ISO 14001:2015 & ISO 45001:2018 Certified", "on": True}])

gallery("Health, Safety & Environment", "Toolbox Talks", "Safety Instructions — Weekly Toolbox Meetings", 100,
        caption="Safety & other instructions are briefed to all workers during toolbox meetings held every week.")

# ---- 101-102. Packing / Dispatch -------------------------------------------
spec("Packing, Dispatch & Ongoing Jobs", "Packing, Preservation & Dispatch", "Tarpaulin Wrapping & Nitrogen Purging", "",
     [("Tarpaulin wrapping", "Loading & lashing on trailer"),
      ("Nitrogen purging", "Supply of cylinder with its accessories")],
     101, layout="showcase")

spec("Packing, Dispatch & Ongoing Jobs", "ODC Dispatch", "SS304 Distillation Column — Single-Piece Transport", "",
     [("Description", "46.5 mtr long distillation column, transported in a single piece"),
      ("Weight", "110 tons")],
     102)

# ---- 103-111. Ongoing jobs --------------------------------------------------
divider("Packing, Dispatch & Ongoing Jobs", "Ongoing<br><span>Jobs</span>",
        "A snapshot of live projects currently in fabrication across our facilities.", index_label="IX")

data_table("Packing, Dispatch & Ongoing Jobs", "Ongoing Jobs", "Ongoing Jobs — Overview",
      [[
        ["Project", "Job Description", "Material", "Weight (kg)"],
        ["SIGBOG2", "Qualistock Ø 1600mm × 8477mm TL", "Shell: SA-240 304; Coil: SA-312 TP 304L", "4,800"],
        ["AWLOLEK", "FA Precut Column Ø 3850/3550/3350mm × 46893mm TL", "Shell: 316L 2.5% Mol", "63,500"],
        ["AWLOLEK", "FA Post Distillation Column Ø 3750/3500mm × 24215mm TL × 10 thk", "Shell: 316L 2.5% Mol", "59,280"],
        ["AWLOLEK", "Dephlegmator FA Precut Column Ø 3500mm × 4996mm TL, 2,053 tubes", "Shell: 317L; tubes SA-249 TP 317L; tubesheet SA-249 TP 317L", "28,100"],
        ["AWLOLEK", "Dephlegmator FA Post Distillation Column Ø 3300mm × 5127mm TL, 1,824 tubes", "Shell: 316L 2.5% Mol; tubes SA-249 TP 317L; tubesheet SA-240 Type 317L", "18,000"],
        ["HIL – Birla Copper, Dahej", "Converter & Internal Heat Exchanger Ø 15300mm × 28122mm OVH", "SS 304H, SS 321H", "720,000"],
        ["Rio Grande LNG (Trains 4 & 5)", "Multimedia Filter A w/ internals (U Stamp) Ø 2439mm × 3252mm overall length", "SA 516 GR 70", "8,000"],
      ]])

data_table("Packing, Dispatch & Ongoing Jobs", "Ongoing Jobs — Water Treatment", "Ongoing Jobs — Water Treatment",
      [
        [["Heat Exchanger", ""],
         ["Material", "SA 240 UNS S31254"],
         ["Tubesheet", "SA 516 Gr.70 + Titanium Gr.1 explosion cladded"],
         ["Tubes", "Titanium Gr.2, Ø 38.1×0.71mm avg. thk × 11,500mm L — qty 500 Nos."],
         ["Size", "Ø 1250/1500mm × 11,500mm TS-TS"],
         ["Total qty / weight", "1 No. / 17.5 MT"]],
        [["Crystallizer", ""],
         ["Material", "SA 240 UNS S31254"],
         ["Size", "Ø 2100mm × 7,130mm TL-TL"],
         ["Total qty / weight", "1 No. / 7 MT"]],
      ],
      sub="McCain Foods (India) Pvt Ltd, WWTP L4 Expansion Plant")

data_table("Packing, Dispatch & Ongoing Jobs", "Ongoing Jobs — Oil & Gas", "Ongoing Jobs — Oil & Gas (Separators, Dehydrator & Degasser)",
      [
        [["LP Separator", ""], ["Material", "SA 516 GR70N (epoxy lining)"], ["Size", "Ø 2727mm × 12292mm TS-TS"], ["Total qty / weight", "4 Nos. / 21.2 MT"]],
        [["HP Separator", ""], ["Material", "SA 516 GR70N (SDSS cladded)"], ["Size", "Ø 2721mm × 12292mm TL-TL"], ["Total qty / weight", "4 Nos. / 20.4 MT"]],
        [["Dehydrator", ""], ["Material", "SA 516 GR70N (epoxy lining)"], ["Size", "Ø 3658mm × 18288mm TS-TS"], ["Total qty / weight", "4 Nos. / 46.82 MT"]],
        [["Degasser", ""], ["Material", "SA 516 GR70N (epoxy lining)"], ["Size", "Ø 2114mm × 9876mm TL-TL"], ["Total qty / weight", "4 Nos. / 10.95 MT"]],
      ],
      sub="ONGC, Uran", columns=2, dense=True)

data_table("Packing, Dispatch & Ongoing Jobs", "Ongoing Jobs — Lithium", "Ongoing Jobs — ZLD Duct Pipes & Vent Condenser",
      [
        [["ZLD Recirculation Duct Pipe", ""], ["Material", "ASTM A240 S32750 (Super Duplex)"], ["Size", "Ø 70 inches"], ["Total qty / weight", "6 Nos. / 75 MT"]],
        [["ZLD Vapor Duct Pipe", ""], ["Material", "ASTM A240 S32205 (Duplex)"], ["Size", "Ø 56 inches"], ["Total qty / weight", "3 Nos. / 65 MT"]],
        [["MgSO4 Stage 4 Vent Condenser", ""],
         ["Material", "1.5″ (40mm thick) foam glass / cellular glass insulation, min. 98kg/m³ density"],
         ["Size", "Ø 2951mm × 3252mm overall length"],
         ["Total qty", "1 No."]],
      ],
      sub="Thacker Pass P-30090 LNC Project", columns=2, dense=True)

# ---- 112. Exhibitions (split across two full-bleed slides; slide114_img02 is
#           a corrupt all-black frame, intentionally dropped) ------------------
photo_showcase("Exhibitions & Approvals", "Industry Presence", "Vitech at Exhibitions — IEW · FAI · GRPC",
    [(IMG(112, 2), "IEW 2026, Goa"),
     (IMG(112, 1), "FAI 2025, Delhi"),
     (IMG(112, 3), "GRPC 2025, Delhi")])

photo_showcase("Exhibitions & Approvals", "Industry Presence", "Vitech at Exhibitions — WEFTEC · CHEMTECH",
    [(IMG(112, 5), "WEFTEC 2025, Chicago"),
     (IMG(112, 4), "CHEMTECH 2026, Mumbai")], fill=True)

# ---- 115. Divider: Appreciation Letters --------------------------------------
divider("Client Appreciation", "Appreciation<br><span>Letters</span>",
        "A selection of recognitions received from clients across our project history.", index_label="X")

gallery("Client Appreciation", "Client Recognition", "Client Appreciation Letters I", [116, 117, 118, 119])
gallery("Client Appreciation", "Client Recognition", "Client Appreciation Letters II", [120, 121, 122, 123])

# ---- 124. Divider: Certifications --------------------------------------------
divider("Certifications", "Certifications",
        "ISO, ASME, Engineers India Limited, IBR, PESO and PDIL — the qualifications behind every job we ship.",
        index_label="XI")

gallery("Certifications", "ISO", "ISO — QMS, EMS & OHSAS Certifications", [125, 126],
        caption="ISO 9001:2015 QMS (VEPL, Rabale & VHEPL, Shahapur) · ISO 14001:2015 EMS (VHEPL, Shahapur) · ISO 45001:2018 OHSAS (VHEPL, Shahapur)")

gallery("Certifications", "ASME & Engineers India Limited", "ASME & EIL Certifications", [127, 128, 129, 130],
        caption="ASME U/U2/R Stamp (VHEPL, Shahapur) · EIL — Clad Pressure Vessels & Columns · EIL — Pressure Vessel (CS up to 75mm & SS 304/316 up to 18mm) · EIL — Pre-Fabricated Piping Spools")

gallery("Certifications", "IBR / PESO / PDIL", "IBR, PESO & PDIL Certifications", [131, 132, 133],
        caption="IBR — Pipe fabrication, pressure vessel & heat exchanger Class 1 (pressure up to 125 kg/cm²)")

# ---- 134-137. Sustainability --------------------------------------------------
water_slide("Sustainability & CSR", "Sustainable Stress-Free Environment",
            "Rainwater Harvesting & Wastewater Recycling")

photo_showcase("Sustainability & CSR", "Sustainable Stress-Free Environment", "Vegetable Farm & Harvest",
    [(IMG(136, 1), None), (IMG(136, 2), None)], fill=True)

photo_showcase("Sustainability & CSR", "Sustainable Stress-Free Environment", "Vegetable Farm & Orchards",
    [(IMG(136, 3), None), (IMG(136, 4), None), (IMG(137, 1), None)], fill=True,
    sub="3,500 fruit-bearing orchard plantations line the periphery of the plot, drip-irrigated using our recycling plant.")

# ---- 138. CSR -------------------------------------------------------------
gallery("Sustainability & CSR", "Corporate Social Responsibility", "Corporate Social Responsibility (CSR)", 138,
        caption="School bags, water purifiers, and solar panels with inverters distributed to Gramin schools.")

# ---- 139. Thank you --------------------------------------------------------
closer("Cover", 'THANK <span>YOU</span>',
       ["+91-9372766457 / 58 / 60", "sales@vitechgroupindia.com", "www.vitechgroupindia.com"],
       139,
       locations=[
         ("Vitech Heavy Equipments Pvt. Ltd.", "Shahapur, Maharashtra"),
         ("Vitech Equipments Pvt. Ltd.", "Rabale, Navi Mumbai"),
         ("Vitech Fabricators Pvt. Ltd.", "Rabale, Navi Mumbai"),
       ])

# ===========================================================================
# Assemble section index for jump-menu (ordered, deduplicated by first appearance)
# ===========================================================================
seen = []
section_first = {}
for s in SLIDES:
    if s["section"] not in section_first:
        section_first[s["section"]] = s["id"]
        seen.append(s["section"])

section_counts = {}
for s in SLIDES:
    section_counts[s["section"]] = section_counts.get(s["section"], 0) + 1

section_cards = "".join(
    '<div class="section-card" data-index="{idx}"><div class="n">{n:02d}</div><div class="t">{t}</div><div class="c">{c} slide{plural}</div></div>'.format(
        idx=section_first[sec] - 1, n=i + 1, t=esc(sec), c=section_counts[sec], plural="s" if section_counts[sec] != 1 else ""
    )
    for i, sec in enumerate(seen) if sec != "Cover"
)

slides_html = "\n".join(s["html"] for s in SLIDES)

PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Vitech Group of Companies — Corporate Presentation</title>
<meta name="description" content="Vitech Group of Companies — heavy engineering & fabrication capability presentation.">
<link rel="icon" href="assets/images/brand/vitech-mark.png">
<link rel="stylesheet" href="assets/css/styles.css">
</head>
<body>
<div id="progress"></div>
<div id="deck">
{slides}
</div>

<div id="chrome">
  <div class="brand-mark"><img src="assets/images/brand/vitech-mark.png" alt=""><span>Vitech Group of Companies</span></div>
  <div class="slide-counter"><span id="counter-section"></span><b id="counter-now">1</b> / <span id="counter-total"></span></div>
  <button class="menu-toggle" id="menu-toggle" aria-label="Jump to section">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
  </button>
  <div class="nav-arrows">
    <button class="nav-btn" id="btn-prev" aria-label="Previous slide"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg></button>
    <button class="nav-btn" id="btn-next" aria-label="Next slide"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg></button>
  </div>
  <div class="hint">Use ← → or space to navigate · click edges · swipe on touch</div>
</div>

<div id="sections-panel">
  <button class="panel-close" id="panel-close" aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
  <div class="sections-grid">
    {sections}
  </div>
</div>

<div id="lightbox">
  <button class="lb-close" aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
  <img src="" alt="">
</div>

<script src="assets/js/main.js"></script>
</body>
</html>
'''.format(slides=slides_html, sections=section_cards)

with open(os.path.join(ROOT, "index.html"), "w") as f:
    f.write(PAGE)

print("Built index.html with", len(SLIDES), "slides")
ids = [s["id"] for s in SLIDES]
expected = list(range(1, len(SLIDES) + 1))
if ids != expected:
    missing = sorted(set(expected) - set(ids))
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    raise SystemExit("Slide id sequence is broken. Missing: {0} Duplicates: {1}".format(missing, dupes))
print("Slide ids sequential 1..{0} — OK".format(len(SLIDES)))
