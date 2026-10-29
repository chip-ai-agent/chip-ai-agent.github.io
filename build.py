#!/usr/bin/env python3
"""Build the bilingual site from content/ (needs: pip install markdown).

    python3 build.py

Layout
    content/site.json                 site name, nav labels and home-page text, per language
    content/posts/<slug>/meta.json    date, tags, summary per language; "draft": true skips the post
    content/posts/<slug>/en.md        English body (first "# " line is the title)
    content/posts/<slug>/zh.md        Chinese body

Output (regenerated on every build; do not edit by hand)
    index.html, research/<slug>/index.html            English
    zh/index.html, zh/research/<slug>/index.html      Chinese
"""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
LANGS = ("en", "zh")
PREFIX = {"en": "", "zh": "zh/"}  # URL prefix of each language, relative to the site root


LOGO = (
    '<svg class="brand-mark" viewBox="0 0 240 240" aria-hidden="true">'
    '<g stroke="currentColor" stroke-width="12" stroke-linecap="round" fill="none">'
    '<rect x="56" y="56" width="128" height="128" rx="26" stroke-width="14"/>'
    '<path d="M94 56V26M146 56V26M94 184v30M146 184v30M56 94H26M56 146H26M184 94h30M184 146h30"/>'
    '</g>'
    '<rect x="92" y="98" width="18" height="44" rx="9" fill="var(--logo-accent)"/>'
    '<rect x="130" y="98" width="18" height="44" rx="9" fill="var(--logo-accent)"/>'
    '</svg>'
)


def rel(depth: int) -> str:
    """Relative path from a page `depth` directories deep back to the site root."""
    return "../" * depth or "./"


def page(site: dict, lang: str, depth: int, other_url: str, title: str, desc: str, body: str) -> str:
    t, root = site[lang], rel(depth)
    home = root + PREFIX[lang]
    return f"""<!doctype html>
<html lang="{t['html_lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="icon" href="{root}assets/logo.svg">
<link rel="stylesheet" href="{root}assets/style.css">
</head>
<body>
<header class="topbar"><div class="wrap">
  <a class="brand" href="{home}">{LOGO}{site['name']}</a>
  <nav class="nav">
    <a href="{home}#research">{t['nav_research']}</a>
    <a href="{home}#about">{t['nav_about']}</a>
    <a href="{site['github']}">GitHub</a>
    <a class="lang" href="{other_url}">{t['switch_label']}</a>
  </nav>
</div></header>
{body}
<footer><div class="wrap">© {site['year']} {site['name']}</div></footer>
</body>
</html>
"""


def load_posts() -> list[dict]:
    posts = []
    for d in sorted((CONTENT / "posts").iterdir()):
        meta_file = d / "meta.json"
        if not d.is_dir() or not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text())
        if meta.get("draft"):
            continue
        post = {"slug": d.name, "date": meta["date"], "tags": meta.get("tags", {}), "summary": meta.get("summary", {})}
        for lang in LANGS:
            src = (d / f"{lang}.md").read_text()
            m = re.match(r"#\s+(.+)\n", src)
            post[lang] = {"title": m.group(1).strip() if m else d.name, "body": src[m.end():] if m else src}
        posts.append(post)
    return sorted(posts, key=lambda p: p["date"], reverse=True)


def build_home(site: dict, posts: list[dict], lang: str) -> None:
    t = site[lang]
    depth = 1 if lang == "zh" else 0
    other = rel(depth) + PREFIX["zh" if lang == "en" else "en"]
    if posts:
        items = []
        for p in posts:
            tags = "".join(f"<span>{html.escape(x)}</span>" for x in p["tags"].get(lang, []))
            items.append(
                f'<li><a href="research/{p["slug"]}/"><span class="post-date">{p["date"][:7].replace("-", ".")}</span>'
                f'<span class="post-body"><span class="post-title">{html.escape(p[lang]["title"])}</span>'
                f'<span class="post-desc">{html.escape(p["summary"].get(lang, ""))}</span>'
                f'<span class="post-tags">{tags}</span></span></a></li>')
        research = '<ul class="posts">' + "".join(items) + "</ul>"
    else:
        research = f'<p class="empty">{t["research_empty"]}</p>'
    body = f"""<main class="wrap">
  <div class="hero home">
    <h1>{t['title']}</h1>
    <p class="lead">{t['intro']}</p>
  </div>
  <section id="research">
    <h2 class="section-title">{t['research_heading']}</h2>
    {research}
  </section>
  <section id="about">
    <h2 class="section-title">{t['about_heading']}</h2>
    <p class="about">{t['about']}</p>
  </section>
</main>"""
    out = ROOT / PREFIX[lang] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(site, lang, depth, other, f"{site['name']} · {t['title']}", t["intro"], body))


def build_post(site: dict, post: dict, lang: str) -> None:
    t = site[lang]
    depth = 3 if lang == "zh" else 2
    other_lang = "zh" if lang == "en" else "en"
    other = rel(depth) + PREFIX[other_lang] + f"research/{post['slug']}/"
    content = markdown.markdown(post[lang]["body"], extensions=["tables", "fenced_code", "toc"])
    content = content.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")
    tags = "".join(f"<span>{html.escape(x)}</span>" for x in post["tags"].get(lang, []))
    body = f"""<main class="wrap doc">
  <p class="back"><a href="{rel(depth)}{PREFIX[lang]}#research">{t['back']}</a></p>
  <h1>{html.escape(post[lang]['title'])}</h1>
  <p class="meta">{post['date']}</p>
  <div class="post-tags">{tags}</div>
  {content}
</main>"""
    out = ROOT / PREFIX[lang] / "research" / post["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(site, lang, depth, other, f"{post[lang]['title']} · {site['name']}",
                        post["summary"].get(lang, ""), body))


def main() -> None:
    site = json.loads((CONTENT / "site.json").read_text())
    for generated in (ROOT / "research", ROOT / "zh"):
        shutil.rmtree(generated, ignore_errors=True)
    posts = load_posts()
    for lang in LANGS:
        build_home(site, posts, lang)
        for post in posts:
            build_post(site, post, lang)
    print(f"built {len(LANGS)} languages, {len(posts)} published post(s)")


if __name__ == "__main__":
    main()
