# -*- coding: utf-8 -*-
"""
1.29 (g12): битые ссылки, формы адресов и хабы.

* Вторая запись ссылки на ту же страницу (`/about/` в меню, `/about.html` в
  тексте) не проверялась на форму.
* `oslo.json` рядом с пропавшей страницей делал /rent/oslo маршрутом.
* `root_mismatch` срабатывал при верном корне и глушил все битые ссылки.
* `/faq/?x=1` при `faq.html` не отмечался.
* `/Rent/nowhere/` (раздел в другом регистре) молчал.
* У `wrong-link-form` и `hub-missing-links` не было полного предмета.
* `/faq.html/` молчал.
* Слаги-числа и слаги-буквы со своим блоком «похожие» становились листами.
* Подстраница с крошкой и блоком «рядом» становилась списком.
* Два полных вида раздела (`/all-cities/`, `/map/`) не засчитывались.
* Вращающийся блок на страницах соседнего раздела прятал хаб.
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
from indexgap import checks, cli, core

SITE = "https://demo.example"
FILL = " ".join(["Rent deposit and commute figures differ between districts, and the "
                 "guide explains how newcomers search for viewings and contracts."] * 3)


def html(title, *links):
    a = "".join(f'<a href="{h}">{h}</a> ' for h in links)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width">'
            f'<title>{title} guide page</title><meta name="description" '
            f'content="A guide about {title} with rent and deposit details for newcomers.">'
            f'</head><body><main><h1>{title}</h1><p>{title}: {FILL}</p>{a}'
            f'</main></body></html>')


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

    def check(self):
        out = os.path.join(os.path.dirname(self.dir), "r.json")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", self.dir, "--site", SITE, "--no-content", "--no-aeo",
                      "--out", out])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def issues(self, data, code, url=None):
        return [i for i in data["issues"] if i["code"] == code
                and (url is None or i["url"] == SITE + url)]

    def text(self, data, code, url=None):
        return " ".join(i["message"] for i in self.issues(data, code, url))


class LinkForms(Site):
    def test_second_form_of_the_same_link_is_checked(self):
        self.write("index.html", html("Home", "/rent/", "/about/", "/faq.html"))
        self.write("rent/index.html", html("Rent", "/", "/about/", "/about.html",
                                           "/faq.html", "/faq/"))
        self.write("about/index.html", html("About", "/", "/faq.html"))
        self.write("faq.html", html("Faq", "/", "/about/"))
        data = self.check()
        text = self.text(data, "wrong-link-form", "/rent/")
        self.assertIn("/about.html", text)
        self.assertIn("/faq/", text)
        self.assertEqual(self.issues(data, "wrong-link-form", "/"), [])
        self.assertTrue(any(i["url"] == SITE + "/faq.html" for i in data["issues"]))

    def test_query_string_does_not_hide_the_form(self):
        self.write("index.html", html("Home", "/rent/", "/faq.html"))
        self.write("rent/index.html", html("Rent", "/", "/faq/?x=1"))
        self.write("faq.html", html("Faq", "/", "/rent/index.html?ref=1"))
        data = self.check()
        self.assertIn("/faq/", self.text(data, "wrong-link-form", "/rent/"))
        self.assertEqual(self.issues(data, "wrong-link-form", "/faq.html"), [])

    def test_wrong_form_carries_the_full_subject(self):
        cities = ["alpha", "beta", "gamma", "delta", "omega"]
        self.write("index.html", html("Home", "/rent/", *(f"/rent/{c}/" for c in cities)))
        self.write("rent/index.html", html("Rent", "/", *(f"/rent/{c}.html" for c in cities)))
        for c in cities:
            self.write(f"rent/{c}/index.html", html(c, "/rent/"))
        data = self.check()
        found = self.issues(data, "wrong-link-form", "/rent/")
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["subject"]), 5)


class BrokenLinks(Site):
    def test_data_file_does_not_make_a_route(self):
        self.write("index.html", html("Home", "/rent/", "/rent/berlin/", "/rent/oslo/",
                                      "/rent/berlin/photo/"))
        self.write("rent/index.html", html("Rent", "/", "/rent/berlin/"))
        self.write("rent/berlin/index.html", html("Berlin", "/rent/"))
        self.write("rent/oslo.json", "{}")
        self.write("rent/berlin/photo.jpg", "x")
        data = self.check()
        text = self.text(data, "broken-link", "/")
        self.assertIn("/rent/oslo", text)
        self.assertIn("/rent/berlin/photo", text)

    def test_page_route_files_still_count(self):
        self.write("index.html", html("Home", "/rent/", "/rent/live/"))
        self.write("rent/index.html", html("Rent", "/"))
        self.write("rent/live/page.js", "export default 1")
        self.write("rent/feed.js", "export default 1")
        self.write("rent/other.html", html("Other", "/rent/feed/"))
        data = self.check()
        self.assertEqual(self.issues(data, "broken-link"), [])

    def test_wrong_case_section(self):
        self.write("index.html", html("Home", "/rent/", "/rent/berlin/", "/Rent/nowhere/",
                                      "/Rent/berlin/"))
        self.write("rent/index.html", html("Rent", "/", "/rent/berlin/"))
        self.write("rent/berlin/index.html", html("Berlin", "/rent/"))
        data = self.check()
        self.assertIn("/Rent/nowhere", self.text(data, "broken-link", "/"))
        self.assertNotIn("/Rent/berlin", self.text(data, "broken-link", "/"))

    def test_slash_after_file_name(self):
        self.write("index.html", html("Home", "/rent/", "/faq.html/",
                                      "/rent/berlin/index.html/"))
        self.write("rent/index.html", html("Rent", "/", "/rent/berlin/", "/faq.html"))
        self.write("rent/berlin/index.html", html("Berlin", "/rent/"))
        self.write("faq.html", html("Faq", "/"))
        data = self.check()
        text = self.text(data, "broken-link", "/")
        self.assertIn("/faq.html", text)
        self.assertIn("/rent/berlin/index.html", text)
        self.assertEqual(self.issues(data, "broken-link", "/rent/"), [])

    def test_correct_root_with_one_section_missing_its_prefix(self):
        cities = ["alpha", "beta", "gamma", "delta", "omega", "sigma", "kappa", "theta"]
        self.write("index.html", html("Home", "/en/", "/de/", "/en/rent/ghost/"))
        self.write("en/index.html", html("En", "/", "/en/rent/alpha/", "/en/rent/alpha.html"))
        self.write("en/rent/alpha/index.html", html("En alpha", "/en/"))
        self.write("de/index.html", html("De", "/", *(f"/rent/{c}/" for c in cities)))
        for c in cities:
            self.write(f"de/rent/{c}/index.html", html("De " + c, "/de/"))
        data = self.check()
        self.assertIn("/en/rent/ghost", self.text(data, "broken-link", "/"))
        self.assertIn("/en/rent/alpha.html", self.text(data, "wrong-link-form", "/en/"))

    def test_shifted_root_is_still_named(self):
        for n in range(6):
            self.write(f"content/p{n}/index.html", html(f"P{n}", "/", *(f"/p{m}/" for m in range(6))))
        self.write("content/index.html", html("Home", *(f"/p{m}/" for m in range(6))))
        # Корневая страница со сдвинутыми ссылками: сдвиг по-прежнему назван.
        self.write("index.html", html("Root", *(f"/p{m}/" for m in range(6))))
        pages, _ = core.load_pages(self.dir, SITE)
        graph = checks.link_graph(pages, SITE + "/")
        self.assertTrue(checks.root_mismatch(pages, graph))


class Hubs(Site):
    def hub(self, data, url):
        return self.issues(data, "hub-missing-links", url)

    def test_numeric_slugs_with_related_block(self):
        ids = [str(100 + i) for i in range(20)]
        self.write("index.html", html("Home", "/products/"))
        self.write("products/index.html", html("Products", "/", "/products/100/"))
        for n, i in enumerate(ids):
            near = [ids[(n + 1) % 20], ids[(n + 2) % 20]]
            self.write(f"products/{i}/index.html",
                       html("Item " + i, "/products/", *(f"/products/{x}/" for x in near)))
        found = self.hub(self.check(), "/products/")
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["subject"]), 19)

    def test_numeric_pager_still_counts(self):
        posts = [f"post-{c}" for c in "abcdefghijkl"]
        self.write("index.html", html("Home", "/blog/"))
        self.write("blog/index.html", html("Blog", "/", "/blog/2/", *(f"/blog/{p}/" for p in posts[:6])))
        self.write("blog/2/index.html", html("Blog page 2", "/blog/", *(f"/blog/{p}/" for p in posts[6:])))
        for p in posts:
            self.write(f"blog/{p}/index.html", html(p, "/blog/"))
        self.assertEqual(self.hub(self.check(), "/blog/"), [])

    def test_letter_slugs_with_see_also(self):
        kids = ["a", "b", "c", "d", "e", "k", "b12", "folate", "biotin", "niacin"]
        self.write("index.html", html("Home", "/vitamins/"))
        self.write("vitamins/index.html", html("Vitamins", "/", "/vitamins/a/"))
        for n, k in enumerate(kids):
            near = [kids[(n + 1) % 10], kids[(n + 2) % 10]]
            self.write(f"vitamins/{k}/index.html",
                       html("Vitamin " + k, "/vitamins/", *(f"/vitamins/{x}/" for x in near)))
        found = self.hub(self.check(), "/vitamins/")
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["subject"]), 9)

    def test_deeper_pages_with_crumb_and_nearby(self):
        names = [f"city{i}" for i in range(20)]
        self.write("index.html", html("Home", "/plumbing/"))
        self.write("plumbing/index.html", html("Plumbing", "/", "/plumbing/city0/",
                                               "/plumbing/city0/emergency/"))
        for n, k in enumerate(names):
            nb = [names[(n + 1) % 20], names[(n + 2) % 20]]
            self.write(f"plumbing/{k}/index.html",
                       html("Plumbers " + k, "/plumbing/", f"/plumbing/{k}/emergency/"))
            self.write(f"plumbing/{k}/emergency/index.html",
                       html("Emergency " + k, "/plumbing/", f"/plumbing/{k}/",
                            *(f"/plumbing/{x}/" for x in nb),
                            *(f"/plumbing/{x}/emergency/" for x in nb)))
        found = self.hub(self.check(), "/plumbing/")
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["subject"]), 19)

    def test_deeper_listing_still_counts(self):
        cities = [f"city{i}" for i in range(8)]
        self.write("index.html", html("Home", "/plumbing/"))
        self.write("plumbing/index.html", html("Plumbing", "/", "/plumbing/states/",
                                               "/plumbing/states/north/"))
        self.write("plumbing/states/index.html", html("States", "/plumbing/"))
        self.write("plumbing/states/north/index.html",
                   html("North", "/plumbing/states/", *(f"/plumbing/{c}/" for c in cities)))
        for c in cities:
            self.write(f"plumbing/{c}/index.html", html("Plumbers " + c, "/plumbing/"))
        self.assertEqual(self.hub(self.check(), "/plumbing/"), [])

    def test_two_full_views_of_the_section(self):
        names = [f"city{i}" for i in range(12)]
        self.write("index.html", html("Home", "/plumbing/"))
        self.write("plumbing/index.html", html("Plumbing", "/", "/plumbing/all-cities/",
                                               "/plumbing/map/"))
        for k in names:
            self.write(f"plumbing/{k}/index.html", html("Plumbers " + k, "/plumbing/"))
        for v in ("all-cities", "map"):
            self.write(f"plumbing/{v}/index.html",
                       html("View " + v, "/plumbing/", *(f"/plumbing/{k}/" for k in names)))
        self.assertEqual(self.hub(self.check(), "/plumbing/"), [])

    def test_nearby_on_every_kid_still_reported(self):
        names = [f"city{i}" for i in range(8)]
        self.write("index.html", html("Home", "/plumbing/"))
        self.write("plumbing/index.html", html("Plumbing", "/"))
        for k in names:
            self.write(f"plumbing/{k}/index.html",
                       html("Plumbers " + k, "/plumbing/", *(f"/plumbing/{x}/" for x in names)))
        self.assertEqual(len(self.hub(self.check(), "/plumbing/")), 1)

    def test_rotating_block_on_cousin_section(self):
        names = [f"city{i}" for i in range(10)]
        self.write("index.html", html("Home", "/plumbing/", "/electricians/"))
        self.write("plumbing/index.html", html("Plumbing", "/", "/plumbing/city0/"))
        self.write("electricians/index.html",
                   html("Electricians", "/", *(f"/electricians/{k}/" for k in names)))
        for n, k in enumerate(names):
            near = [names[(n + j) % 10] for j in range(8)]
            self.write(f"plumbing/{k}/index.html", html("Plumbers " + k, "/plumbing/"))
            self.write(f"electricians/{k}/index.html",
                       html("Electricians " + k, "/electricians/",
                            *(f"/plumbing/{x}/" for x in near)))
        found = self.hub(self.check(), "/plumbing/")
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["subject"]), 9)

    def test_site_toc_page_still_counts(self):
        names = [f"city{i}" for i in range(10)]
        self.write("index.html", html("Home", "/plumbing/", "/toc.html"))
        self.write("toc.html", html("Contents", "/", *(f"/plumbing/{k}/" for k in names)))
        self.write("plumbing/index.html", html("Plumbing", "/"))
        for k in names:
            self.write(f"plumbing/{k}/index.html", html("Plumbers " + k, "/plumbing/"))
        self.assertEqual(self.hub(self.check(), "/plumbing/"), [])


if __name__ == "__main__":
    unittest.main()
