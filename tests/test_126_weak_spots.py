# -*- coding: utf-8 -*-
"""
1.26: три слабых места, которые показала сверка на живом многоязычном каталоге.

* Next.js App Router кладёт robots.txt и sitemap.xml маршрутами: файл
  `robots.txt.body` рядом с папкой `robots.txt/`. Их не находили — и без
  sitemap каждая сознательно закрытая страница была критичной.
* Закрытые целиком ветки раздела (одиннадцать стран по десять вопросов) — одно
  правило шаблона, а не сто критичных noindex.
* Шаблон, страницы которого стоят в двух процентах от порога дубля, молчал:
  риск был размазан по сотне сведений «похожа».
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


def run_check(folder, *extra):
    out = os.path.join(folder, "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        cli.main(["check", folder, "--site", SITE, "--out", out, *extra])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh), printed.getvalue()


class NextBuildFiles(unittest.TestCase):
    """Сборка Next.js: robots.txt/ и sitemap.xml/ — папки, ответ — в .body."""

    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="indexgap-126-"), "site")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir), True)
        shutil.copytree(DEMO, self.dir)
        for name in ("robots.txt", "sitemap.xml"):
            path = os.path.join(self.dir, name)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            os.remove(path)
            os.makedirs(os.path.join(self.dir, name))
            with open(os.path.join(self.dir, name, "route.js"), "w") as fh:
                fh.write("module.exports = {}")
            with open(path + ".body", "w", encoding="utf-8") as fh:
                fh.write(body)

    def closed_pages(self):
        pages = []
        for slug in sorted(os.listdir(os.path.join(self.dir, "rent"))):
            path = os.path.join(self.dir, "rent", slug, "index.html")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    if "noindex" in fh.read():
                        pages.append(slug)
        return pages

    def test_robots_body_is_found(self):
        args = SimpleNamespace(root=self.dir)
        self.assertTrue(cli._guess_robots(args).endswith("robots.txt.body"))
        report, _ = run_check(self.dir)
        self.assertNotIn("no-robots", {i["code"] for i in report["issues"]})

    def test_noindex_off_the_build_sitemap_is_a_decision(self):
        closed = self.closed_pages()
        self.assertTrue(closed, "the demo has a noindex page")
        listed = os.path.join(self.dir, "sitemap.xml.body")
        with open(listed, encoding="utf-8") as fh:
            xml = fh.read()
        for slug in closed:
            xml = xml.replace(f"<url><loc>{SITE}/rent/{slug}/</loc></url>", "")
        with open(listed, "w", encoding="utf-8") as fh:
            fh.write(xml)
        report, printed = run_check(self.dir)
        levels = {i["level"] for i in report["issues"] if i["code"] == "noindex"}
        self.assertEqual(levels, {"info"})
        self.assertIn("sitemap.xml", printed + json.dumps(report["notes"], ensure_ascii=False))

    def test_a_listed_noindex_page_stays_critical(self):
        closed = self.closed_pages()
        listed = os.path.join(self.dir, "sitemap.xml.body")
        with open(listed, encoding="utf-8") as fh:
            xml = fh.read()
        extra = "".join(f"<url><loc>{SITE}/rent/{slug}/</loc></url>" for slug in closed
                        if f"/rent/{slug}/" not in xml)
        with open(listed, "w", encoding="utf-8") as fh:
            fh.write(xml.replace("</urlset>", extra + "</urlset>"))
        report, _ = run_check(self.dir)
        levels = {i["level"] for i in report["issues"] if i["code"] == "noindex"}
        self.assertEqual(levels, {"critical"})

    def test_a_sitemap_index_in_the_build_is_not_fetched(self):
        with open(os.path.join(self.dir, "sitemap.xml.body"), "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><sitemapindex><sitemap><loc>'
                     'https://demo.example/s1.xml</loc></sitemap></sitemapindex>')
        self.assertEqual(cli._build_sitemap_urls(SimpleNamespace(root=self.dir)), [])


def page(url):
    return SimpleNamespace(url=url)


class ClosedGroups(unittest.TestCase):
    INTENTS = ["fees", "documents", "status", "photo", "timing"]

    def catalogue(self, closed_countries, open_countries=12):
        pages, issues = [], []
        names = [f"c{n:02d}" for n in range(len(closed_countries) + open_countries)]
        closed = set(names[:len(closed_countries)])
        for name in names:
            for intent in self.INTENTS:
                url = f"{SITE}/en/visa/{name}/{intent}/"
                pages.append(page(url))
                if name in closed:
                    issues.append(("critical", url, "noindex", "closed"))
        return pages, issues

    def test_closed_branches_are_one_finding(self):
        pages, issues = self.catalogue(range(5))
        out = checks.collapse_closed_groups(issues, pages)
        group = [i for i in out if i[2] == "noindex-group"]
        self.assertEqual(len(group), 1)
        self.assertEqual(group[0][0], "critical")
        self.assertEqual(group[0][1], "/en/visa/")
        self.assertEqual(len(group[0][3].subject), 25)
        self.assertEqual({i[0] for i in out if i[2] == "noindex"}, {"info"})

    def test_too_few_branches_stay_as_they_were(self):
        pages, issues = self.catalogue(range(2))
        self.assertEqual(checks.collapse_closed_groups(issues, pages), issues)

    def test_a_mostly_closed_section_is_not_a_group(self):
        """Закрыта большая часть веток — это раздел, его ведёт _closed_sections."""
        pages, issues = self.catalogue(range(8), open_countries=4)
        out = checks.collapse_closed_groups(issues, pages)
        self.assertFalse([i for i in out if i[2] == "noindex-group"])

    def test_a_sitemap_without_them_lowers_the_group(self):
        pages, issues = self.catalogue(range(5))
        out = checks.collapse_closed_groups(issues, pages)
        listed = [p.url for p in pages if "/c00/" not in p.url and "/c01/" not in p.url
                  and "/c02/" not in p.url and "/c03/" not in p.url and "/c04/" not in p.url]
        lowered = checks.closed_off_map(out, listed)
        self.assertEqual([i[0] for i in lowered if i[2] == "noindex-group"], ["info"])
        # Одна закрытая ветка в sitemap — противоречие: находка остаётся критичной.
        kept = checks.closed_off_map(out, listed + [f"{SITE}/en/visa/c00/fees/"])
        self.assertEqual([i[0] for i in kept if i[2] == "noindex-group"], ["critical"])


class DuplicateRisk(unittest.TestCase):
    def pairs(self, n, j, pattern="/en/visa/{}/fees/"):
        urls = [SITE + pattern.format(f"c{i}") for i in range(n)]
        return [(page(a), page(b), j) for a, b in zip(urls, urls[1:])]

    def test_a_template_at_the_threshold_is_one_warning(self):
        found = checks.duplicate_risk(self.pairs(6, 0.78), checks.CONFIG)
        self.assertEqual([(i[0], i[1], i[2]) for i in found],
                         [("warning", "/en/visa/*/fees/", "duplicate-risk")])
        self.assertEqual(len(found[0][3].subject), 6)
        self.assertIn("78%", found[0][3])

    def test_a_value_just_below_is_not_rounded_up(self):
        found = checks.duplicate_risk(self.pairs(6, 0.799), checks.CONFIG)
        self.assertIn("79%", found[0][3])
        self.assertNotIn("до 80%", found[0][3])

    def test_far_from_the_threshold_or_few_pages_is_quiet(self):
        self.assertEqual(checks.duplicate_risk(self.pairs(6, 0.70), checks.CONFIG), [])
        self.assertEqual(checks.duplicate_risk(self.pairs(4, 0.78), checks.CONFIG), [])

    def test_pages_of_different_templates_are_not_one_slot(self):
        self.assertEqual(checks._slot_pattern(SITE + "/en/a/fees/", SITE + "/en/b/fees/"),
                         "/en/*/fees/")
        self.assertEqual(checks._slot_pattern(SITE + "/en/a/fees/", SITE + "/en/b/status/"), "")
        self.assertEqual(checks._slot_pattern(SITE + "/en/a/", SITE + "/en/a/fees/"), "")

    def test_pages_already_over_the_threshold_are_counted_apart(self):
        pairs = self.pairs(6, 0.78) + [(page(SITE + "/en/visa/x/fees/"),
                                        page(SITE + "/en/visa/y/fees/"), 0.85)]
        found = checks.duplicate_risk(pairs, checks.CONFIG)
        self.assertIn("2 страниц(ы) этого шаблона порог уже перешли", found[0][3])
        self.assertEqual(len(found[0][3].subject), 6)


def write(folder, rel, html):
    path = os.path.join(folder, rel, "index.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


def doc(lang, head="", body="", words="text"):
    return (f'<!doctype html><html lang="{lang}"><head><title>{lang} page</title>{head}'
            f'</head><body><h1>{lang}</h1><p>{words}</p>{body}</body></html>')


class HreflangExactAndHead(unittest.TestCase):
    """Ответная ссылка — точный адрес; hreflang в <body> не считается."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-126h-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def links(self, en, de):
        return (f'<link rel="alternate" hreflang="en" href="{en}">'
                f'<link rel="alternate" hreflang="de" href="{de}">')

    def run_site(self):
        report, _ = run_check(self.dir, "--no-content")
        return [i for i in report["issues"] if i["code"].startswith("hreflang")]

    def test_a_return_link_to_the_http_variant_is_one_way(self):
        good = self.links(SITE + "/en/a/", SITE + "/de/a/")
        for city in ("b", "c"):
            write(self.dir, f"en/{city}", doc("en", self.links(SITE + f"/en/{city}/", SITE + f"/de/{city}/")))
            write(self.dir, f"de/{city}", doc("de", self.links(SITE + f"/en/{city}/", SITE + f"/de/{city}/")))
        write(self.dir, "en/a", doc("en", good))
        write(self.dir, "de/a", doc("de", self.links("http://demo.example/en/a/", SITE + "/de/a/")))
        found = self.run_site()
        returns = [i for i in found if i["code"] == "hreflang-no-return"]
        self.assertEqual([i["url"] for i in returns], [SITE + "/en/a/"])
        self.assertIn("http://demo.example/en/a/", returns[0]["message"])

    def test_the_sites_own_host_is_the_reference_not_site_flag(self):
        """Сайт везде пишет www.: это его адрес, и находок нет."""
        www = "https://www.demo.example"
        for city in ("a", "b", "c"):
            write(self.dir, f"en/{city}", doc("en", self.links(www + f"/en/{city}/", www + f"/de/{city}/")))
            write(self.dir, f"de/{city}", doc("de", self.links(www + f"/en/{city}/", www + f"/de/{city}/")))
        self.assertFalse([i for i in self.run_site() if i["code"] == "hreflang-no-return"])

    def test_links_in_body_do_not_count(self):
        for city in ("a", "b"):
            write(self.dir, f"en/{city}", doc("en", self.links(SITE + f"/en/{city}/", SITE + f"/de/{city}/")))
            body = city == "a"
            links = self.links(SITE + f"/en/{city}/", SITE + f"/de/{city}/")
            write(self.dir, f"de/{city}", doc("de", "" if body else links, links if body else ""))
        found = self.run_site()
        self.assertEqual([i["url"] for i in found if i["code"] == "hreflang-in-body"], [SITE + "/de/a/"])
        self.assertIn(SITE + "/en/a/", [i["url"] for i in found if i["code"] == "hreflang-no-return"])
        self.assertNotIn(SITE + "/de/a/", [i["url"] for i in found if i["code"] == "hreflang-missing"])


