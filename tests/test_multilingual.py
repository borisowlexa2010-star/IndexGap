# -*- coding: utf-8 -*-
"""
Многоязычность и гео.

Прогон на живом каталоге виз — 2 970 страниц на десяти языках — показал, что
мультиязычный сайт до этого не поддерживался, а тихо портился. Цифры оттуда:

  * все 174 находки `thin` были ложными, и все 174 — китайскими: язык проекта
    определялся как `en` по большинству и перебивал язык каждой страницы,
    поэтому иероглифы считались словами (201 «слово» вместо 654);
  * все 914 находок `vague-anchor` были ложными: «यमन» (Йемен) и «হোম» (Главная)
    коротки в знаках и полны по смыслу. На английских страницах того же сайта
    находок не было ни одной;
  * hreflang не проверялся вовсе, хотя для сайта на десяти языках это
    единственное, что связывает версии между собой.

Здесь всё это закреплено, включая правило, ради которого писался модуль
`hreflang`: две версии на одном языке для разных стран законно похожи
почти дословно, и совет «поставь canonical» убил бы региональную версию.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import checks, content, core, hreflang, settings

SITE = "https://example.com"


def page_html(lang, title, body, alternates=(), canonical=None, anchors=()):
    links = "".join(
        f'<link rel="alternate" hrefLang="{code}" href="{href}">'
        for code, href in alternates)
    if canonical:
        links += f'<link rel="canonical" href="{canonical}">'
    body_links = "".join(f'<a href="/x{i}/">{a}</a>'
                         for i, a in enumerate(anchors))
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title>'
            f'<meta name="description" content="{"описание страницы " * 5}">'
            f'{links}</head><body><main><h1>{title}</h1><p>{body}</p>'
            f'{body_links}</main></body></html>')


class Fixture(unittest.TestCase):
    def pages(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-ml-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        loaded, _ = core.load_pages(root, SITE)
        return loaded

    def codes(self, result):
        return [i[2] for i in result["issues"]]


# ── письменность вместо объявленного языка ────────────────────────────────────

class TestScriptNotLanguage(Fixture):
    def test_chinese_page_is_not_thin_because_the_site_is_english(self):
        """174 ложных `thin` на живом сайте — ровно этот случай."""
        pages = self.pages({
            "zh/index.html": page_html("zh", "新加坡签证", "新加坡签证申请指南。" * 60),
        })
        page = pages[0]
        self.assertGreater(settings.text_volume(page, "en"), 250)

    def test_mixed_script_counts_both_halves(self):
        """
        У живого китайского каталога в заголовках 43% иероглифов, остальное
        латиница. Делить такую строку пополам — вдвое занизить латиницу.
        """
        pages = self.pages({
            "zh/index.html": page_html("zh", "新加坡签证 Form 14A",
                                       "新加坡签证 " * 50 + "Form 14A guide " * 50),
        })
        volume = settings.text_volume(pages[0], "")
        # 50 латинских слов ×3 + 150 иероглифов / 2 — порядок должен быть сотнями.
        self.assertGreater(volume, 200)

    def test_width_not_character_count_for_title(self):
        self.assertEqual(settings.display_width("abcd"), 4)
        self.assertEqual(settings.display_width("新加坡"), 6)
        self.assertEqual(settings.display_width("新加坡 Form"), 6 + 5)

    def test_latin_title_bounds_are_unchanged(self):
        bounds = checks._length_bounds(checks.CONFIG)
        self.assertEqual(bounds["title_max"], checks.CONFIG["title_max"])


class TestAnchorsInAnyScript(Fixture):
    def test_short_words_in_indic_scripts_are_not_vague(self):
        for anchor in ("यमन", "হোম", "العربية", "한국어", "ไทย"):
            page = self.pages({"a/index.html": page_html(
                "hi", "Заголовок страницы про визы", "текст " * 300,
                anchors=[anchor])})[0]
            self.assertNotIn("vague-anchor",
                             [i[2] for i in content.check_brief([page])], anchor)

    def test_latin_and_cyrillic_are_still_judged_by_length(self):
        """Короткое слово латиницей или кириллицей по-прежнему находка."""
        for anchor in ("тут", "тут", "see"):
            page = self.pages({"a/index.html": page_html(
                "ru", "Заголовок страницы про визы", "текст " * 300,
                anchors=[anchor])})[0]
            self.assertIn("vague-anchor",
                          [i[2] for i in content.check_brief([page])], anchor)

    def test_the_vague_word_list_still_works_in_any_length(self):
        """«подробнее» длинное, но бессмысленное — ловится списком, не длиной."""
        cfg = {"vague_anchors": settings.PROJECT_DEFAULTS["vague_anchors"]}
        page = self.pages({"a/index.html": page_html(
            "ru", "Заголовок страницы про визы", "текст " * 300,
            anchors=["подробнее"])})[0]
        self.assertIn("vague-anchor",
                      [i[2] for i in content.check_brief([page], cfg)])


# ── hreflang ──────────────────────────────────────────────────────────────────

class TestHreflang(Fixture):
    def cluster(self, langs, broken=None):
        files = {}
        for code in langs:
            alternates = [(other, f"{SITE}/{other}/") for other in langs
                          if not (broken and (code, other) == broken)]
            files[f"{code}/index.html"] = page_html(
                code, f"Title for {code} version", "текст " * 300,
                alternates=alternates)
        return self.pages(files)

    def test_a_correct_cluster_produces_nothing(self):
        pages = self.cluster(["en", "de", "fr"])
        result = hreflang.check(pages)
        self.assertTrue(result["checked"])
        self.assertEqual([i[2] for i in result["issues"]], [])

    def test_missing_self_reference_is_critical(self):
        pages = self.cluster(["en", "de", "fr"], broken=("en", "en"))
        codes = [i[2] for i in hreflang.check(pages)["issues"]]
        self.assertIn("hreflang-no-self", codes)

    def test_a_one_way_link_is_reported(self):
        """Google не «учитывает частично» — он отбрасывает связь целиком."""
        pages = self.cluster(["en", "de"], broken=("de", "en"))
        codes = [i[2] for i in hreflang.check(pages)["issues"]]
        self.assertIn("hreflang-no-return", codes)

    def test_a_country_code_where_a_language_belongs(self):
        self.assertIn("uk", hreflang.check_tag("uk-GB") or "uk")
        self.assertTrue(hreflang.check_tag("gb"))
        self.assertTrue(hreflang.check_tag("cn"))
        self.assertTrue(hreflang.check_tag("zzz"))

    def test_valid_codes_pass(self):
        for code in ("en", "pt-BR", "zh-Hant-TW", "x-default", "es-419"):
            self.assertEqual(hreflang.check_tag(code), "", code)

    def test_canonical_to_another_language_kills_the_cluster(self):
        files = {}
        for code in ("en", "de"):
            files[f"{code}/index.html"] = page_html(
                code, f"Title for {code}", "текст " * 300,
                alternates=[("en", f"{SITE}/en/"), ("de", f"{SITE}/de/")],
                canonical=f"{SITE}/en/" if code == "de" else None)
        codes = [i[2] for i in hreflang.check(self.pages(files))["issues"]]
        self.assertIn("hreflang-canonical-conflict", codes)

    def test_a_page_without_alternates_on_a_multilingual_site(self):
        files = {}
        for code in ("en", "de"):
            files[f"{code}/index.html"] = page_html(
                code, f"Title for {code}", "текст " * 300,
                alternates=[("en", f"{SITE}/en/"), ("de", f"{SITE}/de/")])
        files["fr/index.html"] = page_html("fr", "Titre", "текст " * 300)
        codes = [i[2] for i in hreflang.check(self.pages(files))["issues"]]
        self.assertIn("hreflang-missing", codes)

    def test_a_monolingual_site_is_left_alone(self):
        """Иначе это была бы находка на каждой странице каждого обычного сайта."""
        pages = self.pages({f"p{i}/index.html": page_html(
            "ru", f"Заголовок страницы {i}", f"текст{i} " * 300) for i in range(5)})
        result = hreflang.check(pages)
        self.assertFalse(result["checked"])
        self.assertEqual(result["issues"], [])


class TestStaticCluster(Fixture):
    """
    Живой каталог недвижимости: все 1 099 страниц печатали один и тот же
    кластер, ведущий на главную. Пакет выдавал 5 498 находок — по три с лишним
    на страницу — вместо одной строки о шаблоне. После починки: 4.
    """

    def test_one_finding_instead_of_thousands(self):
        alternates = [("en", f"{SITE}/"), ("ru", f"{SITE}/?lang=ru")]
        files = {f"p{i}/index.html": page_html(
            "en" if i % 2 else "ru", f"Title of page {i}", f"текст{i} " * 300,
            alternates=alternates) for i in range(30)}
        result = hreflang.check(self.pages(files))
        codes = [i[2] for i in result["issues"]]
        self.assertIn("hreflang-static-cluster", codes)
        self.assertEqual(codes.count("hreflang-static-cluster"), 1)
        self.assertNotIn("hreflang-no-self", codes)
        self.assertNotIn("hreflang-no-return", codes)

    def test_a_correct_per_page_cluster_is_not_called_static(self):
        files = {}
        for i in range(30):
            code = "en" if i % 2 else "de"
            other = "de" if i % 2 else "en"
            files[f"{code}/p{i}/index.html"] = page_html(
                code, f"Title of page {i}", f"текст{i} " * 300,
                alternates=[(code, f"{SITE}/{code}/p{i}/"),
                            (other, f"{SITE}/{other}/p{i}/")])
        codes = [i[2] for i in hreflang.check(self.pages(files))["issues"]]
        self.assertNotIn("hreflang-static-cluster", codes)


class TestGeoDuplicatesAreNotDuplicates(Fixture):
    """
    `en-us` и `en-gb` совпадают почти дословно, и это норма. Совет «оставь одну
    с canonical» убил бы региональную версию — а именно его давала обычная
    проверка дублей.
    """

    def regional(self):
        body = " ".join(f"слово{i}" for i in range(400))
        files = {}
        for code in ("en-us", "en-gb"):
            files[f"{code}/index.html"] = page_html(
                code, f"Visa guide {code}", body,
                alternates=[("en-US", f"{SITE}/en-us/"),
                            ("en-GB", f"{SITE}/en-gb/")])
        return self.pages(files)

    def test_regional_pair_is_not_called_a_duplicate(self):
        result = checks.run_all(self.regional(), home_url=SITE + "/")
        self.assertNotIn("near-duplicate", self.codes(result))

    def test_and_it_is_said_out_loud(self):
        result = checks.run_all(self.regional(), home_url=SITE + "/")
        self.assertTrue(any("canonical" in n and "стран" in n
                            for n in result["notes"]), result["notes"])


class TestTemplateWidePerLanguage(Fixture):
    """
    Находка может покрывать сто процентов одного языка и быть каплей по сайту.
    На живом сайте так вёл себя `description-length`: 289 из 289 китайских
    страниц, 10% сайта.
    """

    def test_a_finding_covering_one_language_is_named(self):
        pages = []
        issues = []
        for code, count in (("en", 60), ("zh", 25)):
            for i in range(count):
                url = f"{SITE}/{code}/p{i}/"
                pages.append(type("P", (), {"url": url, "lang": code})())
                if code == "zh":
                    issues.append(("info", url, "description-length", "…"))
        notes = checks.template_wide(issues, len(pages), pages=pages)
        self.assertTrue(any("zh" in n for n in notes), notes)

    def test_a_scattered_finding_is_not_named(self):
        pages, issues = [], []
        for code, count in (("en", 60), ("zh", 25)):
            for i in range(count):
                url = f"{SITE}/{code}/p{i}/"
                pages.append(type("P", (), {"url": url, "lang": code})())
                if i < 3:
                    issues.append(("info", url, "no-date", "…"))
        self.assertEqual(checks.template_wide(issues, len(pages), pages=pages), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
