# -*- coding: utf-8 -*-
"""
`broken-link`: внутренняя ссылка на страницу, которой в сборке нет.

`link_graph` такие ссылки собирал всегда — и пользовался ими только для
догадки о неверном корне каталога. Находки не было: шаблон, ссылающийся на
строки, которые фильтр выкинул из сборки, давал тысячи ссылок в 404, и пакет
молчал. Ложные тревоги здесь легко устроить, поэтому правила осторожные:
ассеты (`.pdf`, `.png`, `.xml`) не страницы; ссылка в раздел, которого в
сборке нет вовсе (проверяли только /blog, а ссылка в /pricing), — не
поломка, а другая часть сайта.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

SITE = "https://example.com"
TEXT = " ".join(["Аренда спецтехники в городе с доставкой и машинистом."] * 8)


def html(title, links=()):
    anchors = " ".join(f'<a href="{href}">ссылка {n}</a>' for n, href in enumerate(links))
    return (f"<!doctype html><html lang=\"ru\"><head><title>{title}</title></head>"
            f"<body><main><h1>{title}</h1><p>{TEXT} {title}</p>{anchors}</main></body></html>")


class BrokenLinks(unittest.TestCase):
    def build(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-broken-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        pages = core.load_pages(root, SITE)[0]
        return checks.run_all(pages, SITE + "/")["issues"]

    def broken(self, issues):
        return {u: m for level, u, c, m in issues if c == "broken-link"}

    def site(self, extra_links=(), **files):
        base = {
            "index.html": html("Главная", ["/cities/", "/cities/omsk/", "/cities/tomsk/",
                                            *extra_links]),
            "cities/index.html": html("Города", ["/", "/cities/omsk/", "/cities/tomsk/"]),
            "cities/omsk/index.html": html("Омск", ["/cities/", "/cities/tomsk/"]),
            "cities/tomsk/index.html": html("Томск", ["/cities/", "/cities/omsk/"]),
        }
        base.update({k.replace("__", "/"): v for k, v in files.items()})
        return self.build(base)

    def test_a_link_to_a_missing_row_page_is_reported(self):
        issues = self.site(extra_links=["/cities/kursk/"])
        found = self.broken(issues)
        self.assertEqual(list(found), [SITE + "/"])
        self.assertIn("/cities/kursk", found[SITE + "/"])
        level = [i[0] for i in issues if i[2] == "broken-link"][0]
        self.assertEqual(level, "warning")

    def test_a_missing_root_level_page_is_reported_when_the_home_is_built(self):
        self.assertIn(SITE + "/", self.broken(self.site(extra_links=["/pricing"])))

    def test_assets_and_feeds_are_not_pages(self):
        issues = self.site(extra_links=["/files/price.pdf", "/img/a.png", "/feed.xml",
                                        "/sitemap.xml", "/robots.txt"])
        self.assertEqual(self.broken(issues), {})

    def test_query_and_fragment_of_an_existing_page_are_fine(self):
        issues = self.site(extra_links=["/cities/omsk/?utm_source=nav", "/cities/#list",
                                        "/cities/omsk/index.html"])
        self.assertEqual(self.broken(issues), {})

    def test_a_section_outside_the_checked_part_is_not_broken(self):
        # Проверяли только /blog: ссылки в /pricing и /docs/… — другая часть сайта.
        issues = self.build({
            "blog/a/index.html": html("A", ["/blog/b/", "/pricing", "/docs/start/"]),
            "blog/b/index.html": html("B", ["/blog/a/", "/blog/missing/"]),
        })
        found = self.broken(issues)
        self.assertEqual(list(found), [SITE + "/blog/b/"])
        self.assertIn("/blog/missing", found[SITE + "/blog/b/"])
        self.assertNotIn("pricing", " ".join(found.values()))

    def test_one_finding_per_page_naming_the_targets(self):
        issues = self.site(extra_links=["/cities/kursk/", "/cities/orel/", "/cities/kursk/"])
        found = self.broken(issues)
        self.assertEqual(len([i for i in issues if i[2] == "broken-link"]), 1)
        self.assertIn("2", found[SITE + "/"])

    def test_server_routes_of_the_build_are_not_broken(self):
        # Next.js: динамический маршрут без HTML — `[lang]/start/page.js`.
        # На visatosingapore 527 страниц ссылались на /en/start и /ru/start.
        issues = self.build({
            "index.html": html("Главная", ["/en/", "/en/a/", "/en/start", "/pricing",
                                            "/blog/hello-world", "/en/missing/"]),
            "en/index.html": html("EN", ["/", "/en/a/"]),
            "en/a/index.html": html("A", ["/en/"]),
            "[lang]/start/page.js": "module.exports = {}",
            "(marketing)/pricing/page.js": "module.exports = {}",
            "blog/[...slug]/page.js": "module.exports = {}",
        })
        found = self.broken(issues)
        self.assertEqual(list(found), [SITE + "/"])
        self.assertIn("/en/missing", found[SITE + "/"])
        for route in ("start", "pricing", "hello-world"):
            self.assertNotIn(route, found[SITE + "/"])

    def test_external_links_are_not_judged(self):
        self.assertEqual(self.broken(self.site(extra_links=["https://other.org/x/"])), {})


if __name__ == "__main__":
    unittest.main()


class BareIndex(unittest.TestCase):
    def test_a_bare_index_link_is_the_page(self):
        # VitePress cleanUrls: href="/en-US/resource/index".
        self.assertEqual(core.url_key(SITE + "/en-US/resource/index"),
                         core.url_key(SITE + "/en-US/resource/"))
        self.assertEqual(core.url_key(SITE + "/en-US/resource/index/"),
                         core.url_key(SITE + "/en-US/resource/"))
        self.assertEqual(core.url_key(SITE + "/index"), core.url_key(SITE + "/"))
        self.assertNotEqual(core.url_key(SITE + "/reindex"), core.url_key(SITE + "/"))
