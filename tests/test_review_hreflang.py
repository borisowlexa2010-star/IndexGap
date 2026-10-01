# -*- coding: utf-8 -*-
"""
Языки и hreflang: находки ревью десяти агентов перед публичным запуском.

Самая частая поломка кластера — односторонняя ссылка на страницу, у которой
hreflang нет вовсе, — как раз и не сообщалась: проверка возврата пропускала
цель без единой альтернативы. Региональные версии узнавались по `<html lang>`,
который у `/us/` и `/uk/` одинаков, и верно размеченные страницы объявлялись
дублями. А языком считался любой первый сегмент пути из двух-трёх букв:
`/app/`, `/faq/`, `/api/`.
"""

import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, hreflang
from test_multilingual import SITE, Fixture, page_html

TEXT = "текст " * 300


class TestOneWay(Fixture):
    def test_one_way_link_to_a_page_without_any_hreflang_is_critical(self):
        pages = self.pages({
            "en/pricing/index.html": page_html("en", "Pricing page", TEXT, alternates=[
                ("en", f"{SITE}/en/pricing/"), ("de", f"{SITE}/de/preise/")]),
            "de/preise/index.html": page_html("de", "Preise Seite", TEXT),
        })
        found = [(i[1].replace(SITE, ""), i[2]) for i in hreflang.check(pages)["issues"]]
        self.assertIn(("/en/pricing/", "hreflang-no-return"), found)

    def test_a_closed_target_is_reported_once_not_twice(self):
        pages = self.pages({
            "en/pricing/index.html": page_html("en", "Pricing page", TEXT, alternates=[
                ("en", f"{SITE}/en/pricing/"), ("de", f"{SITE}/de/preise/")]),
            "de/preise/index.html": page_html("de", "Preise Seite", TEXT).replace(
                "<head>", '<head><meta name="robots" content="noindex">'),
        })
        codes = [i[2] for i in hreflang.check(pages)["issues"] if "/en/pricing" in i[1]]
        self.assertEqual(codes, ["hreflang-target-blocked"])


class TestRegionalPairs(Fixture):
    def site(self, us_lang, uk_lang):
        files = {}
        for n in range(8):
            alternates = [("en-us", f"{SITE}/us/p{n}/"), ("en-gb", f"{SITE}/uk/p{n}/"),
                          ("x-default", f"{SITE}/us/p{n}/")]
            # Текст свой у каждого товара и один на оба региона.
            body = " ".join(f"word{n}x{i}" for i in range(300))
            files[f"us/p{n}/index.html"] = page_html(us_lang, f"Product {n} for the US", body,
                                                    alternates=alternates)
            files[f"uk/p{n}/index.html"] = page_html(uk_lang, f"Product {n} for the UK", body,
                                                    alternates=alternates)
        return self.pages(files)

    def test_regional_pair_with_identical_html_lang_is_not_a_duplicate(self):
        """`lang="en"` на каждой английской версии — норма; Google его не читает."""
        pages = self.site("en", "en")
        result = checks.run_all(pages, SITE + "/us/p0/")
        codes = [i[2] for i in result["issues"]]
        self.assertNotIn("near-duplicate", codes)
        self.assertFalse(any("групп" in n and "почти-дубли" in n for n in result["notes"]),
                         result["notes"])

    def test_regional_pair_with_regional_html_lang_still_works(self):
        result = checks.run_all(self.site("en-US", "en-GB"), SITE + "/us/p0/")
        self.assertNotIn("near-duplicate", [i[2] for i in result["issues"]])


class TestLocalePrefix(unittest.TestCase):
    def split(self, path):
        return checks._locale_split(SITE + path)[1]

    def test_short_non_language_segments_are_not_locales(self):
        for path in ("/app/pricing/", "/go/x/", "/faq/", "/api/v1/", "/img/a/",
                     "/dev/", "/new/g1/", "/old/g1/", "/css/a/"):
            self.assertEqual(self.split(path), "", path)

    def test_languages_and_regions_are(self):
        for path, lang in (("/de/preise/", "de"), ("/pt-br/a/", "pt-br"),
                           ("/zh-Hant-TW/a/", "zh-hant-tw"), ("/en-gb/a/", "en-gb"),
                           ("/us/a/", "us"), ("/uk/a/", "uk")):
            self.assertEqual(self.split(path), lang, path)


class TestParkedAtRoot(Fixture):
    def test_parked_translations_with_default_language_at_root(self):
        """Next.js, Astro, Hugo, Docusaurus: основной язык живёт в корне."""
        files = {}
        for n in range(6):
            files[f"p{n}/index.html"] = page_html("en", f"Page number {n}", f"page {n} " + TEXT)
            files[f"de/p{n}/index.html"] = page_html(
                "de", f"Seite Nummer {n}", f"seite {n} " + TEXT,
                canonical=f"{SITE}/p{n}/").replace(
                    "<head>", '<head><meta name="robots" content="none">')
        pages = self.pages(files)
        self.assertEqual(len(checks.parked_translations(pages)), 6)
        codes = [i[2] for i in checks.run_all(pages, SITE + "/p0/")["issues"]]
        self.assertEqual(codes.count("translations-parked"), 1)
        self.assertNotIn("canonical-elsewhere", codes)


class TestCodes(unittest.TestCase):
    def test_basque_is_a_language_and_en_uk_is_not_a_region(self):
        self.assertEqual(hreflang.check_tag("eu"), "")
        self.assertNotEqual(hreflang.check_tag("en-UK"), "")
        self.assertEqual(hreflang.check_tag("en-GB"), "")
        self.assertEqual(hreflang.check_tag("es-419"), "")


if __name__ == "__main__":
    unittest.main()
