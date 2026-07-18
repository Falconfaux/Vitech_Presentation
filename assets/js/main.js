(function () {
  "use strict";

  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var total = slides.length;
  var current = 0;
  var deck = document.getElementById("deck");
  var progress = document.getElementById("progress");
  var counterNow = document.getElementById("counter-now");
  var counterTotal = document.getElementById("counter-total");
  var sectionsPanel = document.getElementById("sections-panel");
  var lightbox = document.getElementById("lightbox");
  var lightboxImg = lightbox ? lightbox.querySelector("img") : null;
  var counterSection = document.getElementById("counter-section");

  counterTotal.textContent = total;

  function clamp(n) { return Math.max(0, Math.min(total - 1, n)); }

  function lazyLoadNear(index) {
    for (var d = -1; d <= 2; d++) {
      var s = slides[index + d];
      if (!s) continue;
      var imgs = s.querySelectorAll("img[data-src]");
      imgs.forEach(function (img) {
        img.src = img.getAttribute("data-src");
        img.removeAttribute("data-src");
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
    lazyLoadNear(index);
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

  document.getElementById("btn-next").addEventListener("click", next);
  document.getElementById("btn-prev").addEventListener("click", prev);

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
    slides.forEach(function (s) {
      var inner = s.querySelector(".slide-inner");
      if (inner) fitSlide(inner);
    });
  }

  function debounce(fn, wait) {
    var t;
    return function () {
      clearTimeout(t);
      var args = arguments;
      t = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  // init
  var startIndex = 0;
  if (location.hash) {
    var n = parseInt(location.hash.replace("#", ""), 10);
    if (!isNaN(n)) startIndex = clamp(n - 1);
  }
  goTo(startIndex, false);
  fitAllSlides();
  document.body.classList.add("ready");

  window.addEventListener("resize", debounce(fitAllSlides, 150));

  window.addEventListener("hashchange", function () {
    var n = parseInt(location.hash.replace("#", ""), 10);
    if (!isNaN(n) && clamp(n - 1) !== current) goTo(n - 1, false);
  });
})();
