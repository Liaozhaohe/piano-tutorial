"""Build the static HTML site (docs/) from the Markdown tutorial (tutorial/).

Usage:  py -X utf8 tools/build_site.py
Requires: markdown-it-py, mdit-py-plugins  (pip install markdown-it-py mdit-py-plugins)

The Markdown sources are never modified.  The output directory docs/ is
regenerated from scratch on every run and is what GitHub Pages serves.

Besides plain rendering, the build adds:
  * callout styling for blockquotes, classified by their leading bold label
    (命题 / 规则 / 练习 / 证明 / 术语说明 …);
  * cross-reference links for numbered items ("命题 103-1"), lectures ("第 25 讲"),
    sections ("§25.3", "0-2 §5.2") and chapters ("第 4-1 章"), with hover previews
    for numbered items (assets/defs.js);
  * interactive hooks: chord symbols in inline code, playable rhythm grids,
    per-lecture completion toggles.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import shutil
import sys
import unicodedata
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "tutorial"
OUT = ROOT / "docs"
ASSETS = pathlib.Path(__file__).resolve().parent / "site_assets"

SITE_TITLE = "流行钢琴即兴演奏与编配"
KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.22/dist"
ABCJS = "https://cdn.jsdelivr.net/npm/abcjs@6.5.1"
FONTS = "https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;700&display=swap"
CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}

# Numbered items that the chapters define and cite ("命题 103-1", "规则 65-R" …).
KINDS = "命题|规则|判据|方案|记号|配方|算法|流程|练习|推论|定理"
ITEM_RE = re.compile(rf"({KINDS})\s?(\d+-[0-9A-Za-z]+)")
LECTURE_RE = re.compile(r"第 (\d+) 讲")
CHAPTER_RE = re.compile(r"第 (\d-\d) 章")
SECTION_RE = re.compile(r"(?:(\d-\d) )?§(\d+(?:\.\d+)?)")
XREF_RE = re.compile(
    rf"(?P<item>{ITEM_RE.pattern})|(?P<lec>{LECTURE_RE.pattern})"
    rf"|(?P<chap>{CHAPTER_RE.pattern})|(?P<sec>{SECTION_RE.pattern})"
)

# Chord symbols (0-2 §3) and rhythm grids (0-2 §5) written as inline code.
CHORD_RE = re.compile(
    r"[A-G](?:#|b)?(?:maj7|maj9|maj13|mMaj7|m7b5|madd9|m6|m7|m9|m11|m13|m|dim7|dim|aug|"
    r"sus2|sus4|7sus4|9sus4|add9|7b9|7#9|7#11|7b13|7b5|7#5|6|7|9|11|13)?(?:/[A-G](?:#|b)?)?"
)
# one beat: 4 cells, 6 cells (compound meter, 1-2 第 15 讲) or a {3-part} triplet; ">X" is one cell
GRID_BEAT = r"(?:\{(?:>?[XẊ.\-]){3}\}|(?:>?[XẊ.\-]){6}|(?:>?[XẊ.\-]){4})"
GRID_RE = re.compile(rf"{GRID_BEAT}(?: {GRID_BEAT})*")
GRID_ROW_RE = re.compile(rf"^[^|\n]*\|(?:\s*{GRID_BEAT}(?: {GRID_BEAT})*\s*\|)+\s*$", re.M)

CALLOUTS = [  # (class, label regex) — first match wins
    ("proof", r"证明"),
    ("thm", r"(命题|定理|推论|引理|性质)"),
    ("ex", r"练习"),
    ("warn", r"(注意|术语说明|警告|⚠|安全)"),
    ("check", r"(达标|自查点|自检)"),
    ("rule", r"(本教程规则|本教程的取舍规则|规则|判据|算法|流程|方案|记号|配方|规程|策略|本教程采用的)"),
    ("note", r"(谱例说明|核对|理由|依据|结论|对照|说明)"),
]


# ---------------------------------------------------------------- pages

class Page:
    def __init__(self, src: pathlib.Path):
        self.src = src
        self.out = out_name(src)
        self.group = group_label(src)
        self.code = page_code(src)
        self.title = ""
        self.tokens = None
        self.env: dict = {}
        self.ids: set[str] = set()
        self.toc: list[tuple[int, str, str]] = []
        self.headings: list[tuple[int, str, str]] = []
        self.sections: dict[str, str] = {}  # "25.3" -> heading id
        self.lectures: list[int] = []
        self.chars = 0


def out_name(src: pathlib.Path) -> str:
    if src.parent == SRC and src.name == "README.md":
        return "index.html"
    m = re.match(r"^(\d)-(\d)-", src.name)
    if m:
        return f"{m.group(1)}-{m.group(2)}.html"
    m = re.match(r"^([A-Z])-", src.name)
    if m:
        return f"appendix-{m.group(1).lower()}.html"
    raise SystemExit(f"no output name rule for {src}")


def page_code(src: pathlib.Path) -> str:
    m = re.match(r"^(\d-\d)-", src.name)
    return m.group(1) if m else ""


def group_label(src: pathlib.Path) -> str:
    if src.parent == SRC:
        return ""
    m = re.match(r"^(\d+)-(.+)$", src.parent.name)
    n, rest = int(m.group(1)), m.group(2)
    return f"板块{CN_NUM[n]}　{rest}" if n in CN_NUM else rest


def collect_pages() -> list[Page]:
    files = [SRC / "README.md"]
    for d in sorted(p for p in SRC.iterdir() if p.is_dir() and re.match(r"^\d+-", p.name)):
        files += sorted(d.glob("*.md"))
    return [Page(f) for f in files]


# ---------------------------------------------------------------- markdown

def gh_slug(text: str) -> str:
    """GitHub-style heading anchor, so that the sources' existing #anchors keep working."""
    s = text.strip().lower()
    s = "".join(
        c for c in s
        if c in "- " or unicodedata.category(c)[0] in "LM" or unicodedata.category(c) in ("Nd", "Pc")
    )
    return s.replace(" ", "-")


