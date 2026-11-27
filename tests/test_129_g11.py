# -*- coding: utf-8 -*-
"""
1.29 (g11): проверки шаблонности и граф ссылок.

Два шаблона в одном каталоге, плоские адреса, крошки и подпись автора перед
текстом, обвязка страницы без <main>, числовые и склоняемые подстановки;
hreflang без ответа, JS-редирект с корня, счёт сирот, белый список robots.txt,
`_index.md` Hugo, --home и --site с index.html, ссылки из тела заглушки.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, cli, content, core
from indexgap.core import SourceError

SITE = "https://demo.example"
WORDS = ("apple river stone bright garden window market silver forest quiet harbor "
         "thunder candle mirror lantern meadow copper violet bridge castle shadow "
         "orchard velvet canyon falcon glacier island jungle kettle ladder").split()


def prose(seed, n):
    out, x = [], seed * 7919 + 13
    for _ in range(n):
        x = (x * 1103515245 + 12345) % (1 << 31)
        out.append(WORDS[x % len(WORDS)] + str(x % 997))
    return " ".join(out)


def html(title, body, head="", main=True):
    inner = f"<main><h1>{title}</h1>{body}</main>" if main else body
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title} '
            f'page of the demo site</title>{head}</head><body>{inner}</body></html>')


class Site(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="indexgap-129-"), "site")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir), True)
        os.makedirs(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def page(self, rel, title, body, **kw):
        self.write(rel.strip("/") + "/index.html" if rel.strip("/") else "index.html",
                   html(title, body, **kw))

    def run_all(self, home="/", robots=None):
        pages, _ = core.load_pages(self.dir, SITE + "/")
        blocked = aeo.blocked_urls(pages, robots) if robots else frozenset()
        return checks.run_all(pages, SITE + home, blocked=blocked)

    def seams(self, code):
        pages, _ = core.load_pages(self.dir, SITE + "/")
        found = content.check_template_seams(pages)["issues"]
        return sorted(i[1] for i in found if i[2] == code)

    def check(self, *extra):
        out = os.path.join(os.path.dirname(self.dir), "r.json")
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            cli.main(["check", self.dir, "--site", SITE, "--no-content", "--no-aeo",
                      "--out", out, *extra])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh), buf.getvalue()

    @staticmethod
    def urls(result, code):
        return sorted(i[1] for i in result["issues"] if i[2] == code)


# ── шаблоны ───────────────────────────────────────────────────────────────────

class TwoTemplatesInOneSection(Site):
    def build(self, heads_b):
        heads_a = ["What it costs", "Where to look", "How long it takes", "Who to call"]
        links = []
        for n in range(12):
            for kind, heads in (("a", heads_a), ("b", heads_b)):
                body = "".join(f"<h2>{h}</h2><p>{prose(n * 50 + i + ord(kind) * 999, 60)}</p>"
                               for i, h in enumerate(heads))
                self.page(f"rent/{kind}{n}", f"Item {kind} {n}", body)
                links.append(f'<a href="/rent/{kind}{n}/">x</a>')
        self.page("", "Home", f"<p>{prose(1, 200)}</p>" + "".join(links))
        return self.seams("template-skeleton")

    def test_two_rigid_templates_in_one_directory_are_both_reported(self):
        result = self.build(["Service overview", "Pricing table", "Booking steps", "FAQ"])
        self.assertEqual(len(result), 24)

    def test_two_short_skeletons_do_not_add_up(self):
        # «Введение, Итоги» бывают у любых статей: двухзаголовочные скелеты
        # в сумму не идут.
        self.page("", "Home", f"<p>{prose(1, 200)}</p>")
        for n in range(10):
            for kind, heads in (("a", ["Intro", "Summary"]), ("b", ["Overview", "Notes"])):
                body = "".join(f"<h2>{h}</h2><p>{prose(n * 9 + i + ord(kind), 60)}</p>"
                               for i, h in enumerate(heads))
                self.page(f"blog/{kind}{n}", f"Post {kind} {n}", body)
        self.assertEqual(self.seams("template-skeleton"), [])


class SlotSkeletons(Site):
    def build(self, h1, h2):
        for n in range(10):
            body = "".join(f"<h2>{h.format(h2(n))}</h2><p>{prose(n * 10 + i, 60)}</p>"
                           for i, h in enumerate(["Prices in {}", "Callouts in {}",
                                                  "Reviews in {}", "Hours in {}"]))
            self.page(f"svc/p{n}", h1(n), body)
        self.page("", "Home", f"<p>{prose(1, 200)}</p>")
        return self.seams("template-skeleton")

    def test_zip_code_slot_is_masked(self):
        found = self.build(lambda n: f"Plumbers in {90210 + n}", lambda n: str(90210 + n))
        self.assertEqual(len(found), 10)

    def test_district_number_slot_is_masked(self):
        found = self.build(lambda n: f"Plumbers in District {n}", lambda n: f"District {n}")
        self.assertEqual(len(found), 10)

    def test_inflected_russian_slot_is_masked(self):
        cities = [("Москва", "Москве"), ("Казань", "Казани"), ("Тверь", "Твери"),
                  ("Пермь", "Перми"), ("Самара", "Самаре"), ("Уфа", "Уфе"),
                  ("Тула", "Туле"), ("Омск", "Омске"), ("Томск", "Томске"),
                  ("Курск", "Курске")]
        for n, (nom, prep) in enumerate(cities):
            body = "".join(f"<h2>{h} в {prep}</h2><p>{prose(n * 10 + i, 60)}</p>"
                           for i, h in enumerate(["Цены на аренду", "Где искать жильё",
                                                  "Какие документы нужны", "Сроки поиска"]))
            self.page(f"arenda/c{n}", f"{nom}: аренда квартир", body)
        self.page("", "Главная", f"<p>{prose(1, 200)}</p>")
        self.assertEqual(len(self.seams("template-skeleton")), 10)


class OpeningAfterServiceBlocks(Site):
    OPEN = ("Renting a flat here starts with the same short checklist that every "
            "tenant in the city reads before signing anything at all")

    def test_breadcrumb_repeating_h1_does_not_hide_same_opening(self):
        names = ["Alpha", "Bravo", "Delta", "Echo", "Golf", "Hotel", "India"]
        for n, name in enumerate(names):
            crumb = (f'<nav class="breadcrumb"><a href="/">Home</a> / '
                     f'<span>Renting in {name}</span></nav>')
            self.write(f"rent/{name.lower()}/index.html", html(
                f"Renting in {name}", "", main=False).replace(
                "<body>", f"<body><main>{crumb}<h1>Renting in {name}</h1>"
                          f"<p>{self.OPEN} {prose(n, 200)}</p></main>"))
        self.page("", "Home", f"<p>{prose(1, 200)}</p>")
        self.assertEqual(len(self.seams("same-opening")), 7)

    def test_shared_byline_is_not_a_same_opening(self):
        byline = ('<p class="byline">By the Demo Editorial Team · 5 min read · '
                  'Reviewed by our senior editors every single month</p>')
        for n in range(8):
            self.page(f"blog/post{n}", f"Post {n}", f"{byline}<p>{prose(n + 40, 300)}</p>")
        self.page("", "Home", f"<p>{prose(1, 200)}</p>")
        self.assertEqual(self.seams("same-opening"), [])


class FlatSlugSection(Site):
    def test_flat_clones_are_measured_as_their_own_section(self):
        fixed = prose(999, 300)
        for n in range(12):
            self.page(f"rent-town-{n}", f"Town {n}", f"<p>{prose(n, 30)}</p><p>{fixed}</p>")
        for n in range(40):
            self.page(f"post-{n}", f"Post {n}", f"<p>{prose(n + 500, 300)}</p>")
        self.page("", "Home", f"<p>{prose(1, 200)}</p>")
        result = self.run_all()
        low = self.urls(result, "low-uniqueness")
        self.assertEqual(len(low), 12)
        self.assertTrue(all("rent-town-" in u for u in low))


class FramedTextIsNotArticle(Site):
    MENU = " ".join(f'<a href="/c{i}/">Category {w} {w}</a>' for i, w in enumerate(WORDS * 2))

    def build(self, body_of):
        foot = f"<footer><p>{prose(4242, 150)}</p></footer>"
        for n in range(6):
            body = f"<header><nav>{self.MENU}</nav></header>{body_of(n)}{foot}"
            self.page(f"items/i{n}", f"Item {n}", body, main=False)
        self.page("", "Home", f"<p>{prose(1, 300)}</p>")
        return self.run_all()

    def test_short_article_without_main_is_thin(self):
        result = self.build(lambda n: f"<div class='content'><h1>Item {n}</h1>"
                                      f"<p>{prose(n, 60)}</p></div>")
        self.assertEqual(len(self.urls(result, "thin")), 6)

    def test_long_article_without_main_is_not_thin(self):
        result = self.build(lambda n: f"<div class='content'><h1>Item {n}</h1>"
                                      f"<p>{prose(n, 400)}</p></div>")
        self.assertEqual(self.urls(result, "thin"), [])


# ── граф ссылок ───────────────────────────────────────────────────────────────

class HreflangEdges(Site):
    def test_one_way_hreflang_does_not_save_an_orphan(self):
        alt = f'<link rel="alternate" hreflang="fr" href="{SITE}/fr-only/">'
        self.page("", "Home", f"<p>{prose(1, 200)}</p>", head=alt)
        self.page("fr-only", "Seulement", f"<p>{prose(2, 200)}</p>")
        self.assertIn(SITE + "/fr-only/", self.run_all()["graph"]["orphans"])

    def test_reciprocal_hreflang_still_links_versions(self):
        both = (f'<link rel="alternate" hreflang="en" href="{SITE}/en/x/">'
                f'<link rel="alternate" hreflang="de" href="{SITE}/de/x/">')
        self.page("", "Home", f'<p>{prose(1, 200)}</p><a href="/en/x/">x</a>')
        self.page("en/x", "Page", f"<p>{prose(2, 200)}</p>", head=both)
        self.page("de/x", "Seite", f"<p>{prose(3, 200)}</p>", head=both)
        graph = self.run_all()["graph"]
        self.assertNotIn(SITE + "/de/x/", graph["orphans"])
        self.assertNotIn(SITE + "/de/x/", graph["unreachable"])


class JsRedirectRoot(Site):
    def test_location_replace_root_is_a_stub(self):
        self.write("index.html", '<!doctype html><html><head><title>Go</title>'
                                 '<script>window.location.replace("/en/");</script>'
                                 '</head><body></body></html>')
        self.page("en", "English home", f'<p>{prose(1, 200)}</p><a href="/en/a/">a</a>')
        self.page("en/a", "Page a", f'<p>{prose(2, 200)}</p><a href="/en/">home</a>')
        result = self.run_all()
        self.assertEqual(result["graph"]["home"], SITE + "/en/")
        self.assertEqual(self.urls(result, "unreachable"), [])
        self.assertEqual(self.urls(result, "js-shell"), [])

    def test_deferred_js_redirect_is_not_a_stub(self):
        page = core.Page(path="x.html", url=SITE + "/x/", text="Thanks",
                         raw='<script>setTimeout(function(){location.href="/";}, 5000)</script>')
        self.assertEqual(checks.redirect_target(page), "")


class StubBodyLinks(Site):
    def test_links_in_redirect_stub_body_are_not_followed(self):
        self.page("", "Home", f'<p>{prose(1, 200)}</p><a href="/old/">old</a>'
                              '<a href="/new/">new</a>')
        self.write("old/index.html", '<!doctype html><html><head><title>Moved</title>'
                                     '<meta http-equiv="refresh" content="0; url=/new/">'
                                     '</head><body><nav><a href="/secret/">s</a></nav>'
                                     '</body></html>')
        self.page("new", "New", f'<p>{prose(2, 200)}</p><a href="/">home</a>')
        self.page("secret", "Secret", f'<p>{prose(3, 200)}</p>')
        self.assertIn(SITE + "/secret/", self.run_all()["graph"]["unreachable"])


class RobotsAllowList(Site):
    def test_disallow_all_with_allow_sections_is_partial(self):
        robots = {"found": True, "sitemaps": [], "rules": {"*": {
            "disallow": ["/"], "allow": ["/$", "/a/", "/behind/"]}}}
        self.page("", "Home", f'<p>{prose(1, 200)}</p><a href="/hub/">h</a><a href="/a/">a</a>')
        self.page("hub", "Hub", f'<p>{prose(2, 200)}</p><a href="/behind/">b</a>')
        self.page("behind", "Behind", f'<p>{prose(3, 200)}</p><a href="/">home</a>')
        self.page("a", "Aaa", f'<p>{prose(4, 200)}</p><a href="/">home</a>')
        self.assertFalse(aeo._blocks_everything(robots["rules"]["*"]))
        result = self.run_all(robots=robots)
        self.assertEqual(self.urls(result, "unreachable"), [SITE + "/behind/"])

    def test_home_only_allow_is_still_a_full_block(self):
        self.assertTrue(aeo._blocks_everything({"disallow": ["/"], "allow": ["/$"]}))


class HugoIndex(Site):
    def test_underscore_index_is_the_section_page(self):
        self.write("_index.md", f"---\ntitle: Home of the demo\n---\n# Home\n\n{prose(1, 200)}"
                                "\n\n[Posts](/posts/)\n")
        self.write("posts/_index.md", f"---\ntitle: All posts\n---\n# Posts\n\n{prose(2, 200)}"
                                      "\n\n[First](/posts/first/)\n")
        self.write("posts/first.md", f"---\ntitle: First post\n---\n# First\n\n{prose(3, 200)}"
                                     "\n\n[Home](/)\n")
        pages, _ = core.load_pages(self.dir, SITE + "/")
        self.assertEqual(sorted(p.url for p in pages),
                         [SITE + "/", SITE + "/posts/", SITE + "/posts/first/"])
        graph = checks.run_all(pages, SITE + "/")["graph"]
        self.assertFalse(graph["home_missing"])
        self.assertEqual(graph["orphans"], [])


class OrphanCountsAgree(Site):
    def test_accepted_orphan_is_not_in_the_json(self):
        self.page("", "Home", f'<p>{prose(1, 200)}</p><a href="/a/">a</a>')
        self.page("a", "Aaa", f'<p>{prose(2, 200)}</p><a href="/">home</a>')
        self.page("lonely", "Lonely", f'<p>{prose(3, 200)}</p>')
        self.write("indexgap.json", json.dumps({"ignore": {"orphan": ["/lonely/"]}}))
        data, _ = self.check()
        self.assertEqual(data["graph"]["orphans"] if "graph" in data else data["orphans"], [])

    def test_canonical_copy_is_not_in_the_json(self):
        self.page("", "Home", f'<p>{prose(1, 200)}</p><a href="/a/">a</a>')
        self.page("a", "Aaa", f'<p>{prose(2, 200)}</p><a href="/">home</a>')
        self.page("a/print", "Aaa", f'<p>{prose(2, 200)}</p>',
                  head=f'<link rel="canonical" href="{SITE}/a/">')
        data, _ = self.check()
        orphans = data["graph"]["orphans"] if "graph" in data else data["orphans"]
        self.assertEqual(orphans, [])


class HomeAndSiteArguments(Site):
    def build(self):
        self.page("", "Home", f'<p>{prose(1, 200)}</p><a href="/en/">en</a>')
        self.page("en", "English", f'<p>{prose(2, 200)}</p><a href="/">home</a>')

    def test_relative_home_is_resolved_against_site(self):
        self.build()
        args = mock.Mock(home="/en/", site=SITE + "/")
        pages, _ = core.load_pages(self.dir, SITE + "/")
        self.assertEqual(cli._home_url(args, pages), SITE + "/en/")

    def test_missing_home_is_an_error(self):
        self.build()
        args = mock.Mock(home=SITE + "/nonexist/", site=SITE + "/")
        pages, _ = core.load_pages(self.dir, SITE + "/")
        with self.assertRaises(SourceError):
            cli._home_url(args, pages)

    def test_site_with_index_html_is_the_directory(self):
        self.assertEqual(core.check_site_url("http://demo.example/docs/index.html"),
                         "http://demo.example/docs/")


if __name__ == "__main__":
    unittest.main()
