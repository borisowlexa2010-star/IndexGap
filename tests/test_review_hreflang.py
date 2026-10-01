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


class TestDeclaredElsewhere(Fixture):
    def test_sitemap_hreflang_counts_as_declared(self):
        """Google считает sitemap равноправным способом объявить hreflang."""
        import os, tempfile
        from indexgap import doctor
        files = {}
        for lang in ("en", "de"):
            for path in ("", "pricing/", "about/"):
                files[f"{lang}/{path}index.html"] = page_html(lang, f"Page {lang} {path}", TEXT)
        pages = self.pages(files)
        ns = ('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
              'xmlns:xhtml="http://www.w3.org/1999/xhtml"')
        body = ""
        for lang in ("en", "de"):
            for path in ("", "pricing/", "about/"):
                links = "".join(f'<xhtml:link rel="alternate" hreflang="{l}" '
                                f'href="{SITE}/{l}/{path}"/>' for l in ("en", "de"))
                body += f"<url><loc>{SITE}/{lang}/{path}</loc>{links}</url>"
        handle, sitemap = tempfile.mkstemp(suffix=".xml")
        self.addCleanup(os.remove, sitemap)
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(f'<?xml version="1.0"?><urlset {ns}>{body}</urlset>')
        read = doctor.read_sitemaps([sitemap])
        self.assertEqual(len(read["alternates"]), 6)
        doctor.apply_sitemap_alternates(pages, read["alternates"])
        result = hreflang.check(pages)
        self.assertEqual([i[2] for i in result["issues"]], [])

    def test_markdown_sources_are_not_asked_for_hreflang(self):
        """В исходник на Markdown тег <link> не поставить: его добавит шаблон."""
        md = "---\ntitle: {0}\nlang: {1}\n---\n\n# {0}\n\n" + "текст " * 300
        pages = self.pages({"en/pricing.md": md.format("Pricing", "en"),
                            "de/pricing.md": md.format("Preise", "de")})
        self.assertEqual([i for i in hreflang.check(pages)["issues"]
                          if i[2] == "hreflang-missing"], [])


class TestIsMultilingual(Fixture):
    def test_locale_prefixes_without_lang_or_hreflang_are_multilingual(self):
        """Худший случай — сайт на трёх языках с `lang="en"` в шаблоне и без
        hreflang — раньше считался одноязычным и не проверялся вовсе."""
        files = {}
        for lang in ("en", "de", "fr"):
            for path in ("pricing", "about", "contact", "features"):
                files[f"{lang}/{path}/index.html"] = page_html("en", f"{path} {lang}", TEXT)
        result = hreflang.check(self.pages(files))
        self.assertTrue(result["checked"])
        self.assertEqual(len([i for i in result["issues"] if i[2] == "hreflang-missing"]), 12)

    def test_a_few_broken_clusters_on_a_large_site_are_still_checked(self):
        files = {f"p{n}/index.html": page_html("en", f"Page {n}", f"page{n} " + TEXT)
                 for n in range(60)}
        files["en/a/index.html"] = page_html("en", "A en", TEXT, alternates=[
            ("en", f"{SITE}/en/a/"), ("de", f"{SITE}/de/a/")])
        files["de/a/index.html"] = page_html("en", "A de", TEXT, alternates=[
            ("de", f"{SITE}/de/a/")])
        result = hreflang.check(self.pages(files))
        self.assertIn("hreflang-no-return", [i[2] for i in result["issues"]])


class TestParkedCollapseKeepsTheRest(Fixture):
    def site(self, with_open_links=True):
        files = {}
        for n in range(6):
            alternates = ([("en", f"{SITE}/en/p{n}/"), ("de", f"{SITE}/de/p{n}/")]
                          if with_open_links else [])
            files[f"en/p{n}/index.html"] = page_html("en", f"Page number {n}", f"page {n} " + TEXT,
                                                    alternates=alternates)
            files[f"de/p{n}/index.html"] = page_html(
                "de", f"Seite Nummer {n}", f"seite {n} " + TEXT,
                canonical=f"{SITE}/en/p{n}/").replace(
                    "<head>", '<head><meta name="robots" content="noindex">')
        return self.pages(files)

    def test_collapse_reports_open_pages_that_still_name_parked_translations(self):
        result = checks.run_all(self.site(), SITE + "/en/p0/")
        message = next(i[3] for i in result["issues"] if i[2] == "translations-parked")
        self.assertIn("6", message)
        self.assertIn("открыт", message)

    def test_a_language_switcher_is_not_hreflang(self):
        pages = self.site(with_open_links=False)
        for page in pages:
            if "/de/" in page.url:
                page.raw += '<a hreflang="en" href="/en/">English</a>'
        message = next(i[3] for i in checks.run_all(pages, SITE + "/en/p0/")["issues"]
                       if i[2] == "translations-parked")
        self.assertNotIn("всё ещё объявляют hreflang", message)


if __name__ == "__main__":
    unittest.main()
