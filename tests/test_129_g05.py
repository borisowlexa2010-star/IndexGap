# -*- coding: utf-8 -*-
"""1.29 (g05): fact-drift между языковыми версиями и кластеры hreflang."""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import core, doctor, facts, hreflang

SITE = "https://example.com"


class Site(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-g05-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, html):
        path = os.path.join(self.dir, rel, "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)

    def pages(self):
        return core.load_pages(self.dir, SITE)[0]


def link(code, href):
    return f'<link rel="alternate" hreflang="{code}" href="{href}">'


class Drift(Site):
    def page(self, lang, body, langs=("en", "de"), title="", description=""):
        alts = "".join(link(l, f"{SITE}/{l}/fee/") for l in langs)
        alts += link("x-default", f"{SITE}/en/fee/")
        meta = f'<meta name="description" content="{description}">' if description else ""
        self.write(f"{lang}/fee", f'<html lang="{lang}"><head><title>{title or "Fee " + lang}'
                                  f"</title>{meta}{alts}</head><body><main><p>{body}</p>"
                                  "</main></body></html>")

    def drift(self):
        return {i[1]: i[3] for i in facts.drift(self.pages())}


class TestFactDrift(Drift):
    def test_a_price_sharing_its_number_with_a_percent(self):
        self.page("en", "The fee is $20 and 20% of applicants get a refund.")
        self.page("de", "Die Gebühr beträgt $27 und 20% erhalten eine Erstattung.")
        self.assertEqual(list(self.drift()), [f"{SITE}/de/fee/"])

    def test_two_currencies_with_the_same_number(self):
        self.page("en", "The fee is $35 or €35 at the counter.")
        self.page("de", "Die Gebühr beträgt $35 oder €53 am Schalter.")
        self.assertIn("€53", self.drift()[f"{SITE}/de/fee/"])

    def test_the_same_price_and_percent_is_quiet(self):
        self.page("en", "The fee is $20 and 20% of applicants get a refund.")
        self.page("de", "Die Gebühr beträgt $20 und 20% erhalten eine Erstattung.")
        self.assertEqual(self.drift(), {})

    def test_more_spellings_of_dollar(self):
        for text in ("Die Gebühr beträgt 53 US-Dollar.", "Opłata wynosi 53 dolarów.",
                     "Ücret 53 ABD doları.", "料金は53米ドルです。", "费用为53美金"):
            with self.subTest(text):
                page = type("P", (), {"text": text})()
                got = facts.facts_of(page)
                self.assertEqual(list(got), ["USD"])
                self.assertEqual(list(got["USD"]), ["53"])

    def test_iso_codes_are_compared(self):
        self.page("en", "The visa fee is SEK 500 for adults.")
        self.page("de", "Die Visagebühr beträgt SEK 900 für Erwachsene.")
        self.assertEqual(list(self.drift()), [f"{SITE}/de/fee/"])

    def test_a_price_in_the_title_and_description(self):
        self.page("en", "Read about the fee.", title="Visa fee $35 for adults",
                  description="The visa fee is $35 for adults")
        self.page("de", "Lies über die Gebühr.", title="Visumgebühr 53 $ für Erwachsene",
                  description="Die Visumgebühr beträgt 53 $")
        self.assertEqual(list(self.drift()), [f"{SITE}/de/fee/"])

    def test_one_extra_zero_is_a_typo_not_a_conversion(self):
        self.page("en", "The fee is $35 for adults.")
        self.page("de", "Die Gebühr beträgt $350 für Erwachsene.")
        self.assertEqual(list(self.drift()), [f"{SITE}/de/fee/"])

    def test_an_explicit_dollar_that_grew_is_not_a_conversion(self):
        self.page("en", "The fee is $35 for adults.")
        self.page("de", "Die Gebühr beträgt 350 USD für Erwachsene.")
        self.assertEqual(list(self.drift()), [f"{SITE}/de/fee/"])

    def test_explicit_dollars_that_shrank_can_be_a_conversion(self):
        self.page("en", "La tarifa es $700 y la exprés $1200.")
        self.page("de", "Die Gebühr beträgt USD 35, express USD 60.")
        self.assertEqual(self.drift(), {})

    def test_a_conversion_that_dropped_one_price(self):
        self.page("en", "The fee is $35, express $60 and urgent $100.", langs=("en", "es"))
        self.page("es", "La tarifa es $700 y la exprés $1200.", langs=("en", "es"))
        self.assertEqual(self.drift(), {})


class Hreflang(Site):
    TEXT = "Some unique text for the page about a city and its streets."

    def page(self, rel, lang, links, text=TEXT):
        self.write(rel, f'<html lang="{lang}"><head><title>{rel} title here</title>'
                        f'<link rel="canonical" href="{SITE}/{rel}/">{links}</head>'
                        f"<body><h1>{rel}</h1><p>{text} {rel}</p></body></html>")

    def codes(self, pages=None):
        return [(i[2], i[1]) for i in hreflang.check(pages or self.pages())["issues"]
                if i[2].startswith("hreflang")]


class TestClusters(Hreflang):
    def test_one_code_for_two_addresses(self):
        for slug in ("a", "b"):
            both = "".join(link(l, f"{SITE}/{l}/{s}/") for l in ("en", "de") for s in ("a", "b"))
            self.page(f"en/{slug}", "en", both)
            self.page(f"de/{slug}", "de", both)
        found = self.codes()
        self.assertIn(("hreflang-conflict", f"{SITE}/en/a/"), found)

    def test_two_x_defaults(self):
        for slug in ("a", "b"):
            links = (link("en", f"{SITE}/en/{slug}/") + link("de", f"{SITE}/de/{slug}/")
                     + link("x-default", f"{SITE}/en/{slug}/") + link("x-default", f"{SITE}/de/{slug}/"))
            self.page(f"en/{slug}", "en", links)
            self.page(f"de/{slug}", "de", links)
        self.assertIn(("hreflang-conflict", f"{SITE}/de/a/"), self.codes())

    def test_a_correct_cluster_is_quiet(self):
        for slug in ("a", "b"):
            links = (link("en", f"{SITE}/en/{slug}/") + link("de", f"{SITE}/de/{slug}/")
                     + link("x-default", f"{SITE}/en/{slug}/"))
            self.page(f"en/{slug}", "en", links)
            self.page(f"de/{slug}", "de", links)
        self.assertEqual(self.codes(), [])

    def test_siblings_call_a_page_by_another_language(self):
        for slug in ("a", "b"):
            self.page(f"en/{slug}", "en", link("en", f"{SITE}/en/{slug}/") + link("de", f"{SITE}/de/{slug}/"))
            self.page(f"de/{slug}", "de", link("de", f"{SITE}/de/{slug}/") + link("fr", f"{SITE}/en/{slug}/"))
        self.assertIn(("hreflang-conflict", f"{SITE}/de/a/"), self.codes())

    def test_a_cluster_of_self_links_only(self):
        for slug in ("a", "b"):
            for lang in ("en", "de"):
                self.page(f"{lang}/{slug}", lang, link(lang, f"{SITE}/{lang}/{slug}/"))
        self.assertIn(("hreflang-missing", f"{SITE}/en/a/"), self.codes())

    def test_relative_hrefs_are_named_not_called_missing(self):
        for slug in ("a", "b"):
            links = link("en", f"/en/{slug}/") + link("de", f"/de/{slug}/")
            self.page(f"en/{slug}", "en", links)
            self.page(f"de/{slug}", "de", links)
        found = {code for code, _ in self.codes()}
        self.assertEqual(found, {"hreflang-relative"})

    def test_uk_used_for_an_english_version(self):
        text = "This is the English text of the page for readers in Britain about the city."
        for slug in ("a", "b"):
            links = link("en-US", f"{SITE}/us/{slug}/") + link("uk", f"{SITE}/uk/{slug}/")
            self.page(f"us/{slug}", "en", links, text)
            self.page(f"uk/{slug}", "uk", links, text)
        found = self.codes()
        self.assertIn(("hreflang-lang-mismatch", f"{SITE}/uk/a/"), found)
        self.assertNotIn(("hreflang-lang-mismatch", f"{SITE}/us/a/"), found)

    def test_real_ukrainian_is_quiet(self):
        for slug in ("a", "b"):
            links = link("en", f"{SITE}/en/{slug}/") + link("uk", f"{SITE}/uk/{slug}/")
            self.page(f"en/{slug}", "en", links)
            self.page(f"uk/{slug}", "uk", links, "Це український текст сторінки про місто та його вулиці.")
        self.assertEqual(self.codes(), [])


class TestSitemapAlternates(Hreflang):
    NS = ('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
          'xmlns:xhtml="http://www.w3.org/1999/xhtml"')

    def sitemap(self, name, entries):
        body = ""
        for loc, codes in entries:
            body += f"<url><loc>{loc}</loc>" + "".join(
                f'<xhtml:link rel="alternate" hreflang="{c}" href="{SITE}/{c}/a/"/>'
                for c in codes) + "</url>"
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f'<?xml version="1.0"?><urlset {self.NS}>{body}</urlset>')
        return path

    def test_in_page_x_default_does_not_hide_the_sitemap_cluster(self):
        for lang in ("en", "de"):
            self.page(f"{lang}/a", lang, link("x-default", f"{SITE}/en/a/"))
        path = self.sitemap("sm.xml", [(f"{SITE}/en/a/", ("en", "de")),
                                       (f"{SITE}/de/a/", ("en", "de"))])
        pages = self.pages()
        self.assertEqual(doctor.apply_sitemap_alternates(
            pages, doctor.read_sitemaps([path])["alternates"]), 2)
        self.assertEqual(self.codes(pages), [])

    def test_the_same_loc_in_two_sitemaps_is_merged(self):
        for lang in ("en", "de"):
            self.page(f"{lang}/a", lang, "")
        first = self.sitemap("a.xml", [(f"{SITE}/en/a/", ("en", "de")),
                                       (f"{SITE}/de/a/", ("en", "de"))])
        second = self.sitemap("b.xml", [(f"{SITE}/en/a/", ("en",))])
        for order in ([first, second], [second, first]):
            with self.subTest(order=order):
                pages = self.pages()
                doctor.apply_sitemap_alternates(pages, doctor.read_sitemaps(order)["alternates"])
                self.assertEqual(self.codes(pages), [])


if __name__ == "__main__":
    unittest.main()
