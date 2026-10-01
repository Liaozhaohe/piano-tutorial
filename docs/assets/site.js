/* 流行钢琴即兴演奏与编配 — site script (math, ABC notation, search, theme, checklists) */
(function () {
  "use strict";

  function store(get, key, value) {
    try {
      if (get) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) { return null; }
  }

  /* ---------- theme ---------- */
  var themeBtn = document.querySelector(".theme-btn");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    store(false, "theme", root.dataset.theme);
  });

  /* ---------- mobile menu ---------- */
  var menuBtn = document.querySelector(".menu-btn");
  if (menuBtn) {
    menuBtn.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (document.body.classList.contains("nav-open") &&
          !e.target.closest(".sidebar") && !e.target.closest(".menu-btn")) {
        document.body.classList.remove("nav-open");
        menuBtn.setAttribute("aria-expanded", "false");
      }
    });
  }
  var cur = document.querySelector('.site-nav a[aria-current="page"]');
  var sidebar = document.querySelector(".sidebar");
  if (cur && sidebar) sidebar.scrollTop = cur.offsetTop - sidebar.clientHeight / 2;

  /* ---------- math (KaTeX) ---------- */
  if (window.katex) {
    document.querySelectorAll(".content .math").forEach(function (el) {
      var tex = el.textContent;
      try {
        katex.render(tex, el, { displayMode: el.tagName === "DIV", throwOnError: false, strict: "ignore" });
      } catch (e) { el.textContent = tex; }
    });
  }

  /* ---------- ABC notation (abcjs) ---------- */
  function renderAbc(block) {
    if (block.dataset.rendered) return;
    block.dataset.rendered = "1";
    var src = block.querySelector(".abc-source code").textContent;
    var target = block.querySelector(".abc-render");
    var tunes;
    try {
      tunes = ABCJS.renderAbc(target, src, { responsive: "resize", add_classes: true, paddingleft: 0, paddingright: 0 });
    } catch (e) {
      target.innerHTML = '<p class="abc-error">谱例渲染失败，请参阅下方 ABC 源码。</p>';
      return;
    }
    var btn = block.querySelector(".abc-play");
    if (!ABCJS.synth || !ABCJS.synth.supportsAudio()) { btn.hidden = true; return; }
    var ctl = null;
    btn.addEventListener("click", function () {
      if (ctl) return;
      btn.disabled = true;
      btn.textContent = "加载音色…";
      ctl = new ABCJS.synth.SynthController();
      ctl.load(block.querySelector(".abc-audio"), null,
        { displayPlay: true, displayProgress: true, displayRestart: true, displayWarp: true });
      ctl.setTune(tunes[0], true, { program: 0 }).then(function () {
        btn.hidden = true;
        ctl.play();
      }).catch(function () {
        btn.disabled = false;
        btn.textContent = "▶ 播放（加载失败，点击重试）";
        ctl = null;
      });
    });
  }
  var abcBlocks = document.querySelectorAll(".abc-block");
  if (abcBlocks.length) {
    if (!window.ABCJS) {
      abcBlocks.forEach(function (b) {
        b.querySelector(".abc-render").innerHTML = '<p class="abc-error">谱例脚本未能加载，请参阅下方 ABC 源码。</p>';
        b.querySelector(".abc-controls").hidden = true;
      });
    } else if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) { renderAbc(en.target); io.unobserve(en.target); }
        });
      }, { rootMargin: "600px 0px" });
      abcBlocks.forEach(function (b) { io.observe(b); });
      window.addEventListener("beforeprint", function () { abcBlocks.forEach(renderAbc); });
    } else {
      abcBlocks.forEach(renderAbc);
    }
  }

  /* ---------- checklists (达标自检) — remembered in this browser only ---------- */
  var page = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".content input.task-list-item-checkbox").forEach(function (cb, i) {
    var key = "check:" + page + ":" + i;
    cb.checked = store(true, key) === "1";
    cb.addEventListener("change", function () { store(false, key, cb.checked ? "1" : null); });
  });

  /* ---------- search over lecture / section headings ---------- */
  var input = document.getElementById("search-input");
  var results = document.getElementById("search-results");
  var loading = false;
  function ensureIndex(cb) {
    if (window.SEARCH_INDEX) return cb();
    if (loading) return;
    loading = true;
    var s = document.createElement("script");
    s.src = "assets/search-index.js";
    s.onload = cb;
    document.head.appendChild(s);
  }
  function esc(t) {
    return t.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  function runSearch() {
    var q = input.value.trim().toLowerCase();
    if (!q) { results.hidden = true; results.innerHTML = ""; return; }
    var terms = q.split(/\s+/);
    var hits = [];
    var idx = window.SEARCH_INDEX || [];
    for (var i = 0; i < idx.length && hits.length < 60; i++) {
      var hay = (idx[i].t + " " + idx[i].p).toLowerCase();
      if (terms.every(function (t) { return hay.indexOf(t) !== -1; })) hits.push(idx[i]);
    }
    hits.sort(function (a, b) { return a.l - b.l; });
    results.innerHTML = hits.length
      ? hits.map(function (h) {
          return '<li><a href="' + h.u + '">' + esc(h.t) + "<small>" + esc(h.p) + "</small></a></li>";
        }).join("")
      : '<li class="empty">无匹配结果</li>';
    results.hidden = false;
  }
  if (input) {
    input.addEventListener("focus", function () { ensureIndex(function () {}); });
    input.addEventListener("input", function () { ensureIndex(runSearch); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { input.value = ""; runSearch(); }
      if (e.key === "Enter") { var a = results.querySelector("a"); if (a) location.href = a.href; }
    });
  }
})();