def inline_text(tok) -> str:
    parts = []
    for c in tok.children or []:
        if c.type in ("text", "code_inline", "math_inline"):
            parts.append(c.content)
        elif c.type == "softbreak":
            parts.append(" ")
    return "".join(parts)


def make_md() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "typographer": False, "breaks": True})
    md.enable(["table", "strikethrough"])
    md.use(dollarmath_plugin, allow_space=True, allow_digits=True, double_inline=True)
    md.use(tasklists_plugin, enabled=True)

    def heading_open(self, tokens, idx, options, env):
        t = tokens[idx]
        extra = ""
        if t.meta.get("lecture"):
            extra = f' class="lecture-h" data-lecture="{t.meta["lecture"]}"'
        return f'<{t.tag} id="{html.escape(t.meta["id"])}"{extra}>'

    def heading_close(self, tokens, idx, options, env):
        t = tokens[idx]
        hid = html.escape(t.meta["id"])
        return f'<a class="anchor" href="#{hid}" aria-label="本节链接">#</a></{t.tag}>\n'

    def table_open(self, tokens, idx, options, env):
        return '<div class="table-wrap"><table>\n'

    def table_close(self, tokens, idx, options, env):
        return "</table></div>\n"

    def code_inline(self, tokens, idx, options, env):
        c = tokens[idx].content
        e = html.escape(c)
        if CHORD_RE.fullmatch(c):
            return f'<code class="chord" tabindex="0" data-chord="{e}">{e}</code>'
        if GRID_RE.fullmatch(c) and ("X" in c or "Ẋ" in c):
            return f'<code class="grid" tabindex="0" title="点击试听">{e}</code>'
        return f"<code>{e}</code>"

    def fence(self, tokens, idx, options, env):
        t = tokens[idx]
        lang = (t.info or "").strip().split(" ")[0]
        code = html.escape(t.content)
        if lang == "abc":
            env["abc_count"] = env.get("abc_count", 0) + 1
            return (
                '<figure class="abc-block">'
                '<div class="abc-render" aria-label="五线谱"></div>'
                '<div class="abc-controls"><button type="button" class="abc-play">'
                '<span aria-hidden="true">▶</span> 播放</button>'
                '<div class="abc-audio"></div></div>'
                f'<details class="abc-source"><summary>ABC 源码</summary><pre><code>{code}</code></pre></details>'
                "</figure>\n"
            )
        cls = f' class="language-{html.escape(lang)}"' if lang else ""
        pre = f"<pre><code{cls}>{code}</code></pre>"
        if not lang and GRID_ROW_RE.search(t.content):
            return f'<div class="grid-block">{pre}</div>\n'
        return pre + "\n"

    def link_open(self, tokens, idx, options, env):
        t = tokens[idx]
        href = t.attrGet("href") or ""
        t.attrSet("href", env["resolve_link"](href))
        return self.renderToken(tokens, idx, options, env)

    md.add_render_rule("heading_open", heading_open)
    md.add_render_rule("heading_close", heading_close)
    md.add_render_rule("table_open", table_open)
    md.add_render_rule("table_close", table_close)
    md.add_render_rule("code_inline", code_inline)
    md.add_render_rule("fence", fence)
    md.add_render_rule("link_open", link_open)
    return md


