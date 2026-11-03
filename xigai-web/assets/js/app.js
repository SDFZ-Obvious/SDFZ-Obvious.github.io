/* =========================================================
   气候债务与全球治理 — presentation controller
   No dependencies. Works from any static path.
   ========================================================= */

(function () {
  "use strict";

  var DATA = window.DECK_DATA;
  if (!DATA || !Array.isArray(DATA.slides) || !DATA.slides.length) {
    var bootTitle = document.querySelector(".boot-title");
    if (bootTitle) bootTitle.textContent = "演示数据载入失败，请刷新页面";
    return;
  }

  var slides = DATA.slides;
  var total = slides.length;
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(selector, scope) {
    return (scope || document).querySelector(selector);
  }

  function $all(selector, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function normalize(value) {
    return String(value || "").toLowerCase().replace(/[\s\u3000]+/g, "");
  }

  var body = document.body;
  var app = $("#app");
  var stage = $("#stage");
  var frame = $("#frame");
  var layerA = $("#layerA");
  var layerB = $("#layerB");
  var imgA = $("#slideA");
  var imgB = $("#slideB");
  var stageLoader = $("#stageLoader");
  var sectionLabel = $("#sectionLabel");
  var slideTitle = $("#slideTitle");
  var currentNum = $("#currentNum");
  var timeline = $("#timeline");
  var prevBtn = $("#prevBtn");
  var nextBtn = $("#nextBtn");
  var edgePrev = $("#edgePrev");
  var edgeNext = $("#edgeNext");
  var playBtn = $("#playBtn");
  var autoplayFill = $("#autoplayFill");
  var overviewBtn = $("#overviewBtn");
  var transcriptBtn = $("#transcriptBtn");
  var fullscreenBtn = $("#fullscreenBtn");
  var overviewOverlay = $("#overviewOverlay");
  var overviewGrid = $("#overviewGrid");
  var transcriptOverlay = $("#transcriptOverlay");
  var transcriptList = $("#transcriptList");
  var transcriptSearch = $("#transcriptSearch");
  var searchClear = $("#searchClear");
  var searchMeta = $("#searchMeta");
  var announcer = $("#announcer");
  var toast = $("#toast");

  var timelineButtons = [];
  var overviewCards = [];
  var transcriptEntries = [];
  var emptyState = null;

  var state = {
    index: 0,
    layer: 0,
    playing: false,
    modal: null,
    lastFocus: null,
    loadToken: 0,
    loaderTimer: null,
    autoRaf: 0,
    autoStart: 0,
    toastTimer: 0,
    uiTimer: 0,
    fauxFullscreen: false
  };

  var AUTO_MS = 8000;

  /* ------------------------------------------------------------------
     Build navigation, overview and transcript
  ------------------------------------------------------------------ */

  function buildTimeline() {
    var fragment = document.createDocumentFragment();

    slides.forEach(function (slide, index) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "timeline-seg";
      button.setAttribute("aria-label", "第 " + (index + 1) + " 页：" + slide.title);
      button.title = pad(index + 1) + " · " + slide.title;
      button.addEventListener("click", function () {
        goTo(index, { user: true, source: "timeline" });
      });
      timelineButtons.push(button);
      fragment.appendChild(button);
    });

    timeline.appendChild(fragment);
  }

  function buildOverview() {
    var fragment = document.createDocumentFragment();

    slides.forEach(function (slide, index) {
      var card = document.createElement("button");
      card.type = "button";
      card.className = "card";
      card.setAttribute("aria-label", "第 " + (index + 1) + " 页：" + slide.title);
      card.setAttribute("aria-current", "false");

      var thumb = document.createElement("span");
      thumb.className = "card-thumb";
      var image = document.createElement("img");
      image.src = slide.thumb;
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      image.width = 640;
      image.height = 360;
      thumb.appendChild(image);

      var cardBody = document.createElement("span");
      cardBody.className = "card-body";
      var num = document.createElement("span");
      num.className = "card-num";
      num.textContent = pad(index + 1);
      var title = document.createElement("span");
      title.className = "card-title";
      title.textContent = slide.title;
      cardBody.appendChild(num);
      cardBody.appendChild(title);

      card.appendChild(thumb);
      card.appendChild(cardBody);
      card.addEventListener("click", function () {
        closeModal();
        goTo(index, { user: true, source: "overview" });
      });

      overviewCards.push(card);
      fragment.appendChild(card);
    });

    overviewGrid.appendChild(fragment);
  }

  function buildTranscript() {
    var fragment = document.createDocumentFragment();

    slides.forEach(function (slide, index) {
      var entry = document.createElement("article");
      entry.className = "entry";
      entry.dataset.index = String(index);

      var head = document.createElement("button");
      head.type = "button";
      head.className = "entry-head";
      head.setAttribute("aria-label", "跳转到第 " + (index + 1) + " 页：" + slide.title);

      var num = document.createElement("span");
      num.className = "entry-num";
      num.textContent = pad(index + 1);

      var title = document.createElement("span");
      title.className = "entry-title";
      title.textContent = slide.title;

      var go = document.createElement("span");
      go.className = "entry-go";
      go.setAttribute("aria-hidden", "true");
      go.innerHTML =
        '跳转<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#i-arrow"></use></svg>';

      head.appendChild(num);
      head.appendChild(title);
      head.appendChild(go);
      head.addEventListener("click", function () {
        closeModal();
        goTo(index, { user: true, source: "transcript" });
      });

      entry.appendChild(head);

      slide.text.forEach(function (line) {
        var paragraph = document.createElement("p");
        if (/^[“「]/.test(line)) paragraph.className = "entry-quote";
        paragraph.textContent = line;
        entry.appendChild(paragraph);
      });

      var haystack = normalize(
        slide.title + " " + slide.section + " " + slide.text.join(" ")
      );
      transcriptEntries.push({ el: entry, text: haystack });
      fragment.appendChild(entry);
    });

    emptyState = document.createElement("div");
    emptyState.className = "empty-state";
    emptyState.hidden = true;
    emptyState.innerHTML =
      "<b>未找到相关内容</b><span>换一个关键词试试，或清除搜索查看全部页面。</span>";

    transcriptList.appendChild(fragment);
    transcriptList.appendChild(emptyState);
  }

  /* ------------------------------------------------------------------
     Slide state
  ------------------------------------------------------------------ */

  function getHashIndex() {
    var match = window.location.hash.match(/slide-(\d+)/i);
    if (!match) match = window.location.hash.match(/^#(\d+)$/);
    if (!match) return 0;
    return clamp(parseInt(match[1], 10) - 1, 0, total - 1);
  }

  function updateChrome(index) {
    var slide = slides[index];

    sectionLabel.textContent = slide.section;
    slideTitle.textContent = slide.title;
    currentNum.textContent = pad(index + 1);
    announcer.textContent = "第 " + (index + 1) + " 页，" + slide.title;

    document.title = pad(index + 1) + " · " + slide.title + " — " + DATA.title;

    timelineButtons.forEach(function (button, buttonIndex) {
      button.classList.toggle("is-current", buttonIndex === index);
      button.classList.toggle("is-done", buttonIndex < index);
      if (buttonIndex === index) {
        button.setAttribute("aria-current", "page");
      } else {
        button.removeAttribute("aria-current");
      }
    });

    overviewCards.forEach(function (card, cardIndex) {
      var active = cardIndex === index;
      card.classList.toggle("is-active", active);
      card.setAttribute("aria-current", active ? "true" : "false");
    });

    transcriptEntries.forEach(function (entry, entryIndex) {
      entry.el.classList.toggle("is-active", entryIndex === index);
    });

    prevBtn.disabled = index === 0;
    nextBtn.disabled = index === total - 1;

    if (window.location.hash !== "#slide-" + (index + 1)) {
      try {
        window.history.replaceState(null, "", "#slide-" + (index + 1));
      } catch (error) {
        window.location.hash = "slide-" + (index + 1);
      }
    }
  }

  function slideAlt(slide) {
    return "第 " + slide.n + " 页：" + slide.title + "。";
  }

  function initialSlide() {
    var start = getHashIndex();
    state.index = start;
    var slide = slides[start];

    if (imgA.getAttribute("src") !== slide.image) {
      imgA.src = slide.image;
    }
    imgA.alt = slideAlt(slide);
    layerA.classList.add("is-active");
    layerB.classList.remove("is-active");
    state.layer = 0;

    updateChrome(start);
    preloadAround(start);
  }

  function setSlide(index, options) {
    options = options || {};
    index = clamp(index, 0, total - 1);

    var slide = slides[index];
    var showingB = state.layer === 0;
    var incomingLayer = showingB ? layerB : layerA;
    var outgoingLayer = showingB ? layerA : layerB;
    var incomingImage = showingB ? imgB : imgA;
    var token = ++state.loadToken;

    state.index = index;
    updateChrome(index);

    incomingImage.alt = slideAlt(slide);
    incomingImage.removeAttribute("data-fallback");

    clearTimeout(state.loaderTimer);
    state.loaderTimer = window.setTimeout(function () {
      if (token === state.loadToken) stageLoader.hidden = false;
    }, 150);

    function reveal() {
      if (token !== state.loadToken) return;
      clearTimeout(state.loaderTimer);
      stageLoader.hidden = true;
      incomingLayer.classList.add("is-active");
      outgoingLayer.classList.remove("is-active");
      state.layer = showingB ? 1 : 0;
      preloadAround(index);
    }

    function fail() {
      if (token !== state.loadToken) return;
      if (!incomingImage.dataset.fallback) {
        incomingImage.dataset.fallback = "1";
        incomingImage.src = slide.thumb;
        return;
      }
      clearTimeout(state.loaderTimer);
      stageLoader.hidden = true;
      showToast("第 " + (index + 1) + " 页载入失败，请检查网络后刷新。");
    }

    incomingImage.onload = function () {
      if (token !== state.loadToken) return;
      window.requestAnimationFrame(reveal);
    };
    incomingImage.onerror = fail;

    if (incomingImage.getAttribute("src") === slide.image && incomingImage.complete &&
        incomingImage.naturalWidth) {
      window.requestAnimationFrame(reveal);
    } else {
      incomingImage.src = slide.image;
    }

    if (options.user) {
      stopAutoplay();
    }
  }

  function goTo(index, options) {
    options = options || {};
    index = clamp(index, 0, total - 1);

    if (index === state.index && !options.force) {
      if (options.user) stopAutoplay();
      return;
    }

    setSlide(index, options);
  }

  function next(options) {
    options = options || {};
    if (state.index >= total - 1) {
      if (options.user) showToast("已经是最后一页了");
      return;
    }
    goTo(state.index + 1, { user: options.user !== false, source: options.source });
  }

  function prev() {
    if (state.index <= 0) {
      showToast("已经是第一页了");
      return;
    }
    goTo(state.index - 1, { user: true, source: "prev" });
  }

  function preloadAround(index) {
    [index + 1, index + 2, index - 1].forEach(function (i) {
      if (i < 0 || i >= total) return;
      var image = new Image();
      image.decoding = "async";
      image.src = slides[i].image;
    });
  }

  /* ------------------------------------------------------------------
     Autoplay
  ------------------------------------------------------------------ */

  function startAutoplay() {
    if (state.playing) return;
    if (state.index === total - 1) {
      setSlide(0, { force: true });
    }

    state.playing = true;
    body.classList.add("is-playing");
    playBtn.setAttribute("aria-pressed", "true");
    playBtn.setAttribute("aria-label", "暂停自动播放");
    playBtn.title = "暂停自动播放";
    state.autoStart = performance.now();

    function tick(now) {
      if (!state.playing) return;
      var progress = Math.min(1, (now - state.autoStart) / AUTO_MS);
      autoplayFill.style.transform = "scaleX(" + progress + ")";

      if (progress >= 1) {
        if (state.index >= total - 1) {
          stopAutoplay();
          showToast("已完成全部页面");
          return;
        }
        setSlide(state.index + 1);
        state.autoStart = performance.now();
      }

      state.autoRaf = window.requestAnimationFrame(tick);
    }

    state.autoRaf = window.requestAnimationFrame(tick);
  }

  function stopAutoplay() {
    if (!state.playing) return;
    state.playing = false;
    body.classList.remove("is-playing");
    playBtn.setAttribute("aria-pressed", "false");
    playBtn.setAttribute("aria-label", "自动播放");
    playBtn.title = "自动播放";
    window.cancelAnimationFrame(state.autoRaf);
    autoplayFill.style.transform = "scaleX(0)";
  }

  function toggleAutoplay() {
    if (state.playing) {
      stopAutoplay();
    } else {
      startAutoplay();
    }
  }

  /* ------------------------------------------------------------------
     Fullscreen
  ------------------------------------------------------------------ */

  function supportsFullscreen() {
    var element = document.documentElement;
    return Boolean(
      element.requestFullscreen ||
      element.webkitRequestFullscreen ||
      element.mozRequestFullScreen ||
      element.msRequestFullscreen
    );
  }

  function applyFullscreen(on) {
    body.classList.toggle("is-fs", on);
    fullscreenBtn.setAttribute("aria-pressed", on ? "true" : "false");
    fullscreenBtn.title = on ? "退出全屏（Esc）" : "全屏（F）";
    var label = fullscreenBtn.querySelector(".tool-label");
    if (label) label.textContent = on ? "退出" : "全屏";

    if (on) {
      wakeUi();
      showToast("按 F 或 Esc 退出全屏", 2400);
    } else {
      clearTimeout(state.uiTimer);
      body.classList.remove("ui-hidden");
    }
  }

  function toggleFullscreen() {
    var isNative = Boolean(document.fullscreenElement || document.webkitFullscreenElement);

    if (isNative) {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(function () {});
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      }
      return;
    }

    if (state.fauxFullscreen) {
      state.fauxFullscreen = false;
      applyFullscreen(false);
      return;
    }

    var element = document.documentElement;
    var request =
      element.requestFullscreen ||
      element.webkitRequestFullscreen ||
      element.mozRequestFullScreen ||
      element.msRequestFullscreen;

    if (!request) {
      state.fauxFullscreen = true;
      applyFullscreen(true);
      return;
    }

    try {
      var result = request.call(element);
      if (result && typeof result.catch === "function") {
        result.catch(function () {
          state.fauxFullscreen = true;
          applyFullscreen(true);
        });
      }
    } catch (error) {
      state.fauxFullscreen = true;
      applyFullscreen(true);
    }
  }

  function onFullscreenChange() {
    var active = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
    if (active) {
      state.fauxFullscreen = false;
    }
    applyFullscreen(active || state.fauxFullscreen);
  }

  function wakeUi() {
    if (!body.classList.contains("is-fs")) return;
    body.classList.remove("ui-hidden");
    clearTimeout(state.uiTimer);
    state.uiTimer = window.setTimeout(function () {
      if (body.classList.contains("is-fs") && !state.modal) {
        body.classList.add("ui-hidden");
      }
    }, 2800);
  }

  /* ------------------------------------------------------------------
     Modal / drawer
  ------------------------------------------------------------------ */

  function focusableElements(container) {
    return $all(
      'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      container
    ).filter(function (element) {
      return element.offsetParent !== null;
    });
  }

  function openModal(name) {
    if (state.modal) closeModal();
    stopAutoplay();

    state.lastFocus = document.activeElement;
    state.modal = name;

    var overlay = name === "overview" ? overviewOverlay : transcriptOverlay;
    var sheet = $(".sheet", overlay);

    overlay.classList.add("is-open");
    overlay.setAttribute("aria-hidden", "false");
    if (app) app.inert = true;

    window.requestAnimationFrame(function () {
      if (name === "overview") {
        var activeCard = overviewCards[state.index];
        var closeButton = $(".icon-btn", sheet);
        (activeCard || closeButton).focus({ preventScroll: true });
        if (activeCard) activeCard.scrollIntoView({ block: "nearest" });
      } else {
        transcriptSearch.focus({ preventScroll: true });
        var activeEntry = transcriptEntries[state.index].el;
        activeEntry.scrollIntoView({ block: "center" });
      }
    });
  }

  function closeModal() {
    if (!state.modal) return;

    var overlay = state.modal === "overview" ? overviewOverlay : transcriptOverlay;
    overlay.classList.remove("is-open");
    overlay.setAttribute("aria-hidden", "true");
    if (app) app.inert = false;

    state.modal = null;
    if (state.lastFocus && typeof state.lastFocus.focus === "function") {
      state.lastFocus.focus({ preventScroll: true });
    }
    if (body.classList.contains("is-fs")) wakeUi();
  }

  function trapFocus(event) {
    if (!state.modal) return;
    var overlay = state.modal === "overview" ? overviewOverlay : transcriptOverlay;
    var sheet = $(".sheet", overlay);
    var focusable = focusableElements(sheet);
    if (!focusable.length) return;

    var first = focusable[0];
    var last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function filterTranscript() {
    var query = normalize(transcriptSearch.value);
    var count = 0;

    transcriptEntries.forEach(function (entry) {
      var matches = !query || entry.text.indexOf(query) !== -1;
      entry.el.hidden = !matches;
      if (matches) count += 1;
    });

    if (emptyState) emptyState.hidden = count !== 0;
    searchClear.hidden = !query;

    if (query) {
      searchMeta.textContent = "找到 " + count + " 页 · 按 Esc 关闭";
    } else {
      searchMeta.textContent = "共 " + total + " 页 · 点击标题跳转";
    }
  }

  function clearSearch() {
    transcriptSearch.value = "";
    filterTranscript();
    transcriptSearch.focus();
  }

  /* ------------------------------------------------------------------
     Toast
  ------------------------------------------------------------------ */

  function showToast(message, duration) {
    duration = duration || 2100;
    toast.textContent = message;
    toast.classList.add("is-show");
    clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(function () {
      toast.classList.remove("is-show");
    }, duration);
  }

  /* ------------------------------------------------------------------
     Boot
  ------------------------------------------------------------------ */

  function finishBoot() {
    body.classList.remove("is-loading");
  }

  function boot() {
    initialSlide();

    var firstImage = imgA;
    var timeout = window.setTimeout(finishBoot, 4200);

    function done() {
      clearTimeout(timeout);
      finishBoot();
    }

    if (firstImage.complete && firstImage.naturalWidth) {
      if (typeof firstImage.decode === "function") {
        firstImage.decode().then(done).catch(done);
      } else {
        window.requestAnimationFrame(done);
      }
    } else {
      firstImage.addEventListener("load", done, { once: true });
      firstImage.addEventListener("error", done, { once: true });
    }
  }

  /* ------------------------------------------------------------------
     Events
  ------------------------------------------------------------------ */

  function bindEvents() {
    prevBtn.addEventListener("click", prev);
    nextBtn.addEventListener("click", function () {
      next({ user: true, source: "next" });
    });
    edgePrev.addEventListener("click", prev);
    edgeNext.addEventListener("click", function () {
      next({ user: true, source: "edge" });
    });
    playBtn.addEventListener("click", toggleAutoplay);

    overviewBtn.addEventListener("click", function () {
      openModal("overview");
    });
    transcriptBtn.addEventListener("click", function () {
      openModal("transcript");
    });
    fullscreenBtn.addEventListener("click", toggleFullscreen);

    $all("[data-close]").forEach(function (element) {
      element.addEventListener("click", function () {
        closeModal();
      });
    });

    transcriptSearch.addEventListener("input", filterTranscript);
    searchClear.addEventListener("click", clearSearch);

    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("webkitfullscreenchange", onFullscreenChange);

    document.addEventListener("keydown", function (event) {
      if (event.isComposing) return;

      if (event.key === "Escape") {
        if (state.modal) {
          event.preventDefault();
          closeModal();
          return;
        }
        if (state.fauxFullscreen) {
          state.fauxFullscreen = false;
          applyFullscreen(false);
          return;
        }
        return;
      }

      if (state.modal) {
        if (event.key === "Tab") trapFocus(event);
        return;
      }

      var target = event.target;
      var tag = target && target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      // Do not steal Enter/Space from focused buttons and links.
      if (
        target &&
        typeof target.closest === "function" &&
        target.closest("button, a, [role='button'], [contenteditable='true']") &&
        (event.key === " " || event.key === "Enter")
      ) {
        return;
      }

      switch (event.key) {
        case "ArrowRight":
        case "ArrowDown":
        case "PageDown":
          event.preventDefault();
          next({ user: true, source: "keyboard" });
          break;
        case "ArrowLeft":
        case "ArrowUp":
        case "PageUp":
        case "Backspace":
          event.preventDefault();
          prev();
          break;
        case " ":
        case "Enter":
          event.preventDefault();
          next({ user: true, source: "keyboard" });
          break;
        case "Home":
          event.preventDefault();
          goTo(0, { user: true });
          break;
        case "End":
          event.preventDefault();
          goTo(total - 1, { user: true });
          break;
        case "f":
        case "F":
          event.preventDefault();
          toggleFullscreen();
          break;
        case "o":
        case "O":
          event.preventDefault();
          openModal("overview");
          break;
        case "t":
        case "T":
          event.preventDefault();
          openModal("transcript");
          break;
        case "?":
          showToast("← → 翻页 · F 全屏 · O 目录 · T 文字稿", 3600);
          break;
        default:
          break;
      }
    });

    window.addEventListener("hashchange", function () {
      var target = getHashIndex();
      if (target !== state.index) {
        goTo(target, { user: true, source: "hash" });
      }
    });

    document.addEventListener("pointermove", wakeUi, { passive: true });
    document.addEventListener("pointerdown", wakeUi, { passive: true });
    document.addEventListener("keydown", wakeUi);

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stopAutoplay();
    });

    // Touch swipe on the slide surface.
    var touchStart = null;
    var suppressClick = false;

    frame.addEventListener("click", function (event) {
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      if (event.target.closest("button, a")) return;
      next({ user: true, source: "stage" });
    });

    frame.addEventListener(
      "pointerdown",
      function (event) {
        if (event.pointerType !== "touch") return;
        if (event.target.closest("button")) return;
        touchStart = {
          x: event.clientX,
          y: event.clientY,
          time: Date.now(),
          id: event.pointerId
        };
      },
      { passive: true }
    );

    frame.addEventListener(
      "pointerup",
      function (event) {
        if (!touchStart || event.pointerId !== touchStart.id) return;
        var dx = event.clientX - touchStart.x;
        var dy = event.clientY - touchStart.y;
        var elapsed = Date.now() - touchStart.time;
        touchStart = null;

        if (elapsed > 900) return;
        if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy) * 1.25) return;

        suppressClick = true;
        window.setTimeout(function () {
          suppressClick = false;
        }, 450);

        if (dx < 0) {
          next({ user: true, source: "swipe" });
        } else {
          prev();
        }
      },
      { passive: true }
    );

    frame.addEventListener(
      "pointercancel",
      function () {
        touchStart = null;
      },
      { passive: true }
    );

    // If the user starts interacting while the controls are hidden, bring
    // them back before the interaction lands.
    document.addEventListener(
      "mousemove",
      function () {
        if (body.classList.contains("ui-hidden")) wakeUi();
      },
      { passive: true }
    );

    // Avoid the browser restoring a stale scroll position.
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
  }

  /* ------------------------------------------------------------------
     Start
  ------------------------------------------------------------------ */

  buildTimeline();
  buildOverview();
  buildTranscript();
  bindEvents();
  boot();
})();
