# -*- coding: utf-8 -*-
"""
1.28: canonical на `http://` или `www.`-версию той же страницы.

`url_key` снимает схему и `www.`, и такой canonical считался «на себя»:
страница уезжала в sitemap без единой находки. Теперь адрес сверяется с тем,
как называет себя сам сайт в canonical (большинство страниц), а не с --site:

* страница, чей canonical пишет другую схему или хост, — canonical-elsewhere
  (warning) и не идёт в sitemap;
* весь сайт пишет один адрес, отличный от --site, — одна заметка о сайте,
  а не находка на каждой странице;
* сайты, где всё согласовано, молчат.
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
from indexgap import cli, publish
from indexgap.core import load_pages

SITE = "https://demo.example"
CITIES = ("berlin", "munich", "hamburg", "cologne", "dresden", "bremen")


def page(slug, canonical=None, description=True):
    head = ""
    if canonical is not None:
        head += f'<link rel="canonical" href="{canonical}">'
    if description:
        head += f'<meta name="description" content="Rooms and flats to rent in {slug}, prices and districts.">'
    words = " ".join(f"{slug} district{i} street{i} rent{i}" for i in range(80))
    return (f'<!doctype html><html lang="en"><head><title>Renting a flat in {slug} today</title>'
            f'{head}</head><body><h1>Rent in {slug}</h1><p>{words}</p>'
            + "".join(f'<a href="/rent/{c}/">{c}</a>' for c in CITIES)
            + '<a href="/">home</a></body></html>')


class CanonicalHost(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-128c-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, html):
        path = os.path.join(self.dir, rel, "index.html") if rel else os.path.join(self.dir, "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)

    def build(self, origin=SITE, odd=None, relative=False):
        """Сайт: главная и шесть городов; `odd` — {город: canonical}."""
        odd = odd or {}
        self.write("", page("home", "/" if relative else origin + "/"))
        for city in CITIES:
            own = f"/rent/{city}/" if relative else f"{origin}/rent/{city}/"
            self.write(f"rent/{city}", page(city, odd.get(city, own)))

    def check(self, site=SITE):
        out = os.path.join(self.dir, "out", "r.json")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", self.dir, "--site", site, "--out", out])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def sitemap(self, site=SITE):
        out = os.path.join(self.dir, "out-sm")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["sitemap", self.dir, "--site", site, "--out", out])
        with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def canon(data):
        return [i for i in data["issues"] if i["code"] == "canonical-elsewhere"]

    @staticmethod
    def site_notes(data):
        return [n for n in data["notes"] if "--site" in str(n) and "canonical" in str(n)]

    # ── находки ────────────────────────────────────────────────────────────
    def test_http_canonical_among_https_is_flagged(self):
        self.build(odd={"berlin": "http://demo.example/rent/berlin/"})
        found = self.canon(self.check())
        self.assertEqual([(i["level"], i["url"]) for i in found],
                         [("warning", SITE + "/rent/berlin/")])
        self.assertIn("http://demo.example/rent/berlin/", found[0]["message"])
        self.assertNotIn("/rent/berlin/", self.sitemap())

    def test_www_canonical_among_bare_host_is_flagged(self):
        self.build(odd={"munich": "https://www.demo.example/rent/munich/"})
        found = self.canon(self.check())
        self.assertEqual([i["url"] for i in found], [SITE + "/rent/munich/"])
        xml = self.sitemap()
        self.assertNotIn("/rent/munich/", xml)
        self.assertIn("/rent/berlin/", xml)

    def test_odd_page_against_dominant_origin_not_against_site(self):
        # Сайт целиком на www., --site без него: из ряда выбивается только
        # страница без www.
        www = "https://www.demo.example"
        self.build(origin=www, odd={"dresden": "https://demo.example/rent/dresden/"})
        data = self.check()
        self.assertEqual([i["url"] for i in self.canon(data)], [SITE + "/rent/dresden/"])
        self.assertEqual(len(self.site_notes(data)), 1)

    def test_no_majority_falls_back_to_site(self):
        # Канонических адресов два, и они разные: мерило — --site.
        self.write("", page("home"))
        for city in CITIES:
            self.write(f"rent/{city}", page(city))
        self.write("rent/berlin", page("berlin", "http://demo.example/rent/berlin/"))
        self.write("rent/munich", page("munich", "https://www.demo.example/rent/munich/"))
        found = self.canon(self.check())
        self.assertEqual(sorted(i["url"] for i in found),
                         [SITE + "/rent/berlin/", SITE + "/rent/munich/"])

    def test_odd_page_keeps_its_other_findings(self):
        # Ошибочный canonical — не намеренное закрытие: остальное о странице
        # остаётся в отчёте.
        self.build(odd={"berlin": "http://demo.example/rent/berlin/"})
        self.write("rent/berlin", page("berlin", "http://demo.example/rent/berlin/",
                                       description=False))
        codes = {i["code"] for i in self.check()["issues"]
                 if i["url"] == SITE + "/rent/berlin/"}
        self.assertIn("no-description", codes)

    def test_indexable_origin_switch(self):
        self.build(odd={"berlin": "http://demo.example/rent/berlin/"})
        pages, _ = load_pages(self.dir, SITE)
        closed = sorted(p.url for p in pages if not publish.indexable(p))
        self.assertEqual(closed, [SITE + "/rent/berlin/"])
        self.assertTrue(all(publish.indexable(p, origin=False) for p in pages))

    # ── сайты, где всё в порядке ───────────────────────────────────────────
    def test_consistent_site_is_quiet(self):
        self.build()
        data = self.check()
        self.assertEqual(self.canon(data), [])
        self.assertEqual(self.site_notes(data), [])
        xml = self.sitemap()
        for city in CITIES:
            self.assertIn(f"/rent/{city}/", xml)

    def test_relative_canonicals_are_quiet(self):
        self.build(relative=True)
        data = self.check()
        self.assertEqual(self.canon(data), [])
        self.assertEqual(self.site_notes(data), [])

    def test_whole_site_on_www_is_one_note_not_per_page(self):
        self.build(origin="https://www.demo.example")
        data = self.check()
        self.assertEqual(self.canon(data), [])
        notes = self.site_notes(data)
        self.assertEqual(len(notes), 1)
        self.assertIn("https://www.demo.example", notes[0])
        xml = self.sitemap()
        for city in CITIES:
            self.assertIn(f"/rent/{city}/", xml)

    def test_whole_site_on_http_is_one_note_not_per_page(self):
        self.build(origin="http://demo.example")
        data = self.check()
        self.assertEqual(self.canon(data), [])
        self.assertEqual(len(self.site_notes(data)), 1)

    def test_site_given_with_www_but_pages_without_is_one_note(self):
        self.build()
        data = self.check(site="https://www.demo.example")
        self.assertEqual(self.canon(data), [])
        self.assertEqual(len(self.site_notes(data)), 1)

    def test_default_port_and_case_are_the_same_address(self):
        self.build(odd={"berlin": "https://demo.example:443/rent/berlin/",
                        "munich": "https://DEMO.example/rent/munich/"})
        data = self.check()
        self.assertEqual(self.canon(data), [])
        self.assertEqual(self.site_notes(data), [])

    def test_mixed_relative_and_absolute_same_origin_is_quiet(self):
        self.build(relative=True, odd={"berlin": SITE + "/rent/berlin/",
                                       "munich": SITE + "/rent/munich/"})
        self.assertEqual(self.canon(self.check()), [])

    def test_pages_without_canonical_are_quiet(self):
        self.write("", page("home"))
        for city in CITIES:
            self.write(f"rent/{city}", page(city))
        data = self.check()
        self.assertEqual(self.canon(data), [])
        self.assertEqual(self.site_notes(data), [])


if __name__ == "__main__":
    unittest.main()