def assign_ids(page: Page) -> None:
    counts: dict[str, int] = {}
    toks = page.tokens
    for i, t in enumerate(toks):
        if t.type == "inline":
            page.chars += len(t.content)
        if t.type != "heading_open":
            continue
        text = inline_text(toks[i + 1]).strip()
        base = gh_slug(text) or "section"
        n = counts.get(base, 0)
        hid = base if n == 0 else f"{base}-{n}"
        counts[base] = n + 1
        t.meta["id"] = hid
        toks[i + 2].meta["id"] = hid  # heading_close
        page.ids.add(hid)
        level = int(t.tag[1])
        m = LECTURE_RE.match(text)
        if m and level in (2, 3):
            t.meta["lecture"] = int(m.group(1))
            page.lectures.append(int(m.group(1)))
        m = re.match(r"^(\d+(?:\.\d+)*)[.\s　]", text)
        if m and level >= 2:
            page.sections.setdefault(m.group(1), hid)
        if level == 1 and not page.title:
            page.title = text
        if level in (2, 3):
            page.toc.append((level, hid, text))
        if level in (2, 3, 4):
            page.headings.append((level, hid, text))


def block_end(toks, i: int) -> int:
    """Index of the token closing the block opened at toks[i]."""
    depth = 0
    for j in range(i, len(toks)):
        depth += toks[j].nesting
        if depth == 0:
            return j
    return len(toks) - 1


def first_label(toks, i: int) -> str:
    """Leading bold text of the first paragraph inside the blockquote opened at toks[i]."""
    if i + 2 < len(toks) and toks[i + 1].type == "paragraph_open" and toks[i + 2].type == "inline":
        ch = [c for c in toks[i + 2].children or [] if not (c.type == "text" and not c.content)]
        if ch and ch[0].type == "strong_open":
            parts = []
            for c in ch[1:]:
                if c.type == "strong_close":
                    break
                if c.type in ("text", "code_inline"):
                    parts.append(c.content)
            return "".join(parts)
    return ""


def line_labels(inline) -> list[str]:
    """Bold texts that open a line of a paragraph ("**规则 27-R1**：…" on each line)."""
    out, cur, at_start = [], None, True
    for c in inline.children or []:
        if c.type == "text" and not c.content:
            continue
        if cur is not None:
            if c.type == "strong_close":
                out.append("".join(cur))
                cur = None
            elif c.type in ("text", "code_inline"):
                cur.append(c.content)
            continue
        if at_start and c.type == "strong_open":
            cur = []
        at_start = c.type in ("softbreak", "hardbreak")
    return out


def classify_callouts(page: Page) -> None:
    toks = page.tokens
    first = True
    for i, t in enumerate(toks):
        if t.type != "blockquote_open" or t.level != 0:
            continue
        label = first_label(toks, i)
        cls = ""
        for name, pat in CALLOUTS:
            if label and re.match(pat, label):
                cls = name
                break
        if not cls and label and re.match(r"^[^（(：]{1,24}[（(][A-Za-z]", label):
            cls = "def"
        if first and i < 8:
            cls = "intro"
        first = False
        if cls:
            t.attrSet("class", f"callout {cls}")


# ---------------------------------------------------------------- cross references

