# -*- coding: utf-8 -*-
"""
1.29: разбор HTML так, как его видит браузер, и адреса сборок генераторов.

Мета-переадресация в `srcdoc`, canonical после тега, закрывшего <head>,
`<script … />`, декларативный теневой корень, <svg> в <head>, `<![CDATA[`
вне SVG, JSON-LD в <template>, <pre> в комментарии. И адреса: `_index.md`
Hugo, `_posts` и служебные каталоги Jekyll, `permalink`/`url`/`slug`,
маршруты `.next/server`, `[slug].html`, коды ответа в разделе.
"""

import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, content, core, install

SITE = "https://demo.example"
FILLER = " ".join(f"word{i} sentence about renting flats here." for i in range(120))


class Tree:
    def __init__(self, case, prefix="indexgap-129-"):
        self.root = tempfile.mkdtemp(prefix=prefix)
        case.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path


def html(head="", body="", title="Renting flats in the demo city"):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{title}</title>{head}</head><body>{body}</body></html>')


MAIN = f"<main><h1>Renting flats</h1><p>{FILLER}</p><a href=\"/other/\">Other</a></main>"


class Parsing(unittest.TestCase):
    def load(self, text, rel="page/index.html"):
        tree = Tree(self)
        path = tree.write(rel, text)
        return core.load_page(path, tree.root, SITE)

    def test_meta_refresh_inside_srcdoc_is_not_a_redirect(self):
        frame = ("<iframe title=\"preview\" srcdoc=\"<meta http-equiv='refresh' "
                 "content='0;url=/about/'><p>demo</p>\"></iframe>")
        for pad in ("", FILLER * 3):
            page = self.load(html(body=MAIN + frame + pad))
            self.assertEqual(checks.redirect_target(page), "")
        live = self.load(html(head='<meta http-equiv="refresh" content="0;url=/about/">'))
        self.assertEqual(checks.redirect_target(live), SITE + "/about/")

    def test_canonical_after_head_end_is_ignored_and_named(self):
        page = self.load(html(head='<img src="/p.gif" alt="">'
                                   f'<link rel="canonical" href="{SITE}/other/">', body=MAIN))
        self.assertEqual(page.canonical, "")
        self.assertTrue(any("canonical" in n and "<body>" in n for n in page.notes))
        page = self.load(html(head=f'<link rel="canonical" href="{SITE}/other/">', body=MAIN))
        self.assertEqual(page.canonical, SITE + "/other/")
        self.assertEqual(page.notes, [])

    def test_self_closed_raw_text_elements_swallow_the_page(self):
        for head, body in (('<script src="/app.js" />', MAIN),
                           ("", '<iframe src="https://demo.example/map" />' + MAIN)):
            page = self.load(html(head=head, body=body))
            self.assertEqual(page.text.strip(), "", head + body)
            self.assertEqual(page.links, [])
        # Закрывающий тег дальше по странице возвращает разметку.
        page = self.load(html(head='<script src="/app.js" /><script>x()</script>', body=MAIN))
        self.assertIn("word5", page.text)
        page = self.load(html(head='<script src="/app.js"></script>', body=MAIN))
        self.assertIn("word5", page.text)
        # Внутри SVG слеш закрывает элемент, как и положено.
        page = self.load(html(body='<svg><script href="/x.js"/></svg>' + MAIN))
        self.assertIn("word5", page.text)

    def test_declarative_shadow_root_is_content(self):
        page = self.load(html(body='<city-guide><template shadowrootmode="open">'
                                   + MAIN + "</template></city-guide>"))
        self.assertIn("word5", page.text)
        self.assertIn((1, "Renting flats"), page.headings)
        self.assertTrue(any(link.endswith("/other/") for link in page.links))
        page = self.load(html(body='<template id="t">' + MAIN + "</template><p>Short.</p>"))
        self.assertNotIn("word5", page.text)
        self.assertEqual(page.headings, [])

    def test_svg_in_head_ends_head(self):
        head = ('<svg style="display:none"><symbol id="i"><path d="M0"/></symbol></svg>'
                f'<link rel="alternate" hreflang="de" href="{SITE}/de/">')
        page = self.load(html(head=head, body=MAIN))
        self.assertEqual(page.alternates_in_body, 1)
        page = self.load(html(head=f'<link rel="alternate" hreflang="de" href="{SITE}/de/">',
                              body=MAIN))
        self.assertEqual(page.alternates_in_body, 0)

    def test_cdata_outside_svg_does_not_hide_robots(self):
        page = self.load(html(head='<![CDATA[ build 42 > <meta name="robots" '
                                   'content="noindex"> ]]>', body=MAIN))
        self.assertIn("noindex", page.robots)

    def test_jsonld_in_inert_blocks_is_not_read(self):
        ld = ('<script type="application/ld+json">{"@context":"https://schema.org",'
              '"@type":"Place","name":"{{city}}"}</script>')
        for wrap in ('<template id="card">{}</template>', "<noscript>{}</noscript>"):
            page = self.load(html(body=MAIN + wrap.format(ld)))
            self.assertEqual(page.jsonld, [], wrap)
            self.assertIn("word5", page.text)
        page = self.load(html(head=ld, body=MAIN))
        self.assertEqual(len(page.jsonld), 1)

    def test_code_only_in_comment_or_script_is_not_a_docs_page(self):
        for extra in ('<!-- old layout: <pre class="debug"></pre> -->',
                      "<script>e.innerHTML='<code>'+e.textContent+'</code>'</script>"):
            for pad in ("", FILLER * 3):
                page = self.load(html(body=MAIN + extra + pad))
                self.assertFalse(content._docs_page(page), extra)
        page = self.load(html(body=MAIN + "<pre>ls -la</pre>" + FILLER * 3))
        self.assertTrue(content._docs_page(page))


