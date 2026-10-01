/* 流行钢琴即兴演奏与编配 — site script
   theme · navigation · math · ABC scores · search · progress · cross-reference previews ·
   chord keyboards · playable rhythm grids */
(function () {
  "use strict";

  var PAGE = document.body.dataset.page || "index.html";

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) { return null; }
  }
  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function loadScript(src, cb) {
    var s = document.createElement("script");
    s.src = src; s.onload = cb; s.onerror = cb;
    document.head.appendChild(s);
  }
  var hoverable = window.matchMedia("(hover: hover)").matches;

  /* ================================================================ theme */
  var themeBtn = document.querySelector(".theme-btn");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    store("theme", root.dataset.theme);
  });

  /* ================================================================ mobile menu & search button */
  var menuBtn = document.querySelector(".menu-btn");
  function setNav(open) {
    document.body.classList.toggle("nav-open", open);
    if (menuBtn) menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (menuBtn) {
    menuBtn.addEventListener("click", function () { setNav(!document.body.classList.contains("nav-open")); });
    document.addEventListener("click", function (e) {
      if (document.body.classList.contains("nav-open") &&
          !e.target.closest(".sidebar") && !e.target.closest(".menu-btn") && !e.target.closest(".search-btn")) setNav(false);
    });
  }
  var searchBtn = document.querySelector(".search-btn");
  var input = document.getElementById("search-input");
  function focusSearch() {
    if (window.innerWidth <= 960) setNav(true);
    if (input) { input.focus(); input.select(); }
  }
  if (searchBtn) searchBtn.addEventListener("click", focusSearch);

  var sidebar = document.querySelector(".sidebar");
  var cur = document.querySelector('.site-nav a[aria-current="page"]');
  if (cur && sidebar) sidebar.scrollTop = cur.offsetTop - sidebar.clientHeight / 2;

  /* ================================================================ math (KaTeX) */
  function renderMath(root) {
    if (!window.katex) return;
    root.querySelectorAll(".math").forEach(function (el) {
      if (el.dataset.done) return;
      el.dataset.done = "1";
      var tex = el.textContent;
      try {
        katex.render(tex, el, { displayMode: el.tagName === "DIV", throwOnError: false, strict: "ignore" });
      } catch (e) { el.textContent = tex; }
    });
  }
  var content = document.querySelector(".content");
  if (content) renderMath(content);

  /* ================================================================ audio (shared) */
  var actx = null;
  function audio() {
    if (!actx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      actx = new AC();
    }
    if (actx.state === "suspended") actx.resume();
    return actx;
  }
  // A soft, piano-like tone: a few decaying partials through a gentle low-pass filter.
  function pianoNote(ctx, midi, t0, dur, vel) {
    var f = 440 * Math.pow(2, (midi - 69) / 12);
    var out = ctx.createGain();
    var lp = ctx.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = Math.min(9000, f * 9);
    out.gain.setValueAtTime(0.0001, t0);
    out.gain.exponentialRampToValueAtTime(vel, t0 + 0.008);
    out.gain.exponentialRampToValueAtTime(vel * 0.35, t0 + 0.35);
    out.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    out.connect(lp); lp.connect(ctx.destination);
    [[1, 1], [2, 0.42], [3, 0.16], [4, 0.08]].forEach(function (p) {
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = f * p[0];
      g.gain.value = p[1];
      o.connect(g); g.connect(out);
      o.start(t0); o.stop(t0 + dur + 0.05);
    });
  }
  // A short percussive click for rhythm playback.
  function click(ctx, t0, freq, vel) {
    var o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "triangle"; o.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vel, t0 + 0.003);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.09);
    o.connect(g); g.connect(ctx.destination);
    o.start(t0); o.stop(t0 + 0.12);
  }

  /* ================================================================ ABC notation (abcjs) */
  function cursorControl(block) {
    function clear() {
      block.querySelectorAll(".abc-hl").forEach(function (el) { el.classList.remove("abc-hl"); });
    }
    return {
      onStart: clear,
      onFinished: clear,
      onEvent: function (ev) {
        clear();
        (ev.elements || []).forEach(function (group) {
          (group || []).forEach(function (el) { el.classList.add("abc-hl"); });
        });
      }
    };
  }
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
      ctl.load(block.querySelector(".abc-audio"), cursorControl(block),
        { displayLoop: true, displayPlay: true, displayProgress: true, displayRestart: true, displayWarp: true });
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
  var abcBlocks = document.querySelectorAll(".content .abc-block");
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

  /* ================================================================ checklists (达标自检) */
  document.querySelectorAll(".content input.task-list-item-checkbox").forEach(function (cb, i) {
    var key = "check:" + PAGE + ":" + i;
    cb.disabled = false;
    cb.checked = store(key) === "1";
    cb.addEventListener("change", function () { store(key, cb.checked ? "1" : null); });
  });

  /* ================================================================ lecture completion */
  function isDone(n) { return store("done:" + n) === "1"; }
  function refreshProgress() {
    document.querySelectorAll(".site-nav a[data-lectures]").forEach(function (a) {
      var ls = a.dataset.lectures.split(",");
      var d = ls.filter(isDone).length;
      var badge = a.querySelector(".nav-count");
      if (!badge) { badge = document.createElement("span"); badge.className = "nav-count"; a.appendChild(badge); }
      badge.textContent = d ? (d === ls.length ? "✓" : d + "/" + ls.length) : "";
      badge.classList.toggle("done", d === ls.length);
      badge.title = "已完成 " + d + " / " + ls.length + " 讲";
    });
    var pp = document.querySelector(".page-progress");
    var hs = document.querySelectorAll(".lecture-h");
    if (pp && hs.length) {
      var d = 0;
      hs.forEach(function (h) { if (isDone(h.dataset.lecture)) d++; });
      pp.hidden = false;
      pp.textContent = "已完成 " + d + " / " + hs.length + " 讲";
    }
    var hp = document.querySelector(".hero-progress");
    if (hp) {
      var total = 0;
      for (var n = 1; n <= 160; n++) if (isDone(n)) total++;
      if (total) {
        hp.hidden = false;
        hp.querySelector(".bar span").style.width = (total / 160 * 100) + "%";
        hp.querySelector("p").textContent = "学习进度：已完成 " + total + " / 160 讲";
      }
    }
  }
  document.querySelectorAll(".content .lecture-h").forEach(function (h) {
    var n = h.dataset.lecture;
    var b = document.createElement("button");
    b.type = "button"; b.className = "done-btn";
    function paint() {
      var d = isDone(n);
      b.setAttribute("aria-pressed", d ? "true" : "false");
      b.textContent = d ? "✓ 已完成" : "标记为已完成";
    }
    b.addEventListener("click", function () { store("done:" + n, isDone(n) ? null : "1"); paint(); refreshProgress(); });
    paint();
    h.insertBefore(b, h.querySelector(".anchor"));
  });
  refreshProgress();

  /* ================================================================ resume reading */
  var resume = document.querySelector(".hero .resume");
  if (resume) {
    try {
      var last = JSON.parse(store("last") || "null");
      if (last && last.u) {
        resume.hidden = false;
        resume.href = last.u;
        resume.textContent = "继续阅读：" + last.t;
      }
    } catch (e) {}
  }

  /* ================================================================ scroll: progress bar, to-top, toc spy, last position */
  var bar = document.querySelector(".read-progress span");
  var toTop = document.querySelector(".to-top");
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll(".toc a"));
  var tocTargets = tocLinks.map(function (a) { return document.getElementById(decodeURIComponent(a.hash.slice(1))); });
  var heads = content ? Array.prototype.slice.call(content.querySelectorAll("h2[id], h3[id]")) : [];
  var ticking = false, saveTimer = null;
  function onScroll() {
    ticking = false;
    var h = document.documentElement;
    var max = h.scrollHeight - h.clientHeight;
    if (bar) bar.style.width = (max > 0 ? Math.min(100, h.scrollTop / max * 100) : 0) + "%";
    if (toTop) toTop.hidden = h.scrollTop < 900;
    var line = h.scrollTop + 90, active = -1;
    for (var i = 0; i < tocTargets.length; i++) {
      if (tocTargets[i] && tocTargets[i].offsetTop <= line) active = i;
    }
    tocLinks.forEach(function (a, i) { a.classList.toggle("active", i === active); });
    if (active >= 0) {
      var toc = document.querySelector(".toc"), a = tocLinks[active];
      if (toc && (a.offsetTop < toc.scrollTop || a.offsetTop > toc.scrollTop + toc.clientHeight - 40))
        toc.scrollTop = a.offsetTop - toc.clientHeight / 3;
    }
    if (PAGE !== "index.html") {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(function () {
        var hid = "", title = document.title.split(" · ")[0];
        for (var j = 0; j < heads.length; j++) { if (heads[j].offsetTop <= line) hid = heads[j].id; else break; }
        var hd = hid && document.getElementById(hid);
        var label = hd ? hd.textContent.replace(/#$/, "").replace(/(✓ 已完成|标记为已完成)/, "").trim() : "";
        store("last", JSON.stringify({ u: PAGE + (hid ? "#" + hid : ""), t: label ? title.split("（")[0] + " · " + label : title }));
      }, 400);
    }
  }
  window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();
  if (toTop) toTop.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });

  /* ================================================================ popover */
  var pop = document.querySelector(".popover");
  var popOwner = null, hideTimer = null;
  function placePop(target) {
    var r = target.getBoundingClientRect();
    pop.style.left = "0px"; pop.style.top = "0px";
    var pw = pop.offsetWidth, ph = pop.offsetHeight;
    var vw = document.documentElement.clientWidth, vh = window.innerHeight;
    var left = Math.max(12, Math.min(r.left, vw - pw - 12));
    var below = r.bottom + 8 + ph < vh || r.top < ph + 16;
    var top = below ? r.bottom + 8 : r.top - ph - 8;
    pop.style.left = (left + window.scrollX) + "px";
    pop.style.top = (top + window.scrollY) + "px";
  }
  function showPop(target, html, cls) {
    clearTimeout(hideTimer);
    if (popOwner && popOwner !== target) popOwner.classList.remove("open");
    popOwner = target;
    target.classList.add("open");
    pop.className = "popover" + (cls ? " " + cls : "");
    pop.innerHTML = html;
    pop.hidden = false;
    renderMath(pop);
    placePop(target);
  }
  function hidePop(now) {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () {
      pop.hidden = true;
      if (popOwner) popOwner.classList.remove("open");
      popOwner = null;
    }, now ? 0 : 220);
  }
  if (pop) {
    pop.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    pop.addEventListener("mouseleave", function () { hidePop(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !pop.hidden) hidePop(true); });
    document.addEventListener("click", function (e) {
      if (!pop.hidden && !e.target.closest(".popover") && !e.target.closest("code.chord")) hidePop(true);
    });
    window.addEventListener("resize", function () { if (!pop.hidden && popOwner) placePop(popOwner); });
  }

  /* ---------------- cross-reference previews (命题 / 规则 / 判据 …) */
  var defsState = 0; // 0 none, 1 loading, 2 ready
  var pendingDef = null;
  function withDefs(cb) {
    if (defsState === 2) return cb();
    pendingDef = cb;
    if (defsState === 1) return;
    defsState = 1;
    loadScript("assets/defs.js", function () { defsState = 2; if (pendingDef) pendingDef(); });
  }
  function defHtml(a) {
    var key = a.dataset.item, d = (window.DEFS || {})[key];
    if (!d) return null;
    return '<div class="pop-head"><b>' + esc(key) + "</b><span>" + esc(d.p) + '</span><a href="' + esc(d.u) + '">前往原文 →</a></div>' +
      (d.h ? '<div class="pop-body">' + d.h + "</div>" : '<p class="pop-empty">（该条目的正文在原文处，点击上方链接前往。）</p>');
  }
  if (pop && hoverable) {
    var hoverTimer = null;
    document.addEventListener("mouseover", function (e) {
      var a = e.target.closest && e.target.closest(".content a.xref.item");
      if (!a) return;
      clearTimeout(hoverTimer);
      clearTimeout(hideTimer);
      hoverTimer = setTimeout(function () {
        withDefs(function () {
          var h = defHtml(a);
          if (h && a.matches(":hover")) showPop(a, h, "def-pop");
        });
      }, 260);
      a.addEventListener("mouseleave", function leave() {
        clearTimeout(hoverTimer);
        if (popOwner === a) hidePop();
        a.removeEventListener("mouseleave", leave);
      });
    });
  }

  /* ================================================================ chords */
  var LET = "CDEFGAB", PCS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  // quality -> [degree, semitones] pairs (0-2 §3.1); "(x)" marks an omittable tone
  var QUAL = {
    "": [[1, 0], [3, 4], [5, 7]], m: [[1, 0], [3, 3], [5, 7]], dim: [[1, 0], [3, 3], [5, 6]], aug: [[1, 0], [3, 4], [5, 8]],
    sus2: [[1, 0], [2, 2], [5, 7]], sus4: [[1, 0], [4, 5], [5, 7]],
    "6": [[1, 0], [3, 4], [5, 7], [6, 9]], m6: [[1, 0], [3, 3], [5, 7], [6, 9]],
    "7": [[1, 0], [3, 4], [5, 7], [7, 10]], maj7: [[1, 0], [3, 4], [5, 7], [7, 11]], m7: [[1, 0], [3, 3], [5, 7], [7, 10]],
    m7b5: [[1, 0], [3, 3], [5, 6], [7, 10]], dim7: [[1, 0], [3, 3], [5, 6], [7, 9]], mMaj7: [[1, 0], [3, 3], [5, 7], [7, 11]],
    "7sus4": [[1, 0], [4, 5], [5, 7], [7, 10]], "9sus4": [[1, 0], [4, 5], [5, 7], [7, 10], [9, 14]],
    "9": [[1, 0], [3, 4], [5, 7], [7, 10], [9, 14]], maj9: [[1, 0], [3, 4], [5, 7], [7, 11], [9, 14]],
    m9: [[1, 0], [3, 3], [5, 7], [7, 10], [9, 14]], add9: [[1, 0], [3, 4], [5, 7], [9, 14]], madd9: [[1, 0], [3, 3], [5, 7], [9, 14]],
    "11": [[1, 0], [3, 4, 1], [5, 7], [7, 10], [9, 14], [11, 17]], m11: [[1, 0], [3, 3], [5, 7], [7, 10], [9, 14], [11, 17]],
    "13": [[1, 0], [3, 4], [5, 7, 1], [7, 10], [9, 14, 1], [13, 21]], maj13: [[1, 0], [3, 4], [5, 7, 1], [7, 11], [9, 14, 1], [13, 21]],
    m13: [[1, 0], [3, 3], [5, 7, 1], [7, 10], [9, 14, 1], [13, 21]],
    "7b9": [[1, 0], [3, 4], [5, 7], [7, 10], [9, 13]], "7#9": [[1, 0], [3, 4], [5, 7], [7, 10], [9, 15]],
    "7#11": [[1, 0], [3, 4], [5, 7], [7, 10], [11, 18]], "7b13": [[1, 0], [3, 4], [5, 7], [7, 10], [13, 20]],
    "7b5": [[1, 0], [3, 4], [5, 6], [7, 10]], "7#5": [[1, 0], [3, 4], [5, 8], [7, 10]]
  };
  var QNAME = {
    "": "大三和弦", m: "小三和弦", dim: "减三和弦", aug: "增三和弦", sus2: "挂二和弦", sus4: "挂四和弦",
    "6": "大六和弦", m6: "小六和弦", "7": "属七和弦", maj7: "大七和弦", m7: "小七和弦", m7b5: "半减七和弦",
    dim7: "减七和弦", mMaj7: "小大七和弦", "7sus4": "属七挂四和弦", "9sus4": "属九挂四和弦", "9": "属九和弦",
    maj9: "大九和弦", m9: "小九和弦", add9: "加九和弦", madd9: "小加九和弦", "11": "属十一和弦", m11: "小十一和弦",
    "13": "属十三和弦", maj13: "大十三和弦", m13: "小十三和弦", "7b9": "变化属和弦（b9）", "7#9": "变化属和弦（#9）",
    "7#11": "变化属和弦（#11）", "7b13": "变化属和弦（b13）", "7b5": "属七降五和弦", "7#5": "属七升五和弦"
  };
  function pcOf(n) {
    var a = 0;
    for (var i = 1; i < n.length; i++) a += n[i] === "#" ? 1 : -1;
    return ((PCS[n[0]] + a) % 12 + 12) % 12;
  }
  function spell(root, deg, semi) {
    var L = LET[(LET.indexOf(root[0]) + deg - 1) % 7];
    var d = ((pcOf(root) + semi - PCS[L]) % 12 + 12) % 12;
    if (d > 6) d -= 12;
    return L + (d > 0 ? new Array(d + 1).join("#") : new Array(-d + 1).join("b"));
  }
  function parseChord(sym) {
    var m = /^([A-G][#b]?)(.*?)(?:\/([A-G][#b]?))?$/.exec(sym);
    if (!m || !QUAL.hasOwnProperty(m[2])) return null;
    var root = m[1], q = QUAL[m[2]], bass = m[3] || null;
    var tones = q.map(function (t) { return { name: spell(root, t[0], t[1]), semi: t[1], opt: !!t[2] }; });
    // voicing for display/playback: root position from the root in octave 3; a slash bass goes below
    var notes = [], base;
    if (bass) {
      var b = 48 + pcOf(bass);
      notes.push({ midi: b, bass: true });
      base = 60 + pcOf(root);
      if (base - b > 12) base -= 12;
    } else base = 48 + pcOf(root);
    tones.forEach(function (t) {
      var x = base + t.semi;
      while (x > 83) x -= 12;
      notes.push({ midi: x, bass: false });
    });
    return { sym: sym, root: root, qual: m[2], bass: bass, tones: tones, notes: notes };
  }
  function keyboardSvg(notes) {
    var lo = 48, hi = 83, ww = 13, wh = 58, bw = 8, bh = 36;
    var on = {}, bassOn = {};
    notes.forEach(function (n) { if (n.bass) bassOn[n.midi] = 1; else on[n.midi] = 1; });
    var whites = [], blacks = [], x = 0;
    for (var m = lo; m <= hi; m++) {
      var pc = m % 12, black = [1, 3, 6, 8, 10].indexOf(pc) >= 0;
      var cls = bassOn[m] ? " bass" : on[m] ? " on" : "";
      if (!black) {
        whites.push('<rect class="w' + cls + '" x="' + (x * ww + 0.5) + '" y="0.5" width="' + (ww - 1) + '" height="' + wh + '" rx="1.5"/>');
        if (pc === 0) whites.push('<text x="' + (x * ww + ww / 2) + '" y="' + (wh - 4) + '" text-anchor="middle">C' + (m / 12 - 1) + "</text>");
        x++;
      } else {
        blacks.push('<rect class="b' + cls + '" x="' + (x * ww - bw / 2) + '" y="0.5" width="' + bw + '" height="' + bh + '" rx="1"/>');
      }
    }
    var W = x * ww + 1;
    return '<svg class="kbd-svg" width="' + W + '" height="' + (wh + 1) + '" viewBox="0 0 ' + W + " " + (wh + 1) +
      '" role="img" aria-label="键盘示意">' + whites.join("") + blacks.join("") + "</svg>";
  }
  function playNotes(notes) {
    var ctx = audio();
    if (!ctx) return;
    var t = ctx.currentTime + 0.03;
    notes.forEach(function (n, i) { pianoNote(ctx, n.midi, t + i * 0.035, 2.2, n.bass ? 0.16 : 0.11); });
  }
  function chordHtml(c) {
    var tones = c.tones.map(function (t) { return t.opt ? "(" + t.name + ")" : t.name; }).join(" ");
    return '<div class="pop-head"><b>' + esc(c.sym) + "</b><span>" + esc(QNAME[c.qual] || "") +
      (c.bass ? " · 低音 " + esc(c.bass) : "") + "</span></div>" +
      keyboardSvg(c.notes) +
      '<div class="chord-notes"><button type="button" class="play-btn pop-play">▶ 试听</button>' +
      '<span>组成音：<span class="tones">' + esc(tones) + "</span></span>" +
      (c.bass ? '<span class="legend">蓝色 = 低音</span>' : "") + "</div>";
  }
  function openChord(el, play) {
    var c = parseChord(el.dataset.chord);
    if (!c) return;
    showPop(el, chordHtml(c), "chord-pop");
    pop.querySelector(".pop-play").addEventListener("click", function () { playNotes(c.notes); });
    if (play) playNotes(c.notes);
  }
  if (pop) {
    document.addEventListener("click", function (e) {
      var el = e.target.closest && e.target.closest("code.chord");
      if (!el) return;
      openChord(el, true);
    });
    document.addEventListener("keydown", function (e) {
      if ((e.key === "Enter" || e.key === " ") && document.activeElement && document.activeElement.matches("code.chord")) {
        e.preventDefault();
        openChord(document.activeElement, true);
      }
    });
    if (hoverable) {
      var chordTimer = null;
      document.addEventListener("mouseover", function (e) {
        var el = e.target.closest && e.target.closest("code.chord");
        if (!el) return;
        clearTimeout(chordTimer); clearTimeout(hideTimer);
        chordTimer = setTimeout(function () { if (el.matches(":hover")) openChord(el, false); }, 300);
        el.addEventListener("mouseleave", function leave() {
          clearTimeout(chordTimer);
          if (popOwner === el) hidePop();
          el.removeEventListener("mouseleave", leave);
        });
      });
    }
  }

  /* ================================================================ rhythm grids (0-2 §5) */
  // one beat: 4 cells, 6 cells (compound meter) or a {3-part} triplet; ">X" counts as one cell
  var BEAT_RE = /\{(?:>?[XẊ.\-]){3}\}|(?:>?[XẊ.\-]){6}(?![XẊ.\->])|(?:>?[XẊ.\-]){4}/g;
  // Parse one row of beats into hits: [{at: beats from start, acc: bool}], plus its length in beats.
  function parseBeats(text) {
    var hits = [], beat = 0, m;
    BEAT_RE.lastIndex = 0;
    while ((m = BEAT_RE.exec(text))) {
      var tok = m[0].replace(/[{}]/g, ""), cells = [];
      for (var i = 0; i < tok.length; i++) {
        if (tok[i] === ">") { cells.push({ c: tok[i + 1], acc: true }); i++; }
        else cells.push({ c: tok[i], acc: tok[i] === "Ẋ" });
      }
      cells.forEach(function (cell, k) {
        if (cell.c === "X" || cell.c === "Ẋ") hits.push({ at: beat + k / cells.length, acc: cell.acc });
      });
      beat++;
    }
    return { hits: hits, beats: beat };
  }
  function gridRows(text) {
    var rows = [];
    text.split("\n").forEach(function (line) {
      var m = /^([^|]*)(\|.*\|)\s*$/.exec(line);
      if (!m) return;
      var segs = m[2].split("|").slice(1, -1);
      var ok = segs.length && segs.every(function (s) {
        return s.trim() === "" ? false : s.trim().replace(BEAT_RE, "").replace(/\s+/g, "") === "";
      });
      if (!ok) return;
      var barBeats = segs.map(function (s) { return (s.match(BEAT_RE) || []).length; });
      var r = parseBeats(m[2]);
      r.label = m[1].trim(); r.bars = barBeats;
      rows.push(r);
    });
    return rows;
  }
  var ROW_FREQ = [1568, 784, 392, 1046];
  var player = null; // {stop: fn}
  function playGrid(rows, opts, onEnd) {
    var ctx = audio();
    if (!ctx) return null;
    var spb = 60 / opts.bpm, t0 = ctx.currentTime + 0.12, len = 0, timer = null, stopped = false;
    rows.forEach(function (r, ri) {
      var f = /LH|左手|低音|Bass|bass/.test(r.label) ? 196 : ROW_FREQ[ri % ROW_FREQ.length];
      r.hits.forEach(function (h) { click(ctx, t0 + h.at * spb, f, h.acc ? 0.5 : 0.28); });
      len = Math.max(len, r.beats);
    });
    if (opts.metro && rows.length) {
      var bars = rows[0].bars || [rows[0].beats], b = 0;
      bars.forEach(function (n) {
        for (var k = 0; k < n; k++) click(ctx, t0 + (b + k) * spb, k === 0 ? 2637 : 2093, k === 0 ? 0.09 : 0.05);
        b += n;
      });
      for (; b < len; b++) click(ctx, t0 + b * spb, 2093, 0.05);
    }
    timer = setTimeout(function () { if (!stopped) onEnd(); }, (len * spb + 0.15) * 1000);
    return { stop: function () { stopped = true; clearTimeout(timer); } };
  }
  function stopPlayer() { if (player) { player.stop(); player.done(); player = null; } }

  document.querySelectorAll(".content .grid-block").forEach(function (block) {
    var rows = gridRows(block.querySelector("pre").textContent);
    if (!rows.length) return;
    var key = "bpm";
    var bpm = parseInt(store(key), 10) || 72;
    var ctl = document.createElement("div");
    ctl.className = "grid-controls";
    ctl.innerHTML = '<button type="button" class="play-btn" aria-pressed="false">▶ 播放节奏</button>' +
      '<label>速度 <input type="range" min="40" max="160" step="2" value="' + bpm + '"><span class="bpm">♩ = ' + bpm + "</span></label>" +
      '<label><input type="checkbox" class="metro" checked> 节拍器</label>' +
      '<label><input type="checkbox" class="loop"> 循环</label>';
    block.appendChild(ctl);
    var btn = ctl.querySelector(".play-btn"), range = ctl.querySelector("input[type=range]"), out = ctl.querySelector(".bpm");
    range.addEventListener("input", function () { out.textContent = "♩ = " + range.value; store(key, range.value); });
    function done() { btn.setAttribute("aria-pressed", "false"); btn.textContent = "▶ 播放节奏"; }
    function start() {
      var p = playGrid(rows, { bpm: +range.value, metro: ctl.querySelector(".metro").checked }, function () {
        if (ctl.querySelector(".loop").checked && player && player.owner === btn) start();
        else stopPlayer();
      });
      if (!p) return;
      p.owner = btn; p.done = done;
      player = p;
      btn.setAttribute("aria-pressed", "true"); btn.textContent = "■ 停止";
    }
    btn.addEventListener("click", function () {
      var mine = player && player.owner === btn;
      stopPlayer();
      if (!mine) start();
    });
  });

  // inline grid such as `X-X-` or `X-X- --X-`: click to hear it twice with a count-in click
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest(".content code.grid");
    if (!el) return;
    var mine = player && player.owner === el;
    stopPlayer();
    if (mine) return;
    var once = parseBeats(el.textContent);
    if (!once.hits.length) return;
    var row = { label: "", hits: [], beats: once.beats * 2, bars: [once.beats, once.beats] };
    [0, 1].forEach(function (rep) {
      once.hits.forEach(function (h) { row.hits.push({ at: h.at + rep * once.beats, acc: h.acc }); });
    });
    var p = playGrid([row], { bpm: parseInt(store("bpm"), 10) || 72, metro: true }, stopPlayer);
    if (!p) return;
    p.owner = el;
    p.done = function () { el.classList.remove("playing"); };
    player = p;
    el.classList.add("playing");
  });

  /* ================================================================ search */
  var results = document.getElementById("search-results");
  var idxState = 0, sel = -1;
  function ensureIndex(cb) {
    if (idxState === 2) return cb();
    if (idxState === 1) return;
    idxState = 1;
    loadScript("assets/search-index.js", function () { idxState = 2; cb(); });
  }
  function mark(text, terms) {
    var out = esc(text);
    terms.forEach(function (t) {
      if (!t) return;
      var re = new RegExp("(" + esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
      out = out.replace(re, "<mark>$1</mark>");
    });
    return out;
  }
  function runSearch() {
    var q = input.value.trim().toLowerCase();
    sel = -1;
    if (!q) { results.hidden = true; results.innerHTML = ""; return; }
    var terms = q.split(/\s+/);
    var hits = [];
    var idx = window.SEARCH_INDEX || [];
    for (var i = 0; i < idx.length; i++) {
      var t = idx[i].t.toLowerCase();
      var hay = t + " " + idx[i].p.toLowerCase();
      if (!terms.every(function (x) { return hay.indexOf(x) !== -1; })) continue;
      var score = (t.indexOf(q) === 0 ? 0 : t.indexOf(q) > 0 ? 1 : 2) * 10 + idx[i].l;
      hits.push({ e: idx[i], s: score, i: i });
    }
    hits.sort(function (a, b) { return a.s - b.s || a.i - b.i; });
    hits = hits.slice(0, 80);
    results.innerHTML = hits.length
      ? hits.map(function (h) {
          var e = h.e, kind = e.l === 5 ? '<span class="kind">条目</span>' : /^第 \d+ 讲/.test(e.t) ? '<span class="kind">讲</span>' : "";
          return '<li><a href="' + e.u + '">' + kind + mark(e.t, terms) + "<small>" + esc(e.p) + "</small></a></li>";
        }).join("")
      : '<li class="empty">无匹配结果</li>';
    results.hidden = false;
  }
  function moveSel(d) {
    var as = results.querySelectorAll("a");
    if (!as.length) return;
    if (sel >= 0) as[sel].classList.remove("sel");
    sel = (sel + d + as.length) % as.length;
    as[sel].classList.add("sel");
    as[sel].scrollIntoView({ block: "nearest" });
  }
  if (input) {
    input.addEventListener("focus", function () { ensureIndex(function () {}); });
    input.addEventListener("input", function () { ensureIndex(runSearch); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { input.value = ""; runSearch(); input.blur(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); moveSel(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); moveSel(-1); }
      else if (e.key === "Enter") {
        var as = results.querySelectorAll("a"), a = as[sel >= 0 ? sel : 0];
        if (a) location.href = a.href;
      }
    });
    results.addEventListener("click", function () { setNav(false); });
  }

  /* ================================================================ keyboard shortcuts */
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (/INPUT|TEXTAREA|SELECT/.test(tag)) return;
    if (e.key === "/") { e.preventDefault(); focusSearch(); }
    else if (e.key === "[") { var p = document.querySelector('.pager a[rel="prev"]'); if (p) location.href = p.href; }
    else if (e.key === "]") { var n = document.querySelector('.pager a[rel="next"]'); if (n) location.href = n.href; }
  });
})();