class Xrefs:
    def __init__(self, pages: list[Page]):
        self.pages = pages
        self.by_code = {p.code: p for p in pages if p.code}
        self.lectures: dict[int, tuple[Page, str, str]] = {}
        self.sections: dict[str, tuple[Page, str]] = {}
        for p in pages:
            for lv, hid, text in p.headings:
                m = LECTURE_RE.match(text)
                if m and int(m.group(1)) not in self.lectures:
                    self.lectures[int(m.group(1))] = (p, hid, text)
            if p.lectures:  # lecture pages: "25.3"-style section keys are global
                for key, hid in p.sections.items():
                    if "." in key:
                        self.sections.setdefault(key, (p, hid))
        self.defs: dict[str, tuple[Page, str, int, int | None]] = {}  # key -> page, anchor, tok idx, bq idx
        self.unresolved: dict[str, int] = {}

    # ---- definitions
    def find_definitions(self) -> None:
        cands: dict[str, list[tuple[int, Page, str, int, int | None]]] = {}
        for p in self.pages:
            toks = p.tokens
            lecture = 0
            for i, t in enumerate(toks):
                if t.type == "heading_open":
                    if t.meta.get("lecture"):
                        lecture = t.meta["lecture"]
                    for m in ITEM_RE.finditer(inline_text(toks[i + 1])):
                        key = f"{m.group(1)} {m.group(2)}"
                        bq = self._next_blockquote(toks, i)
                        cands.setdefault(key, []).append((lecture, p, t.meta["id"], i, bq))
                elif t.type == "blockquote_open" and t.level == 0 and toks[i + 2].type == "inline":
                    for label in line_labels(toks[i + 2]):
                        for m in ITEM_RE.finditer(label):
                            key = f"{m.group(1)} {m.group(2)}"
                            anchor = f"d-{m.group(1)}-{m.group(2)}"
                            cands.setdefault(key, []).append((lecture, p, anchor, i, i))
                elif t.type == "paragraph_open" and t.level == 0 and toks[i + 1].type == "inline":
                    # a bold-led top-level paragraph ("**练习 17-1　…**") — no preview body
                    for label in line_labels(toks[i + 1])[:1]:
                        for m in ITEM_RE.finditer(label):
                            key = f"{m.group(1)} {m.group(2)}"
                            anchor = f"d-{m.group(1)}-{m.group(2)}"
                            cands.setdefault(key, []).append((lecture, p, anchor, i, None))
        for key, lst in cands.items():
            num = int(key.split()[1].split("-")[0])

            def rank(c):  # own lecture first; then blockquote > heading > bold paragraph
                lec, p, anchor, i, bq = c
                kind = 1 if not anchor.startswith("d-") else (0 if bq == i else 2)
                return (lec != num, kind)
            lec, p, anchor, i, bq = sorted(lst, key=rank)[0]  # stable: document order among equals
            if anchor.startswith("d-"):
                t = p.tokens[i]
                if t.attrGet("id"):
                    anchor = t.attrGet("id")
                else:
                    t.attrSet("id", anchor)
                p.ids.add(anchor)
            self.defs[key] = (p, anchor, i, bq)

    @staticmethod
    def _next_blockquote(toks, i: int):
        for j in range(i + 3, min(i + 40, len(toks))):
            if toks[j].type == "heading_open":
                return None
            if toks[j].type == "blockquote_open" and toks[j].level == 0:
                return j
        return None

    # ---- linking
    def target(self, m: re.Match, page: Page) -> tuple[str, str, str] | None:
        """(href, css class, title) for one regex match, or None."""
        if m.group("item"):
            key = f"{m.group(2)} {m.group(3)}"
            d = self.defs.get(key)
            if not d:
                self.unresolved[key] = self.unresolved.get(key, 0) + 1
                return None
            p, anchor, _, _ = d
            return self._href(page, p, anchor), "xref item", key
        if m.group("lec"):
            n = int(m.group(5))
            if n not in self.lectures:
                return None
            p, hid, text = self.lectures[n]
            return self._href(page, p, hid), "xref", text
        if m.group("chap"):
            p = self.by_code.get(m.group(7))
            return (p.out, "xref", p.title) if p else None
        if m.group("sec"):
            code, key = m.group(9), m.group(10)
            if code:
                p = self.by_code.get(code)
                if p and key in p.sections:
                    return self._href(page, p, p.sections[key]), "xref", f"{p.title} §{key}"
                return None
            if key in page.sections:
                return f"#{page.sections[key]}", "xref", f"§{key}"
            if key in self.sections:
                p, hid = self.sections[key]
                return self._href(page, p, hid), "xref", f"§{key}"
        return None

    @staticmethod
    def _href(cur: Page, p: Page, anchor: str) -> str:
        return ("" if p is cur else p.out) + "#" + anchor

    def link_page(self, page: Page) -> None:
        toks = page.tokens
        in_heading, own = False, None
        for i, t in enumerate(toks):
            if t.type == "heading_open":
                in_heading = True
            elif t.type == "heading_close":
                in_heading = False
            elif t.type in ("blockquote_open", "paragraph_open") and t.level == 0:
                own = t.attrGet("id")  # a definition must not link to itself
            elif t.type in ("blockquote_close", "paragraph_close") and t.level == 0:
                own = None
            if t.type != "inline" or in_heading or not t.children:
                continue
            out, depth = [], 0
            for c in t.children:
                if c.type == "link_open":
                    depth += 1
                elif c.type == "link_close":
                    depth -= 1
                if c.type != "text" or depth or not XREF_RE.search(c.content):
                    out.append(c)
                    continue
                pos, s = 0, c.content
                for m in XREF_RE.finditer(s):
                    tgt = self.target(m, page)
                    if not tgt:
                        continue
                    href, cls, title = tgt
                    if own and href == f"#{own}":
                        continue
                    if m.start() > pos:
                        out.append(self._text(s[pos:m.start()]))
                    h = Token("html_inline", "", 0)
                    item = f' data-item="{html.escape(title)}"' if cls == "xref item" else ""
                    h.content = (f'<a class="{cls}" href="{html.escape(href)}"{item}'
                                 f' title="{html.escape(title)}">{html.escape(m.group(0))}</a>')
                    out.append(h)
                    pos = m.end()
                if pos < len(s):
                    out.append(self._text(s[pos:]))
            t.children = out

    @staticmethod
    def _text(s: str) -> Token:
        tok = Token("text", "", 0)
        tok.content = s
        return tok


