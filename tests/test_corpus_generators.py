# -*- coding: utf-8 -*-
"""
Второй прогон по чужим сайтам: двенадцать сборок на генераторах, которых
пакет ещё не видел — Hugo, Docusaurus с i18n, VitePress, Hexo, Pelican,
Gatsby, Nuxt, Eleventy, pkgdown, Docsify, Next.js.

Около пятнадцати тысяч находок, в основном критичных, давали шесть причин.
Каждая повторилась бы на любом сайте того же генератора:

* hreflang и содержимое оценивались на страницах, которых в индексе не будет:
  печатные копии Hugo (`index.print.html`, canonical на основную), старые
  версии документации Docusaurus (noindex);
* одно решение закрыть страницу давало две критичные находки — noindex и
  canonical-elsewhere, — а закрытый раздел из четырёх тысяч страниц давал
  восемь тысяч;
* `index.source.md` рядом с каждой страницей Hugo считался страницей;
* одна кривая ссылка `https://x.org][1` роняла прогон на 47 тысяч страниц;
* плоский `filter.html` без canonical попадал в отчёт и sitemap как
  `/filter/` — на GitHub Pages это 404;
* `same-opening` срабатывал на баннере и меню сайта без `<main>`.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, content, core, hreflang, publish

SITE = "https://ex.com"
WORDS = ("Regional guides explain how the service works in each city, what it costs, "
         "which documents are needed, how long processing takes and where to apply.")


def text(n):
    return " ".join(f"{WORDS} Section {n} part {i}." for i in range(6))


class Site(unittest.TestCase):
    def build(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-gen-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, body in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
        self.root = root
        pages, self.problems = core.load_pages(root, SITE)[:2]
        return pages

    def issues(self, pages):
        return checks.run_all(pages, SITE + "/")["issues"]

    def on(self, issues, url, code=None):
        return [i for i in issues if i[1] == SITE + url and (code is None or i[2] == code)]


def page(title, body, head="", lang="en", main=True):
    inner = f"<main>{body}</main>" if main else body
    return (f"<!doctype html><html lang=\"{lang}\"><head><title>{title}</title>"
            f"<meta name=\"description\" content=\"{title} — a regional guide\">{head}</head>"
            f"<body>{inner}</body></html>")


def alternates(path):
    return "".join(f'<link rel="alternate" hreflang="{code}" href="{SITE}/{code}/{path}">'
                   for code in ("en", "fr"))


class PrintCopies(Site):
    """Hugo: печатная копия с canonical на основную страницу и тем же hreflang."""

    def site(self):
        files = {"index.html": page("Home of the guides", f"<h1>Home</h1><p>{text(0)}</p>"
                                    '<a href="/en/a/">en</a> <a href="/fr/a/">fr</a>')}
        for code in ("en", "fr"):
            files[f"{code}/a/index.html"] = page(
                f"Guide A in {code} for every city", f"<h1>A</h1><p>{text(code)}</p>"
                f'<a href="/{code}/a/index.print.html">print</a> <a href="/">home</a>',
                head=f'<link rel="canonical" href="{SITE}/{code}/a/">' + alternates("a/"),
                lang=code)
            files[f"{code}/a/index.print.html"] = page(
                f"Guide A print {code}", "<h1>A</h1><p>short</p>",
                head=f'<link rel="canonical" href="{SITE}/{code}/a/">' + alternates("a/"),
                lang=code)
        return self.build(files)

    def test_no_hreflang_findings_on_a_canonicalised_copy(self):
        issues = self.issues(self.site())
        for code in ("en", "fr"):
            found = [i[2] for i in self.on(issues, f"/{code}/a/index.print/")
                     if i[2].startswith("hreflang-")]
            self.assertEqual(found, [], code)

    def test_no_content_findings_on_a_canonicalised_copy(self):
        issues = checks.drop_closed_noise(self.issues(self.site()), self.site())
        codes = {i[2] for i in self.on(issues, "/en/a/index.print/")}
        self.assertFalse(codes & {"thin", "no-answer", "title-short", "deep"}, codes)

    def test_the_copy_is_consolidation_not_an_alarm(self):
        found = self.on(self.issues(self.site()), "/en/a/index.print/", "canonical-elsewhere")
        self.assertEqual([i[0] for i in found], ["info"])

    def test_a_translation_canonicalised_to_another_language_stays_critical(self):
        # apisix: /zh/comparisons/ → /comparisons/. Перевод выпадает из индекса.
        pages = self.build({
            "index.html": page("Home of the guides", f"<h1>Home</h1><p>{text(0)}</p>"
                               '<a href="/zh/c/">zh</a> <a href="/c/">en</a>'),
            "c/index.html": page("Comparison of the gateways", f"<h1>C</h1><p>{text(1)}</p>"),
            "zh/c/index.html": page("网关对比", f"<h1>C</h1><p>{text(2)}</p>", lang="zh",
                                    head=f'<link rel="canonical" href="{SITE}/c/">'),
        })
        found = self.on(self.issues(pages), "/zh/c/", "canonical-elsewhere")
        self.assertEqual([i[0] for i in found], ["critical"])


class ClosedSections(Site):
    def site(self, closed=25, open_=10):
        files = {"index.html": page("Home of the docs", f"<h1>Home</h1><p>{text(0)}</p>"
                                    + "".join(f'<a href="/docs/v1/p{n}/">v1 {n}</a> '
                                              f'<a href="/docs/p{n}/">p{n}</a> '
                                              for n in range(max(closed, open_))))}
        for n in range(closed):
            files[f"docs/v1/p{n}/index.html"] = page(
                f"Old version page {n} of the docs", f"<h1>P{n}</h1><p>{text(n)}</p>",
                head='<meta name="robots" content="noindex">'
                     f'<link rel="canonical" href="{SITE}/docs/p{n}/">')
        for n in range(max(closed, open_)):
            files[f"docs/p{n}/index.html"] = page(f"Current page {n} of the docs",
                                                  f"<h1>P{n}</h1><p>{text(n + 100)}</p>")
        return self.build(files)

    def test_one_decision_is_one_finding(self):
        issues = self.issues(self.site())
        codes = [i[2] for i in self.on(issues, "/docs/v1/p3/")]
        self.assertIn("noindex", codes)
        self.assertNotIn("canonical-elsewhere", codes)

    def test_a_closed_section_is_a_note_not_hundreds_of_criticals(self):
        result = checks.run_all(self.site(), SITE + "/")
        levels = {i[0] for i in result["issues"] if i[2] == "noindex"}
        self.assertEqual(levels, {"info"})
        self.assertTrue(any("/docs/v1/" in n for n in result["notes"]), result["notes"])

    def test_a_single_closed_page_is_still_critical(self):
        issues = self.issues(self.site(closed=1))
        self.assertEqual([i[0] for i in issues if i[2] == "noindex"], ["critical"])


class BuiltMarkdown(Site):
    def test_hugo_source_copies_are_not_pages(self):
        pages = self.build({
            "index.html": page("Home of the notes", f"<h1>Home</h1><p>{text(0)}</p>"
                               '<a href="/notes/">notes</a>'),
            "notes/index.html": page("Notes of the project", f"<h1>Notes</h1><p>{text(1)}</p>"),
            "notes/index.source.md": '+++\ntitle = "Notes"\n+++\nShort raw source.\n',
        })
        self.assertEqual(sorted(p.url for p in pages), [SITE + "/", SITE + "/notes/"])
        self.assertTrue(any("index.source.md" in p for p in self.problems), self.problems)

    def test_markdown_in_an_underscore_asset_directory(self):
        pages = self.build({
            "index.html": page("Home of the docs", f"<h1>Home</h1><p>{text(0)}</p>"),
            "_media/example-with-yaml.md": "---\nauthor: x\n---\nOne sentence.\n",
        })
        self.assertEqual([p.url for p in pages], [SITE + "/"])

    def test_markdown_sources_without_html_are_still_pages(self):
        pages = self.build({
            "index.md": "---\ntitle: Home\n---\n# Home\n\n" + text(0),
            "guide.md": "---\ntitle: Guide\n---\n# Guide\n\n" + text(1),
        })
        self.assertEqual(len(pages), 2)


class BadHref(Site):
    def test_a_broken_link_does_not_kill_the_run(self):
        pages = self.build({
            "index.html": page("Home page title for the test",
                               f"<h1>Home</h1><p>{text(0)}</p>"
                               '<a href="https://example.org][1">x</a> <a href="/a/">a</a>'
                               '<a href="http://[::1">y</a>',
                               head='<link rel="canonical" href="http://[bad">'),
            "a/index.html": page("Page A of the test site", f"<h1>A</h1><p>{text(1)}</p>"
                                 '<a href="/">home</a>'),
        })
        self.assertEqual(len(pages), 2)
        self.issues(pages)
        # 3.9 такой адрес не отвергает, 3.12+ бросает ValueError — падать нельзя нигде.
        core.url_key("https://example.org][1")


class FlatFiles(Site):
    def test_a_flat_file_linked_as_html_keeps_its_html_address(self):
        pages = self.build({
            "index.html": page("Reference index", f"<h1>Ref</h1><p>{text(0)}</p>"
                               '<a href="reference/filter.html">filter</a>'),
            "reference/filter.html": page("Filter rows of a table", f"<h1>filter</h1><p>{text(1)}</p>"
                                          '<a href="../index.html">home</a>'),
        })
        urls = sorted(p.url for p in pages)
        self.assertIn(SITE + "/reference/filter.html", urls)

    def test_a_flat_file_linked_without_extension_keeps_that_form(self):
        # Next.js export: out/about.html, ссылки /about.
        pages = self.build({
            "index.html": page("Home of the site", f"<h1>Home</h1><p>{text(0)}</p>"
                               '<a href="/about">about</a>'),
            "about.html": page("About the company", f"<h1>About</h1><p>{text(1)}</p>"
                               '<a href="/">home</a>'),
        })
        self.assertIn(SITE + "/about", [p.url for p in pages])

    def test_an_unlinked_flat_file_gets_the_form_that_works_everywhere(self):
        pages = self.build({
            "index.html": page("Home of the site", f"<h1>Home</h1><p>{text(0)}</p>"),
            "chapter_1.html": page("Chapter one of the book", f"<h1>One</h1><p>{text(1)}</p>"),
        })
        self.assertIn(SITE + "/chapter_1.html", [p.url for p in pages])

    def test_a_self_canonical_still_decides(self):
        pages = self.build({
            "index.html": page("Home of the site", f"<h1>Home</h1><p>{text(0)}</p>"
                               '<a href="/about.html">about</a>'),
            "about.html": page("About the company", f"<h1>About</h1><p>{text(1)}</p>",
                               head=f'<link rel="canonical" href="{SITE}/about/">'),
        })
        self.assertIn(SITE + "/about/", [p.url for p in pages])

    def test_directory_pages_are_unchanged(self):
        pages = self.build({
            "index.html": page("Home of the site", f"<h1>Home</h1><p>{text(0)}</p>"
                               '<a href="/guide/">guide</a>'),
            "guide/index.html": page("Guide to the city", f"<h1>Guide</h1><p>{text(1)}</p>"),
        })
        self.assertIn(SITE + "/guide/", [p.url for p in pages])


class Hints(Site):
    def test_links_without_the_base_path_are_named_as_such(self):
        # Eleventy без pathPrefix: сайт под /data/, ссылки от корня домена.
        files = {"index.html": page("Home of the data", f"<h1>Home</h1><p>{text(0)}</p>"
                                    '<a href="/oss/">oss</a> <a href="/attack/x/">x</a>')}
        files["oss/index.html"] = page("Open source list", f"<h1>OSS</h1><p>{text(1)}</p>"
                                       '<a href="/attack/x/">x</a>')
        for n, name in enumerate(("x", "y", "z", "w")):
            files[f"attack/{name}/index.html"] = page(
                f"Attack {name} described", f"<h1>{name}</h1><p>{text(n + 2)}</p>"
                '<a href="/oss/">oss</a> <a href="/attack/x/">x</a> <a href="/attack/y/">y</a>')
        root = tempfile.mkdtemp(prefix="indexgap-gen-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, body in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
        pages = core.load_pages(root, SITE + "/data/")[0]
        notes = checks.run_all(pages, SITE + "/data/")["notes"]
        self.assertTrue(any("/data" in n and "404" in n for n in notes), notes)


class SameOpening(Site):
    def test_banner_and_menu_without_main_are_not_the_opening(self):
        banner = ('<div class="notice">A thank you to everyone who makes this possible: '
                  '<a href="/thanks.html">Read More</a></div><header><nav>'
                  '<a href="/">Start</a> <a href="/p1.html">Events</a> '
                  '<a href="/p2.html">Tags</a> <a href="/p3.html">Speakers</a></nav></header>')
        files = {f"p{n}.html": page(f"Talk number {n} at the conference",
                                    banner + f"<h1>Talk {n}</h1><p>Speaker {n} talks about "
                                    f"topic {n * 7} with examples {n * 3}. {text(n)}</p>",
                                    main=False)
                 for n in range(10)}
        pages = self.build(files)
        issues = content.check_template_seams(pages)["issues"]
        self.assertEqual([i for i in issues if i[2] == "same-opening"], [])


if __name__ == "__main__":
    unittest.main()
