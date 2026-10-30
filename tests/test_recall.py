# -*- coding: utf-8 -*-
"""
Полнота: дефекты программных сайтов, которые пакет пропускал молча.

Ревьюер собрал каталог на 757 страниц с посеянными дефектами. Ложных тревог
на чистых страницах почти не было, а вот половина дефектов проходила:

* `Disallow: /compare/` в robots.txt при шестидесяти таких страницах в
  sitemap — пакет разбирал правила, но смотрел только на `Disallow: /`;
* `X-Robots-Tag: noindex` из `_headers` закрывал 88 страниц глоссария, а
  отчёт показывал их открытыми;
* `answer-short` на 98% страниц: первым абзацем бралась строка
  «Updated September 2026»;
* `check-by-eye` на «rated 4.6 out of 5» — пятёрка шкалы не факт строки.
"""

import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, content, core

SITE = "https://example.com"
BODY = ("Plumbers in Austin fix leaks, unclog drains and install water heaters. Most "
        "visits take under two hours, and every job comes with a written quote first.")


def html(title, body, head=""):
    return (f"<!doctype html><html lang=\"en\"><head><title>{title}</title>{head}</head>"
            f"<body><main><h1>{title}</h1>{body}</main></body></html>")


class Fixture(unittest.TestCase):
    def build(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-recall-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.root = root
        pages, self.problems = core.load_pages(root, SITE)[:2]
        return pages


class RobotsRules(unittest.TestCase):
    def robots(self, text):
        root = tempfile.mkdtemp(prefix="indexgap-robots-")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "robots.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return aeo.read_robots(path)

    def test_longest_match_wins(self):
        r = self.robots("User-agent: *\nDisallow: /compare/\nAllow: /compare/public/\n")
        self.assertFalse(aeo.robots_allows(r, "/compare/a-vs-b/"))
        self.assertTrue(aeo.robots_allows(r, "/compare/public/x/"))
        self.assertTrue(aeo.robots_allows(r, "/pros/"))

    def test_wildcards_and_end_anchor(self):
        r = self.robots("User-agent: *\nDisallow: /*?sort=\nDisallow: /*.pdf$\n")
        self.assertFalse(aeo.robots_allows(r, "/pros/?sort=price"))
        self.assertFalse(aeo.robots_allows(r, "/files/a.pdf"))
        self.assertTrue(aeo.robots_allows(r, "/files/a.pdf.html"))

    def test_googlebot_group_beats_the_star(self):
        r = self.robots("User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow: /tmp/\n")
        self.assertTrue(aeo.robots_allows(r, "/pros/"))
        self.assertFalse(aeo.robots_allows(r, "/tmp/x"))

    def test_non_latin_rules_match_in_any_spelling(self):
        for rule in ("/каталог/", "/%d0%ba%d0%b0%d1%82%d0%b0%d0%bb%d0%be%d0%b3/",
                     "/%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3/"):
            with self.subTest(rule=rule):
                r = self.robots(f"User-agent: *\nDisallow: {rule}\n")
                self.assertFalse(aeo.robots_allows(r, "/%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3/a/"))
                self.assertFalse(aeo.robots_allows(r, "/каталог/a/"))
                self.assertTrue(aeo.robots_allows(r, "/pros/"))

    def test_a_versioned_agent_name_is_the_same_crawler(self):
        r = self.robots("User-agent: *\nDisallow:\n\nUser-agent: Googlebot/2.1\nDisallow: /tmp/\n")
        self.assertFalse(aeo.robots_allows(r, "/tmp/x"))

    def test_empty_disallow_allows(self):
        self.assertTrue(aeo.robots_allows(self.robots("User-agent: *\nDisallow:\n"), "/a/"))


class BlockedPages(Fixture):
    def test_a_blocked_page_in_the_build_is_critical(self):
        pages = self.build({
            "index.html": html("Plumbers directory", f"<p>{BODY}</p><a href='/compare/a-vs-b/'>c</a>"),
            "compare/a-vs-b/index.html": html("A versus B plumbing", f"<p>{BODY}</p>"),
            "robots.txt": "User-agent: *\nDisallow: /compare/\n",
        })
        result = aeo.run(pages, os.path.join(self.root, "robots.txt"))
        found = [i for i in result["issues"] if i[2] == "robots-blocks-page"]
        self.assertEqual([(i[0], i[1]) for i in found],
                         [("critical", SITE + "/compare/a-vs-b/")])

    def test_a_closed_page_is_not_reported_twice(self):
        pages = self.build({
            "index.html": html("Plumbers directory", f"<p>{BODY}</p>"),
            "admin/index.html": html("Admin", f"<p>{BODY}</p>",
                                     head='<meta name="robots" content="noindex">'),
            "robots.txt": "User-agent: *\nDisallow: /admin/\n",
        })
        result = aeo.run(pages, os.path.join(self.root, "robots.txt"))
        self.assertEqual([i for i in result["issues"] if i[2] == "robots-blocks-page"], [])

    def test_a_whole_site_block_is_one_finding(self):
        pages = self.build({
            "index.html": html("Plumbers directory", f"<p>{BODY}</p>"),
            "a/index.html": html("Page A", f"<p>{BODY}</p>"),
            "robots.txt": "User-agent: *\nDisallow: /\n",
        })
        result = aeo.run(pages, os.path.join(self.root, "robots.txt"))
        self.assertEqual([i for i in result["issues"] if i[2] == "robots-blocks-page"], [])


class HeaderFiles(Fixture):
    def site(self, extra):
        files = {"index.html": html("Plumbers directory", f"<p>{BODY}</p>"),
                 "glossary/drain/index.html": html("Drain glossary", f"<p>{BODY}</p>"),
                 "pros/a/index.html": html("Pro A", f"<p>{BODY}</p>")}
        files.update(extra)
        return {p.url: p for p in self.build(files)}

    def test_netlify_headers_file(self):
        pages = self.site({"_headers": "/glossary/*\n  X-Robots-Tag: noindex\n"
                                       "/pros/*\n  Cache-Control: max-age=60\n"})
        self.assertTrue(pages[SITE + "/glossary/drain/"].noindex)
        self.assertFalse(pages[SITE + "/pros/a/"].noindex)
        self.assertTrue(any("_headers" in p for p in self.problems), self.problems)

    def test_netlify_toml_one_level_up(self):
        files = {"index.html": html("Plumbers directory", f"<p>{BODY}</p>"),
                 "glossary/drain/index.html": html("Drain glossary", f"<p>{BODY}</p>")}
        root = tempfile.mkdtemp(prefix="indexgap-recall-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, "public", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(root, "netlify.toml"), "w", encoding="utf-8") as fh:
            fh.write('[build]\npublish = "public"\n\n[[headers]]\n  for = "/glossary/*"\n'
                     '  [headers.values]\n    X-Robots-Tag = "noindex, nofollow"\n')
        pages = {p.url: p for p in core.load_pages(os.path.join(root, "public"), SITE)[0]}
        self.assertTrue(pages[SITE + "/glossary/drain/"].noindex)
        self.assertFalse(pages[SITE + "/"].noindex)

    def test_vercel_json(self):
        pages = self.site({"vercel.json": json.dumps({"headers": [
            {"source": "/glossary/(.*)", "headers": [{"key": "X-Robots-Tag", "value": "noindex"}]}]})})
        self.assertTrue(pages[SITE + "/glossary/drain/"].noindex)
        self.assertFalse(pages[SITE + "/pros/a/"].noindex)

    def test_a_preview_host_rule_does_not_close_production(self):
        # Рецепт Cloudflare: превью *.pages.dev закрыты, свой домен открыт.
        for rule in ("https://:project.pages.dev/*", "https://preview.example.com/*"):
            with self.subTest(rule=rule):
                pages = self.site({"_headers": f"{rule}\n  X-Robots-Tag: noindex\n"})
                self.assertFalse(any(p.noindex for p in pages.values()))
        pages = self.site({"_headers": "https://example.com/glossary/*\n  X-Robots-Tag: noindex\n"})
        self.assertTrue(pages[SITE + "/glossary/drain/"].noindex)

    def test_a_header_for_another_bot_does_not_close_for_google(self):
        for value in ("googlebot-news: noindex", "bingbot: noindex", "otherbot: none"):
            with self.subTest(value=value):
                pages = self.site({"_headers": f"/glossary/*\n  X-Robots-Tag: {value}\n"})
                self.assertFalse(pages[SITE + "/glossary/drain/"].noindex)
        pages = self.site({"_headers": "/glossary/*\n  X-Robots-Tag: googlebot: noindex\n"})
        self.assertTrue(pages[SITE + "/glossary/drain/"].noindex)

    def test_a_removed_header_reopens_the_page(self):
        pages = self.site({"_headers": "/*\n  X-Robots-Tag: noindex\n"
                                       "/glossary/*\n  ! X-Robots-Tag\n"})
        self.assertFalse(pages[SITE + "/glossary/drain/"].noindex)
        self.assertTrue(pages[SITE + "/pros/a/"].noindex)

    def test_a_commented_out_toml_header_is_not_a_rule(self):
        pages = self.site({"netlify.toml": '[[headers]]\n  for = "/*"\n  [headers.values]\n'
                                           '    # X-Robots-Tag = "noindex"\n'
                                           '    Cache-Control = "max-age=60"\n'})
        self.assertFalse(any(p.noindex for p in pages.values()))

    def test_a_conditional_vercel_rule_is_not_applied_to_every_request(self):
        rule = {"source": "/(.*)", "headers": [{"key": "X-Robots-Tag", "value": "noindex"}]}
        for cond in ({"has": [{"type": "host", "value": "preview.example.com"}]},
                     {"has": [{"type": "header", "key": "x-preview"}]},
                     {"missing": [{"type": "host", "value": "example.com"}]}):
            with self.subTest(cond=cond):
                pages = self.site({"vercel.json": json.dumps({"headers": [{**rule, **cond}]})})
                self.assertFalse(any(p.noindex for p in pages.values()))
        own = {**rule, "has": [{"type": "host", "value": "example.com"}]}
        pages = self.site({"vercel.json": json.dumps({"headers": [own]})})
        self.assertTrue(pages[SITE + "/pros/a/"].noindex)


class FirstParagraph(Fixture):
    def test_a_date_line_is_not_the_answer(self):
        pages = self.build({"index.html": html(
            "Plumbers in Austin",
            "<p class='updated'><time datetime='2026-09-01'>Updated September 2026</time></p>"
            f"<p>{BODY} {BODY}</p>")})
        codes = [i[2] for i in aeo.check_answer(pages[0])]
        self.assertNotIn("answer-short", codes)

    def test_a_byline_is_not_the_answer(self):
        pages = self.build({"index.html": html(
            "Plumbers in Austin", f"<p>Published 12 March 2026 · 5 min read</p><p>{BODY} {BODY}</p>")})
        self.assertNotIn("answer-short", [i[2] for i in aeo.check_answer(pages[0])])

    def test_a_preamble_after_the_date_is_still_found(self):
        pages = self.build({"index.html": html(
            "Plumbers in Austin", "<p><time datetime='2026-09-01'>Updated September 2026</time></p>"
            f"<p>In today's fast-paced world, plumbing matters more than ever. {BODY}</p>")})
        self.assertIn("answer-preamble", [i[2] for i in aeo.check_answer(pages[0])])


class RatingScales(unittest.TestCase):
    def test_the_top_of_a_scale_is_not_a_fact(self):
        for phrase in ("rated 4.6 out of 5 across 1,801 reviews", "4.6/5 from 1,801 reviews",
                       "4,6 von 5 Sternen bei 1.801 Bewertungen", "оценка 4,6 из 5 по 1801 отзыву"):
            with self.subTest(phrase=phrase):
                got = content._generic_numbers_in(phrase)
                self.assertNotIn("5", got, got)


if __name__ == "__main__":
    unittest.main()


class CrossEngine(unittest.TestCase):
    def test_three_engines_are_not_double_counted(self):
        from indexgap import doctor
        pages = [core.Page(path=f"{n}.html", url=f"{SITE}/{n}/") for n in ("", "berlin", "munich")]
        key = lambda n: core.url_key(f"{SITE}/{n}/")
        funnel = {"panel_keys": {"google": {key("")}, "bing": {key(""), key("berlin")},
                                 "yandex": {key("munich")}}}
        out = {row["id"] + ":" + row.get("engine", ""): row["count"]
               for row in doctor.cross_engine(funnel, pages)}
        # Только в одном — не «нет только в» двух других.
        self.assertNotIn("missing-only:google", out)
        self.assertNotIn("missing-only:bing", out)
        # Главная есть в Google и Bing — нет только в Яндексе.
        self.assertEqual(out.get("missing-only:yandex"), 1)
        # Берлин и Мюнхен — каждый в одном индексе из трёх.
        self.assertEqual(out.get("partly:"), 2)

    def test_missing_only_from_one_engine(self):
        from indexgap import doctor
        pages = [core.Page(path="a.html", url=f"{SITE}/a/")]
        k = core.url_key(f"{SITE}/a/")
        funnel = {"panel_keys": {"google": set(), "bing": {k}, "yandex": {k}}}
        rows = {r["id"] + ":" + r.get("engine", ""): r["count"]
                for r in doctor.cross_engine(funnel, pages)}
        self.assertEqual(rows.get("missing-only:google"), 1)