# ---------------------------------------------------------------- templates

def esc(s: str) -> str:
    return html.escape(s, quote=True)


def lecture_span(p: Page) -> str:
    if not p.lectures:
        return ""
    a, b = min(p.lectures), max(p.lectures)
    return f"{a}" if a == b else f"{a}-{b}"


def nav_html(pages: list[Page], current: Page) -> str:
    out, group = [], None
    for p in pages:
        if p.group != group:
            if group is not None:
                out.append("</ul>")
            group = p.group
            if group:
                out.append(f'<p class="nav-group">{esc(group)}</p>')
            out.append("<ul>")
        label = "首页" if p.out == "index.html" else p.title
        cur = ' aria-current="page"' if p is current else ""
        lec = f' data-lectures="{",".join(map(str, p.lectures))}"' if p.lectures else ""
        out.append(f'<li><a href="{p.out}"{cur}{lec}><span class="nav-t">{esc(label)}</span></a></li>')
    out.append("</ul>")
    return "\n".join(out)


def toc_html(page: Page) -> str:
    if len(page.toc) < 2:
        return ""
    items = "\n".join(
        f'<li class="toc-l{lv}"><a href="#{esc(i)}">{esc(t)}</a></li>'
        for lv, i, t in page.toc
    )
    return (f'<nav class="toc" aria-label="本页目录"><p class="toc-title">本页目录</p>'
            f"<ul>{items}</ul></nav>")


def pager_html(pages: list[Page], i: int) -> str:
    parts = []
    if i > 0:
        p = pages[i - 1]
        parts.append(f'<a class="prev" href="{p.out}" rel="prev"><span>← 上一篇</span>{esc(p.title)}</a>')
    else:
        parts.append("<span></span>")
    if i + 1 < len(pages):
        p = pages[i + 1]
        parts.append(f'<a class="next" href="{p.out}" rel="next"><span>下一篇 →</span>{esc(p.title)}</a>')
    return f'<nav class="pager">{"".join(parts)}</nav>'