class SourceUrls(unittest.TestCase):
    def urls(self, root, site=SITE):
        pages, _ = core.load_pages(root, site)
        return {os.path.relpath(p.path, root).replace(os.sep, "/"): p.url for p in pages}

    def test_hugo_index_is_the_section_page(self):
        tree = Tree(self)
        tree.write("_index.md", "---\ntitle: Home of the demo\n---\n# Home\n\n[Posts](/posts/)\n")
        tree.write("posts/_index.md", "---\ntitle: Posts\n---\n# Posts\n\n[A](/posts/a/)\n")
        tree.write("posts/a.md", "---\ntitle: A post\n---\n# A\n\nText.\n")
        urls = self.urls(tree.root)
        self.assertEqual(urls["_index.md"], SITE + "/")
        self.assertEqual(urls["posts/_index.md"], SITE + "/posts/")
        self.assertEqual(urls["posts/a.md"], SITE + "/posts/a/")

    def test_front_matter_url_slug_and_permalink(self):
        tree = Tree(self)
        tree.write("index.md", "---\ntitle: Home\n---\n# Home\n")
        tree.write("posts/special.md", "---\ntitle: Special\nurl: /special/\n---\n# S\n")
        tree.write("posts/gamma.md", "---\ntitle: Gamma\nslug: gamma-renamed\n---\n# G\n")
        tree.write("posts/link.md", "---\ntitle: Link\nurl: https://other.example/x\n---\n# L\n")
        tree.write("about.md", "---\ntitle: About\npermalink: /company/\n---\n# A\n")
        urls = self.urls(tree.root)
        self.assertEqual(urls["posts/special.md"], SITE + "/special/")
        self.assertEqual(urls["posts/gamma.md"], SITE + "/posts/gamma-renamed/")
        self.assertEqual(urls["posts/link.md"], SITE + "/posts/link/")
        self.assertEqual(urls["about.md"], SITE + "/company/")
        self.assertEqual(urls["index.md"], SITE + "/")

    def test_jekyll_private_dirs_and_posts(self):
        tree = Tree(self)
        tree.write("_config.yml", "title: x\n")
        tree.write("index.md", "---\ntitle: Home\n---\n# Home\n")
        tree.write("_layouts/default.html",
                   "<!DOCTYPE html><html><head><title>{{ page.title }}</title></head>"
                   "<body>{{ content }}</body></html>")
        tree.write("_drafts/secret.md", "---\ntitle: Draft\n---\n# Draft\n")
        tree.write("_posts/2024-01-05-hello.md", "---\ntitle: Hello\n---\n# Hello\n")
        tree.write("_posts/2024-02-01-cats.md",
                   "---\ntitle: Cats\ncategories:\n  - Pets\n  - news\n---\n# Cats\n")
        tree.write("_posts/2024-03-01-slugged.md",
                   "---\ntitle: S\nslug: renamed\n---\n# S\n")
        tree.write("_posts/2024-04-01-fixed.md",
                   "---\ntitle: F\npermalink: /fixed/\n---\n# F\n")
        urls = self.urls(tree.root)
        self.assertEqual(sorted(urls), ["_posts/2024-01-05-hello.md", "_posts/2024-02-01-cats.md",
                                        "_posts/2024-03-01-slugged.md",
                                        "_posts/2024-04-01-fixed.md", "index.md"])
        self.assertEqual(urls["_posts/2024-01-05-hello.md"], SITE + "/2024/01/05/hello.html")
        self.assertEqual(urls["_posts/2024-02-01-cats.md"],
                         SITE + "/pets/news/2024/02/01/cats.html")
        self.assertEqual(urls["_posts/2024-03-01-slugged.md"], SITE + "/2024/03/01/renamed.html")
        self.assertEqual(urls["_posts/2024-04-01-fixed.md"], SITE + "/fixed/")
        tree.write("_config.yml", "title: x\npermalink: pretty\ncollections:\n  recipes:\n"
                                  "    output: true\n")
        tree.write("_recipes/soup.md", "---\ntitle: Soup\n---\n# Soup\n")
        urls = self.urls(tree.root)
        self.assertEqual(urls["_posts/2024-01-05-hello.md"], SITE + "/2024/01/05/hello/")
        self.assertIn("_recipes/soup.md", urls)

    def test_readme_is_home_without_config(self):
        tree = Tree(self)
        tree.write("README.md", "# Docs\n\nRead the [guide](guide/install.md).\n")
        tree.write("guide/install.md", "# Install\n\nBack [home](../README.md).\n")
        self.assertEqual(self.urls(tree.root)["README.md"], SITE + "/")
        tree.write("package.json", "{}")
        self.assertNotEqual(self.urls(tree.root)["README.md"], SITE + "/")


