"""Build the static HTML site (docs/) from the Markdown tutorial (tutorial/).

Usage:  py -X utf8 tools/build_site.py
Requires: markdown-it-py, mdit-py-plugins  (pip install markdown-it-py mdit-py-plugins)

The Markdown sources are never modified.  The output directory docs/ is
regenerated from scratch on every run and is what GitHub Pages serves.
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
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "tutorial"
OUT = ROOT / "docs"
ASSETS = pathlib.Path(__file__).resolve().parent / "site_assets"

SITE_TITLE = "流行钢琴即兴演奏与编配"
KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.22/dist"
ABCJS = "https://cdn.jsdelivr.net/npm/abcjs@6.5.1"
CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}


# ---------------------------------------------------------------- pages

class Page:
    def __init__(self, src: pathlib.Path):
        self.src = src
        self.out = out_name(src)
        self.group = group_label(src)
        self.title = ""
        self.tokens = None
        self.env: dict = {}
        self.ids: set[str] = set()
        self.toc: list[tuple[int, str, str]] = []
        self.headings: list[tuple[int, str, str]] = []


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
    # Keep letters, marks, decimal digits, connector punctuation, '-' and ' ' (as github-slugger
    # does); everything else, including circled numbers such as ①, is dropped.
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
    md = MarkdownIt("commonmark", {"html": True, "typographer": False})
    md.enable(["table", "strikethrough"])
    md.use(dollarmath_plugin, allow_space=True, allow_digits=True, double_inline=True)
    md.use(tasklists_plugin, enabled=True)

    def heading_open(self, tokens, idx, options, env):
        t = tokens[idx]
        return f'<{t.tag} id="{html.escape(t.meta["id"])}">'

    def heading_close(self, tokens, idx, options, env):
        t = tokens[idx]
        hid = html.escape(t.meta["id"])
        return f'<a class="anchor" href="#{hid}" aria-label="本节链接">#</a></{t.tag}>\n'

    def table_open(self, tokens, idx, options, env):
        return '<div class="table-wrap"><table>\n'

    def table_close(self, tokens, idx, options, env):
        return "</table></div>\n"

    def fence(self, tokens, idx, options, env):
        t = tokens[idx]
        lang = (t.info or "").strip().split(" ")[0]
        code = html.escape(t.content)
        if lang == "abc":
            env["abc_count"] = env.get("abc_count", 0) + 1
            return (
                '<figure class="abc-block">'
                '<div class="abc-render" aria-label="五线谱"></div>'
                '<div class="abc-controls"><button type="button" class="abc-play">▶ 播放</button>'
                '<div class="abc-audio"></div></div>'
                f'<details class="abc-source"><summary>ABC 源码</summary><pre><code>{code}</code></pre></details>'
                "</figure>\n"
            )
        cls = f' class="language-{html.escape(lang)}"' if lang else ""
        return f"<pre><code{cls}>{code}</code></pre>\n"

    def link_open(self, tokens, idx, options, env):
        t = tokens[idx]
        href = t.attrGet("href") or ""
        t.attrSet("href", env["resolve_link"](href))
        return self.renderToken(tokens, idx, options, env)

    md.add_render_rule("heading_open", heading_open)
    md.add_render_rule("heading_close", heading_close)
    md.add_render_rule("table_open", table_open)
    md.add_render_rule("table_close", table_close)
    md.add_render_rule("fence", fence)
    md.add_render_rule("link_open", link_open)
    return md


def assign_ids(page: Page) -> None:
    counts: dict[str, int] = {}
    toks = page.tokens
    for i, t in enumerate(toks):
        if t.type != "heading_open":
            continue
        text = inline_text(toks[i + 1])
        base = gh_slug(text) or "section"
        n = counts.get(base, 0)
        hid = base if n == 0 else f"{base}-{n}"
        counts[base] = n + 1
        t.meta["id"] = hid
        toks[i + 2].meta["id"] = hid  # heading_close
        page.ids.add(hid)
        level = int(t.tag[1])
        if level == 1 and not page.title:
            page.title = text.strip()
        if level in (2, 3):
            page.toc.append((level, hid, text.strip()))
        if level in (2, 3, 4):
            page.headings.append((level, hid, text.strip()))


# ---------------------------------------------------------------- templates

def nav_html(pages: list[Page], current: Page) -> str:
    out, group = [], None
    for p in pages:
        if p.group != group:
            if group is not None:
                out.append("</ul>")
            group = p.group
            if group:
                out.append(f'<p class="nav-group">{html.escape(group)}</p>')
            out.append("<ul>")
        label = "首页" if p.out == "index.html" else p.title
        cur = ' aria-current="page"' if p is current else ""
        out.append(f'<li><a href="{p.out}"{cur}>{html.escape(label)}</a></li>')
    out.append("</ul>")
    return "\n".join(out)


def toc_html(page: Page) -> str:
    if len(page.toc) < 2:
        return ""
    items = "\n".join(
        f'<li class="toc-l{lv}"><a href="#{html.escape(i)}">{html.escape(t)}</a></li>'
        for lv, i, t in page.toc
    )
    return f'<nav class="toc" aria-label="本页目录"><p class="toc-title">本页目录</p><ul>{items}</ul></nav>'


def pager_html(pages: list[Page], i: int) -> str:
    parts = []
    if i > 0:
        p = pages[i - 1]
        parts.append(f'<a class="prev" href="{p.out}"><span>上一篇</span>{html.escape(p.title)}</a>')
    else:
        parts.append("<span></span>")
    if i + 1 < len(pages):
        p = pages[i + 1]
        parts.append(f'<a class="next" href="{p.out}"><span>下一篇</span>{html.escape(p.title)}</a>')
    return f'<nav class="pager">{"".join(parts)}</nav>'


def page_html(pages: list[Page], i: int, body: str, has_abc: bool) -> str:
    page = pages[i]
    title = SITE_TITLE if page.out == "index.html" else f"{page.title} · {SITE_TITLE}"
    abc_tags = (
        f'<link rel="stylesheet" href="{ABCJS}/abcjs-audio.css">\n'
        f'<script defer src="{ABCJS}/dist/abcjs-basic-min.js"></script>\n'
        if has_abc else ""
    )
    toc = toc_html(page)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<script>try{{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
<link rel="stylesheet" href="{KATEX}/katex.min.css">
<link rel="stylesheet" href="assets/style.css">
<script defer src="{KATEX}/katex.min.js"></script>
{abc_tags}<script defer src="assets/site.js"></script>
</head>
<body>
<header class="topbar">
  <button type="button" class="menu-btn" aria-label="打开目录" aria-expanded="false">☰</button>
  <a class="site-title" href="index.html">{SITE_TITLE}</a>
  <button type="button" class="theme-btn" aria-label="切换深浅色">◐</button>
</header>
<div class="layout{' has-toc' if toc else ''}">
<aside class="sidebar">
  <div class="search">
    <input type="search" id="search-input" placeholder="搜索讲次与小节标题…" autocomplete="off" aria-label="搜索">
    <ul id="search-results" hidden></ul>
  </div>
  <nav class="site-nav" aria-label="全站目录">
{nav_html(pages, page)}
  </nav>
</aside>
<main>
<article class="content">
{body}
</article>
{pager_html(pages, i)}
</main>
{toc}
</div>
</body>
</html>
"""