class SeamsPerSection(unittest.TestCase):
    """Двадцать одинаковых страниц раздела не прячутся за блогом рядом."""

    def build(self, guides):
        folder = tempfile.mkdtemp(prefix="indexgap-126s-")
        self.addCleanup(shutil.rmtree, folder, True)
        heads = ["What it costs", "Where to look", "How long it takes", "Who to call", "What to bring"]
        opening = ("Renting a flat here starts with the same short checklist that every "
                   "tenant should read before signing anything at all.")
        for n in range(20):
            body = "".join(f"<h2>{h}</h2><p>Text {n} about {h.lower()} here.</p>" for h in heads)
            write(folder, f"rent/city{n}", doc("en", body=body, words=opening))
        for n in range(guides):
            body = (f"<h2>Guide {n} part one</h2><p>Own words {n} for the first part.</p>"
                    f"<h2>Guide {n} part two</h2><p>More own words {n} for this guide.</p>")
            write(folder, f"guides/g{n}", doc("en", body=body,
                                              words=f"Guide number {n} opens with its own sentence about topic {n} today."))
        return folder

    def codes(self, folder):
        report, _ = run_check(folder, "--no-aeo")
        return {i["code"] for i in report["issues"]}

    def test_a_blog_beside_the_template_does_not_hide_it(self):
        for guides in (0, 20, 70):
            with self.subTest(guides=guides):
                found = self.codes(self.build(guides))
                self.assertIn("template-skeleton", found)
                self.assertIn("same-opening", found)

    def test_a_few_pages_in_a_section_are_not_a_template(self):
        folder = tempfile.mkdtemp(prefix="indexgap-126s2-")
        self.addCleanup(shutil.rmtree, folder, True)
        for n in range(4):
            write(folder, f"team/p{n}", doc("en", body="<h2>About</h2><p>a</p><h2>Contact</h2><p>b</p>",
                                            words=f"Person {n}"))
        for n in range(30):
            write(folder, f"blog/b{n}", doc("en", body=f"<h2>Topic {n}</h2><p>x {n}</p><h2>Notes {n}</h2><p>y</p>",
                                            words=f"Post {n}"))
        self.assertNotIn("template-skeleton", self.codes(folder))


class ArgparseInRussian(unittest.TestCase):
    def output(self, lang, argv):
        from indexgap import i18n
        before = i18n.get_lang()
        i18n.set_lang(lang)
        self.addCleanup(i18n.set_lang, before)
        from indexgap import argparse_ru
        argparse_ru.install()
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err), mock.patch.object(sys, "stdout", io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(argv)
        return err.getvalue() + out.getvalue()

    def test_errors_and_help_are_russian(self):
        self.assertIn("ошибка", self.output("ru", ["nosuch"]))
        self.assertIn("показать эту справку", self.output("ru", ["check", "--help"]))

    def test_english_stays_english(self):
        text = self.output("en", ["nosuch"])
        self.assertIn("error", text)
        self.assertNotIn("ошибка", text)


if __name__ == "__main__":
    unittest.main()