class Builds(unittest.TestCase):
    def urls(self, root):
        pages, _ = core.load_pages(root, SITE)
        return {os.path.relpath(p.path, root).replace(os.sep, "/"): p.url for p in pages}

    def test_next_server_unlinked_pages_are_routes(self):
        tree = Tree(self)
        app = os.path.join(tree.root, ".next", "server", "app")
        for rel, body in (("index.html", '<a href="/about">About</a>' + MAIN),
                          ("about.html", MAIN), ("pricing.html", MAIN),
                          ("legal/terms.html", MAIN)):
            tree.write(".next/server/app/" + rel, html(body=body))
        urls = self.urls(app)
        self.assertEqual(urls["pricing.html"], SITE + "/pricing")
        self.assertEqual(urls["legal/terms.html"], SITE + "/legal/terms")
        self.assertEqual(urls["about.html"], SITE + "/about")

    def test_flat_static_unlinked_page_keeps_file_form(self):
        tree = Tree(self)
        tree.write("index.html", html(body=MAIN))
        tree.write("pricing.html", html(body=MAIN))
        self.assertEqual(self.urls(tree.root)["pricing.html"], SITE + "/pricing.html")

    def test_dynamic_route_shell_is_not_a_page(self):
        tree = Tree(self)
        tree.write("index.html", html(body=MAIN))
        tree.write("blog/[slug].html", html(body='<div id="__next"></div>'))
        tree.write("docs/[...path].html", html(body='<div id="__next"></div>'))
        self.assertEqual(sorted(self.urls(tree.root)), ["index.html"])

    def test_next_default_locale_has_no_prefix(self):
        tree = Tree(self)
        tree.write(".next/routes-manifest.json",
                   json.dumps({"i18n": {"locales": ["en", "fr"], "defaultLocale": "en"}}))
        for rel in ("en.html", "en/about.html", "fr.html", "fr/about.html"):
            tree.write(".next/server/pages/" + rel, html(body=MAIN))
        urls = self.urls(os.path.join(tree.root, ".next", "server", "pages"))
        self.assertEqual(urls["en.html"], SITE + "/")
        self.assertEqual(urls["en/about.html"], SITE + "/about")
        self.assertEqual(urls["fr.html"], SITE + "/fr")
        self.assertEqual(urls["fr/about.html"], SITE + "/fr/about")

    def test_status_pages_in_short_section_follow_links(self):
        tree = Tree(self)
        tree.write("index.html", html(body='<a href="/api/404/">404</a>' + MAIN))
        tree.write("api/404/index.html", html(body=MAIN))
        tree.write("api/500/index.html", html(body=MAIN))
        tree.write("404.html", html(body=MAIN))
        tree.write("en/404.html", html(body=MAIN))
        self.assertEqual(sorted(self.urls(tree.root)), ["api/404/index.html", "index.html"])

    def test_git_alone_does_not_hide_canonical_form(self):
        tree = Tree(self)
        os.makedirs(os.path.join(tree.root, ".git"))
        self.assertEqual(core._host_serves_any_form(tree.root)[0], False)
        tree.write("package.json", "{}")
        self.assertEqual(core._host_serves_any_form(tree.root)[0], True)

    def test_detects_nuxt_vitepress_and_astro_server_builds(self):
        for build, sources in ((".output/public", None), ("docs/.vitepress/dist", "docs"),
                               ("dist/client", None)):
            tree = Tree(self)
            if sources:
                for name in ("index.md", "a.md", "b.md"):
                    tree.write(f"{sources}/{name}", "# Page\n")
            for name in ("index.html", "a/index.html", "b/index.html"):
                tree.write(f"{build}/{name}", html(body=MAIN))
            if build == "dist/client":
                tree.write("dist/server/entry.mjs", "export {}")
            self.assertEqual(install.detect_content_dir(tree.root),
                             os.path.join(".", *build.split("/")))


if __name__ == "__main__":
    unittest.main()