# ---------------------------------------------------------------- build

def main() -> int:
    pages = collect_pages()
    by_src = {p.src.resolve(): p for p in pages}
    md = make_md()
    problems_pre: list[str] = []

    for p in pages:
        p.env = {}
        # utf-8-sig: some sources begin with a BOM, which would stop "# title" parsing as a heading
        p.tokens = md.parse(p.src.read_text(encoding="utf-8-sig"), p.env)
        if p.tokens and p.tokens[0].type == "heading_open" and p.tokens[0].tag != "h1":
            problems_pre.append(f"{p.src.name}: first heading is not h1")
        assign_ids(p)

    problems: list[str] = problems_pre + [f"{p.src.name}: no h1 title" for p in pages if not p.title]
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)

    search = []
    for i, p in enumerate(pages):
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
        body = md.renderer.render(p.tokens, md.options, p.env)
        has_abc = p.env.get("abc_count", 0) > 0
        (OUT / p.out).write_text(page_html(pages, i, body, has_abc), encoding="utf-8")
        for lv, hid, text in p.headings:
            search.append({"t": text, "u": f"{p.out}#{hid}", "p": p.title, "l": lv})

    (OUT / "assets" / "search-index.js").write_text(
        "window.SEARCH_INDEX=" + json.dumps(search, ensure_ascii=False, separators=(",", ":")) + ";",
        encoding="utf-8",
    )
    for a in ASSETS.iterdir():
        shutil.copy2(a, OUT / "assets" / a.name)
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    print(f"built {len(pages)} pages, {len(search)} indexed headings -> {OUT}")
    for msg in problems:
        print("WARN", msg)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