def page_header(page: Page) -> str:
    if page.out == "index.html":
        return """<section class="hero">
  <p class="hero-kicker">面向零基础成年学习者的系统教程</p>
  <h1 class="hero-title">流行钢琴<br>即兴演奏与编配</h1>
  <p class="hero-sub">5 大板块 · 20 章 · 160 讲：从音名与节奏开始，到能为任意歌曲独立编配并即兴演奏。</p>
  <div class="hero-actions">
    <a class="btn primary" href="0-1.html">从第一章开始</a>
    <a class="btn" href="0-2.html">记号与术语约定</a>
    <a class="btn resume" href="#" hidden>继续阅读</a>
  </div>
  <div class="hero-progress" hidden><div class="bar"><span></span></div><p></p></div>
</section>"""
    meta = []
    span = lecture_span(page)
    if span:
        meta.append(f"第 {span.replace('-', '–')} 讲")
    meta.append(f"约 {max(1, round(page.chars / 450))} 分钟阅读")
    prog = '<span class="page-progress" hidden></span>' if page.lectures else ""
    crumb = f'<p class="crumb">{esc(page.group)}</p>' if page.group else ""
    return f'{crumb}\n<!--H1-->\n<p class="page-meta">{" · ".join(meta)}{prog}</p>'


def place_header(page: Page, body: str) -> str:
    """Breadcrumb above the page's h1, reading metadata below it."""
    head = page_header(page)
    if page.out == "index.html" or "<!--H1-->" not in head:
        return head + "\n" + body
    before, after = head.split("<!--H1-->")
    i = body.find("</h1>")
    if i < 0:
        return before + after + body
    j = i + len("</h1>")
    return before + body[:j] + after + body[j:]


def page_html(pages: list[Page], i: int, body: str, has_abc: bool) -> str:
    page = pages[i]
    title = SITE_TITLE if page.out == "index.html" else f"{page.title} · {SITE_TITLE}"
    abc_tags = (
        f'<link rel="stylesheet" href="{ABCJS}/abcjs-audio.css">\n'
        f'<script defer src="{ABCJS}/dist/abcjs-basic-min.js"></script>\n'
        if has_abc else ""
    )
    toc = toc_html(page)
    home = " home" if page.out == "index.html" else ""
    desc = "面向零基础成年学习者的流行钢琴即兴演奏与编配系统教程，共 160 讲。"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{desc}">
