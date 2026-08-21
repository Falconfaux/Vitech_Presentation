(function () {
  "use strict";

  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var total = slides.length;
  var current = 0;
  var deck = document.getElementById("deck");
  var stage = document.querySelector(".stage");
  var progress = document.getElementById("progress");
  var counterNow = document.getElementById("counter-now");
  var counterTotal = document.getElementById("counter-total");
  var sectionsPanel = document.getElementById("sections-panel");
  var lightbox = document.getElementById("lightbox");
  var lightboxImg = lightbox ? lightbox.querySelector("img") : null;
  var counterSection = document.getElementById("counter-section");

  counterTotal.textContent = total;

  // iOS Safari has a much lower renderer/GPU-memory ceiling than desktop and
  // crashes ("A problem repeatedly occurred") when a slide switch repaints too
  // many large composited layers at once — chiefly backdrop-filter chrome over
  // the scaled stage, kenburns-animated full-screen backgrounds, and duplicate
  // blurred media. Tagging <html> lets CSS strip exactly those effects on iOS
  // only, leaving every other device's approved design untouched. Covers iPhone/
  // iPod/iPad plus iPadOS 13+, which reports a desktop (Macintosh) UA with touch.
  var ua = navigator.userAgent || "";
  var isIOS = /iPhone|iPod|iPad/.test(ua) ||
              (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  if (isIOS) document.documentElement.classList.add("ios");

  function clamp(n) { return Math.max(0, Math.min(total - 1, n)); }

  // Sliding-window media management. iOS Safari kills a tab that exceeds its
  // per-tab memory ceiling, and decoded image/video memory is far larger than
  // file size. So we keep the real src only on slides near the current one and
  // blank the rest — the original URL always lives on data-src so media can be
  // re-loaded on return. LOAD_RADIUS is the window we load; UNLOAD_RADIUS is a
  // wider band we keep loaded, so a boundary swipe back-and-forth doesn't thrash.
  var LOAD_AHEAD = 2, LOAD_BACK = 1;
  var UNLOAD_AHEAD = 3, UNLOAD_BACK = 2;

  function loadMediaEl(el) {
    // On iOS the blurred fill copies are hidden (CSS) and only add a second
    // full-size decode/video decoder, so never load them there.
    if (isIOS && el.classList.contains("media-blur")) return;
    var src = el.getAttribute("data-src");
    if (!src || el.getAttribute("src") === src) return; // already loaded
    if (el.tagName === "VIDEO") {
      el.src = src;
      el.load();
    } else {
      el.decoding = "async";
      el.src = src;
    }
  }

  function unloadMediaEl(el) {
    if (!el.getAttribute("data-src")) return; // nothing to restore from → leave it
    if (!el.getAttribute("src")) return;      // already blanked
    if (el.tagName === "VIDEO") {
      try { el.pause(); } catch (e) {}
      el.removeAttribute("src");
      el.load(); // flush buffered/decoded frames
    } else {
      el.removeAttribute("src");
      el.removeAttribute("srcset");
    }
  }

  function eachMedia(slide, fn) {
    slide.querySelectorAll("img[data-src], video[data-src]").forEach(fn);
  }

  function lazyLoadNear(index) {
    for (var d = -LOAD_BACK; d <= LOAD_AHEAD; d++) {
      var s = slides[index + d];
      if (s) eachMedia(s, loadMediaEl);
    }
  }

  // Render window. iOS Safari enforces a hard GPU backing-store / memory ceiling
  // (far lower than desktop) and allocates buffers for every slide's background
  // image, scrim and backdrop-filter / blur chrome — even hidden ones. Keeping
  // all ~130 slides renderable overruns it and WebKit kills the tab on any nav.
  // We give the `render` class only to slides in a tiny window around the current
  // one; CSS then applies `content-visibility: hidden` to the rest so the engine
  // fully skips them (no layout, paint, compositing or filter buffers). Radius 1
  // keeps the outgoing slide renderable so the cross-fade still works.
  var RENDER_RADIUS = 1;
  function setRenderWindow(index) {
    slides.forEach(function (s, i) {
      s.classList.toggle("render", Math.abs(i - index) <= RENDER_RADIUS);
    });
  }

  // Release media on slides outside the keep-window so decoded bitmaps and video
  // buffers can be reclaimed. Slide 0 (the cover) is never unloaded.
  function unloadFar(index) {
    slides.forEach(function (s, i) {
      if (i === 0) return;
      if (i >= index - UNLOAD_BACK && i <= index + UNLOAD_AHEAD) return;
      eachMedia(s, unloadMediaEl);
    });
  }

  // play the active slide's video(s) from the start; pause the immediate
  // neighbours' (anything further out is unloaded by unloadFar).
  function syncVideos(index) {
    for (var d = -UNLOAD_BACK; d <= UNLOAD_AHEAD; d++) {
      var s = slides[index + d];
      if (!s) continue;
      var active = (index + d === index);
      s.querySelectorAll("video").forEach(function (v) {
        // on iOS the blurred duplicate video is hidden and never loaded — don't
        // spin up a second decoder for it.
        if (isIOS && v.classList.contains("media-blur")) return;
        if (active) {
          try { v.currentTime = 0; } catch (e) {}
          var p = v.play();
          if (p && p.catch) p.catch(function () {});
        } else {
          v.pause();
        }
      });
    }
  }

  function goTo(index, pushHash) {
    index = clamp(index);
    var prevIndex = current;
    if (index < prevIndex) deck.classList.add("dir-back");
    else if (index > prevIndex) deck.classList.remove("dir-back");
    slides.forEach(function (s, i) {
      s.classList.remove("active", "prev");
      if (i === index) s.classList.add("active");
      else if (i === prevIndex && prevIndex !== index) s.classList.add("prev");
    });
    current = index;
    document.body.classList.toggle("on-cover", index === 0);
    counterNow.textContent = index + 1;
    progress.style.width = ((index + 1) / total * 100) + "%";
    if (counterSection) counterSection.textContent = slides[index].getAttribute("data-section") || "";
    setRenderWindow(index);
    lazyLoadNear(index);
    unloadFar(index);
    syncVideos(index);
    if (pushHash !== false) {
      history.replaceState(null, "", "#" + (index + 1));
    }
    slides[index].querySelector(".slide-inner").scrollTop = 0;
  }

  function next() { goTo(current + 1); }
  function prev() { goTo(current - 1); }

  // retire the navigation hint once the viewer starts moving through the deck
  var hintEl = document.querySelector(".hint");
  var _goTo = goTo;
  goTo = function (index, pushHash) {
    if (hintEl && index > 0) hintEl.classList.add("hide");
    _goTo(index, pushHash);
  };

  document.addEventListener("keydown", function (e) {
    if (lightbox.classList.contains("open")) {
      if (e.key === "Escape") closeLightbox();
      return;
    }
    if (sectionsPanel.classList.contains("open")) {
      if (e.key === "Escape") toggleSections(false);
      return;
    }
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") { next(); e.preventDefault(); }
    else if (e.key === "ArrowLeft" || e.key === "PageUp") { prev(); e.preventDefault(); }
    else if (e.key === "Home") goTo(0);
    else if (e.key === "End") goTo(total - 1);
  });

  // touch swipe
  var touchX = null;
  deck.addEventListener("touchstart", function (e) { touchX = e.touches[0].clientX; }, { passive: true });
  deck.addEventListener("touchend", function (e) {
    if (touchX === null) return;
    var dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 50) { dx < 0 ? next() : prev(); }
    touchX = null;
  }, { passive: true });

  // click zones (left third / right third of a slide advances)
  deck.addEventListener("click", function (e) {
    if (e.target.closest("img, a, button, .gallery-grid, .spec-media-grid")) return;
    var w = window.innerWidth;
    if (e.clientX < w * 0.14) prev();
    else if (e.clientX > w * 0.86) next();
  });

  // section jump menu
  var menuToggle = document.getElementById("menu-toggle");
  var panelClose = document.getElementById("panel-close");
  function toggleSections(force) {
    var open = typeof force === "boolean" ? force : !sectionsPanel.classList.contains("open");
    sectionsPanel.classList.toggle("open", open);
  }
  menuToggle.addEventListener("click", function () { toggleSections(); });
  panelClose.addEventListener("click", function () { toggleSections(false); });

  // prev/next corner arrows
  var btnPrev = document.getElementById("btn-prev");
  var btnNext = document.getElementById("btn-next");
  if (btnPrev) btnPrev.addEventListener("click", function () { prev(); });
  if (btnNext) btnNext.addEventListener("click", function () { next(); });
  sectionsPanel.addEventListener("click", function (e) {
    if (e.target === sectionsPanel) toggleSections(false);
  });
  document.querySelectorAll(".section-card").forEach(function (card) {
    card.addEventListener("click", function () {
      var idx = parseInt(card.getAttribute("data-index"), 10);
      goTo(idx);
      toggleSections(false);
    });
  });

  // lightbox
  function openLightbox(src) {
    lightboxImg.src = src;
    lightbox.classList.add("open");
  }
  function closeLightbox() {
    lightbox.classList.remove("open");
    lightboxImg.src = "";
  }
  document.querySelectorAll(".spec-media-grid img, .spec-hero img, .gallery-grid img, .visual-frame img, .site-plan-map img").forEach(function (img) {
    img.addEventListener("click", function () {
      openLightbox(img.getAttribute("data-src") || img.src);
    });
  });
  // industry tiles (slides 4 & 5): the photo sits behind a scrim + label, so
  // wire the click on the whole tile and enlarge its background image. Stop
  // propagation so the deck's edge click-to-advance doesn't also fire.
  document.querySelectorAll(".industry-tile.has-photo").forEach(function (tile) {
    var bg = tile.querySelector(".industry-tile-bg");
    if (!bg) return;
    tile.style.cursor = "zoom-in";
    tile.addEventListener("click", function (e) {
      e.stopPropagation();
      openLightbox(bg.getAttribute("data-src") || bg.src);
    });
  });
  lightbox.addEventListener("click", function (e) {
    if (e.target === lightbox || e.target.closest(".lb-close")) closeLightbox();
  });

  // animated stat counters
  var countersObserved = new WeakSet();
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        var el = entry.target;
        if (countersObserved.has(el)) return;
        countersObserved.add(el);
        var target = parseFloat(el.getAttribute("data-count"));
        var suffix = el.getAttribute("data-suffix") || "";
        var dur = 1400, start = null;
        function step(ts) {
          if (!start) start = ts;
          var p = Math.min(1, (ts - start) / dur);
          var eased = 1 - Math.pow(1 - p, 3);
          el.textContent = Math.round(target * eased) + suffix;
          if (p < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      }
    });
  }, { threshold: 0.4 });
  document.querySelectorAll("[data-count]").forEach(function (el) { io.observe(el); });

  // ---------------------------------------------------------------------
  // Auto-fit: shrink vertical rhythm (via --fit custom property) on any
  // slide whose .slide-inner content overflows its box, so nobody has to
  // scroll. Every .slide is always 100% of the deck's box regardless of
  // .active state, so this runs once for all slides at load, then again
  // on resize — not on navigation, since a slide's fit doesn't change
  // between activations.
  // ---------------------------------------------------------------------
  var FIT_STEP = 0.04;
  var FIT_FLOOR = 0.56;
  var FIT_TOLERANCE = 2; // px

  function fitSlide(inner) {
    inner.style.setProperty("--fit", 1);
    var overflow = inner.scrollHeight - inner.clientHeight;
    if (overflow <= FIT_TOLERANCE) return;

    var fit = 1;
    while (overflow > FIT_TOLERANCE && fit > FIT_FLOOR) {
      fit = Math.max(FIT_FLOOR, fit - FIT_STEP);
      inner.style.setProperty("--fit", fit.toFixed(2));
      overflow = inner.scrollHeight - inner.clientHeight;
    }

    if (overflow > FIT_TOLERANCE) {
      var slide = inner.closest(".slide");
      console.warn(
        "[fit] slide " + (slide ? slide.id : "?") +
        " still overflows by " + Math.round(overflow) +
        "px at floor scale " + FIT_FLOOR + " — needs content trimming, not CSS scaling."
      );
    }
  }

  function fitAllSlides() {
    // Auto-fit measures every slide's overflow, which needs real layout. When
    // render-windowing is on, off-window slides are `content-visibility: hidden`
    // and report no layout, so lift windowing for the measurement pass, then
    // restore it. Measurement is layout-only (no paint/compositing) and the
    // slides stay hidden + image-unloaded, so this costs iOS nothing to render.
    var wasWindowed = document.body.classList.contains("windowed");
    if (wasWindowed) document.body.classList.remove("windowed");
    slides.forEach(function (s) {
      var inner = s.querySelector(".slide-inner");
      if (inner) fitSlide(inner);
    });
    if (wasWindowed) document.body.classList.add("windowed");
  }

  function debounce(fn, wait) {
    var t;
    return function () {
      clearTimeout(t);
      var args = arguments;
      t = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  // ---------------------------------------------------------------------
  // Fill-the-screen fit. The .stage keeps a fixed 1920px design *width*, so
  // the horizontal layout and every type size are identical on every device.
  // We scale it so that width fills the viewport edge-to-edge, then set its
  // *height* to whatever fills the viewport height at that same scale — so the
  // slide covers the whole display with NO letterbox bars on any screen size
  // or aspect ratio. Content stays vertically centered, gaining or losing only
  // vertical breathing room as the screen gets taller or shorter.
  // ---------------------------------------------------------------------
  var STAGE_W = 1920;
  function scaleStage() {
    if (!stage) return;
    var scale = window.innerWidth / STAGE_W;
    stage.style.height = (window.innerHeight / scale) + "px";
    stage.style.transform = "translate(-50%, -50%) scale(" + scale + ")";
  }

  // init
  var startIndex = 0;
  if (location.hash) {
    var n = parseInt(location.hash.replace("#", ""), 10);
    if (!isNaN(n)) startIndex = clamp(n - 1);
  }
  scaleStage();
  goTo(startIndex, false);
  fitAllSlides();
  document.body.classList.add("ready");
  // Now that every slide has been measured/fitted while fully renderable, turn on
  // render-windowing: only the active slide (± one) stays rendered, capping iOS
  // Safari's GPU/memory to a few slides instead of all ~130 (see setRenderWindow).
  setRenderWindow(current);
  document.body.classList.add("windowed");

  // fitAllSlides() above runs before web fonts are guaranteed to have
  // swapped in, so it can measure fallback-font metrics on slides whose
  // text is close to the fit threshold — re-run once fonts actually settle
  // so every slide's --fit reflects real glyph metrics, not a race.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(fitAllSlides);
  }

  // Rescale the stage immediately on any viewport change; --fit is now measured
  // against the constant 1080px-tall stage so it no longer changes with the
  // window, but re-run it debounced as a safety net.
  window.addEventListener("resize", scaleStage);
  window.addEventListener("orientationchange", scaleStage);
  window.addEventListener("resize", debounce(fitAllSlides, 150));

  window.addEventListener("hashchange", function () {
    var n = parseInt(location.hash.replace("#", ""), 10);
    if (!isNaN(n) && clamp(n - 1) !== current) goTo(n - 1, false);
  });
})();