<meta name="color-scheme" content="light dark">
<script>try{{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="{KATEX}/katex.min.css">
<link rel="stylesheet" href="assets/style.css">
<link rel="icon" href="assets/icon.svg" type="image/svg+xml">
<script defer src="{KATEX}/katex.min.js"></script>
{abc_tags}<script defer src="assets/site.js"></script>
</head>
<body class="{home.strip()}" data-page="{esc(page.out)}">
<div class="read-progress" aria-hidden="true"><span></span></div>
<header class="topbar">
  <button type="button" class="icon-btn menu-btn" aria-label="打开目录" aria-expanded="false">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>
  <a class="site-title" href="index.html"><span class="logo" aria-hidden="true"></span>{SITE_TITLE}</a>
  <button type="button" class="icon-btn search-btn" aria-label="搜索（快捷键 /）">
    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg></button>
  <button type="button" class="icon-btn theme-btn" aria-label="切换深浅色">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></svg></button>
</header>
<div class="layout{' has-toc' if toc else ''}">
<aside class="sidebar">
  <div class="search">
    <input type="search" id="search-input" placeholder="搜索讲次、小节、命题与规则…" autocomplete="off" aria-label="搜索">
    <ul id="search-results" hidden></ul>
  </div>
  <nav class="site-nav" aria-label="全站目录">
{nav_html(pages, page)}
  </nav>
</aside>
<main>
<article class="content{home}">
{place_header(page, body)}
</article>
{pager_html(pages, i)}
</main>
{toc}
</div>
<button type="button" class="to-top" aria-label="回到顶部" hidden>↑</button>
<div class="popover" role="tooltip" hidden></div>
</body>
</html>
"""


# ---------------------------------------------------------------- build

def preview_html(md: MarkdownIt, p: Page, bq: int | None) -> str:
    if bq is None:
        return ""
    toks = p.tokens
    end = block_end(toks, bq)
    inner = toks[bq + 1:end]
    # Keep previews short: the first three top-level blocks of the callout, or just
    # the first one when those are long (tables, worked examples).
    def first_blocks(limit: int):
        keep, n = [], 0
        for t in inner:
            if t.level == 1 and t.nesting in (0, 1) and t.type not in ("inline",):
                n += 1
                if n > limit:
                    break
            keep.append(t)
        return md.renderer.render(keep, md.options, p.env).strip()
    out = first_blocks(3)
    if len(out) > 2500:
        out = first_blocks(1)
    return out if len(out) <= 6000 else ""


def main() -> int:
    pages = collect_pages()
    by_src = {p.src.resolve(): p for p in pages}
    md = make_md()
    problems: list[str] = []

    for p in pages:
        p.env = {}
        # utf-8-sig: some sources begin with a BOM, which would stop "# title" parsing as a heading
        p.tokens = md.parse(p.src.read_text(encoding="utf-8-sig"), p.env)
        if p.tokens and p.tokens[0].type == "heading_open" and p.tokens[0].tag != "h1":
            problems.append(f"{p.src.name}: first heading is not h1")
        assign_ids(p)
        classify_callouts(p)
    problems += [f"{p.src.name}: no h1 title" for p in pages if not p.title]

    xr = Xrefs(pages)
    xr.find_definitions()
    for p in pages:
        xr.link_page(p)

    for p in pages:
        def resolve(href: str, p=p) -> str:
            if re.match(r"^[a-z]+:", href) or not href:
                return href
            path, _, frag = href.partition("#")
            target = p
            if path:
                tgt = (p.src.parent / unquote(path)).resolve()
                target = by_src.get(tgt)
                if target is None:
                    problems.append(f"{p.src.name}: link to missing page {href}")
                    return href
            if frag and unquote(frag) not in target.ids:
                problems.append(f"{p.src.name}: missing anchor {href}")
            new = "" if target is p else target.out
            return new + (f"#{frag}" if frag else "")
        p.env["resolve_link"] = resolve

    # Empty docs/ rather than deleting it, so a local preview server rooted there keeps working.
    OUT.mkdir(exist_ok=True)
    for child in OUT.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (OUT / "assets").mkdir()

    defs = {}
    for key, (p, anchor, i, bq) in xr.defs.items():
        defs[key] = {"u": f"{p.out}#{anchor}", "p": p.title, "h": preview_html(md, p, bq)}

    search = []
    for i, p in enumerate(pages):
        body = md.renderer.render(p.tokens, md.options, p.env)
        has_abc = p.env.get("abc_count", 0) > 0
        (OUT / p.out).write_text(page_html(pages, i, body, has_abc), encoding="utf-8")
        for lv, hid, text in p.headings:
            search.append({"t": text, "u": f"{p.out}#{hid}", "p": p.title, "l": lv})
    for key, (p, anchor, i, bq) in xr.defs.items():
        label = first_label(p.tokens, bq) if bq is not None else key
        search.append({"t": label if key in label else f"{key}　{label}", "u": f"{p.out}#{anchor}",
                       "p": p.title, "l": 5})

    def write_js(name: str, var: str, data) -> None:
        (OUT / "assets" / name).write_text(
            f"window.{var}=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";",
            encoding="utf-8",
        )
    write_js("search-index.js", "SEARCH_INDEX", search)
    write_js("defs.js", "DEFS", defs)
    for a in ASSETS.iterdir():
        shutil.copy2(a, OUT / "assets" / a.name)
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    print(f"built {len(pages)} pages, {len(search)} search entries, {len(defs)} linked definitions -> {OUT}")
    if xr.unresolved:
        print(f"INFO {len(xr.unresolved)} cited items have no recognisable definition (left unlinked): "
              + ", ".join(sorted(xr.unresolved)))
    for msg in problems:
        print("WARN", msg)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
