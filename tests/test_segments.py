# -*- coding: utf-8 -*-
"""
Разрывы индексации по разделам — то, ради чего пакет называется IndexGap.

Воронка говорит «40 страниц не в индексе». Чинить по этой цифре нечего:
нужно знать, что 35 из них — раздел /rent/, где у шаблона сломана
перелинковка, а остальной сайт в порядке. Раздел подсвечивается, только
когда теряет заметно больше ОСТАЛЬНОГО сайта: большой раздел с обычными
потерями — это размер, а не беда.
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
from indexgap import cli, core, doctor

SITE = "https://example.com"


def page(title, extra_head=""):
    words = " ".join(f"{title} слово{j}" for j in range(150))
    return (f"<html><head><title>{title} — достаточно длинный заголовок</title>"
            f"{extra_head}</head><body><h1>{title}</h1><p>{words}</p>"
            f"<a href='/'>главная</a></body></html>")


class SiteCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-seg-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, html):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)

    def section(self, name, count, flat=False, head=""):
        urls = []
        for i in range(count):
            rel = f"{name}/p{i}.html" if flat else f"{name}/p{i}/index.html"
            self.write(rel, page(f"{name} {i}", head))
            urls.append(f"{SITE}/{name}/p{i}" + (".html" if flat else "/"))
        return urls

    def load(self):
        self.write("index.html", page("главная"))
        pages, _ = core.load_pages(self.dir, SITE)
        return pages

    def segments(self, pages, sitemap=None, indexed=None):
        result = doctor.funnel(pages, sitemap, indexed)
        return doctor.segments(result, pages)

    @staticmethod
    def flagged(result):
        return [(r["segment"], r["lost"], r["pages"]) for r in result["highlighted"]]


class TestHighlight(SiteCase):
    def test_the_section_that_loses_is_named(self):
        rent = self.section("rent", 20)
        buy = self.section("buy", 20)
        pages = self.load()
        everything = [SITE + "/"] + rent + buy
        indexed = [u for u in everything if u not in rent[:15] and u != buy[3]]
        got = self.segments(pages, everything, indexed)
        self.assertEqual(self.flagged(got), [("/rent/", 15, 20)])

    def test_a_section_that_drags_the_average_down_is_still_named(self):
        """
        Против среднего по сайту `/rent/` с 75% потерь не выделялся: он сам
        тянул среднее до 39%. Сравнивать надо с остальным сайтом.
        """
        rent = self.section("rent", 20)
        buy = self.section("buy", 20)
        pages = self.load()
        everything = [SITE + "/"] + rent + buy
        indexed = [u for u in everything if u not in rent[:15]]
        got = self.segments(pages, everything, indexed)
        self.assertIn("/rent/", [s for s, _, _ in self.flagged(got)])
        self.assertNotIn("/buy/", [s for s, _, _ in self.flagged(got)])

    def test_even_losses_highlight_nothing(self):
        """Везде теряется поровну — это свойство сайта, а не раздела."""
        rent = self.section("rent", 20)
        buy = self.section("buy", 20)
        pages = self.load()
        everything = [SITE + "/"] + rent + buy
        indexed = [u for u in everything if u not in rent[:8] + buy[:8]]
        got = self.segments(pages, everything, indexed)
        self.assertEqual(got["highlighted"], [])
        self.assertTrue(all(r["lost"] == 8 for r in got["rows"] if r["segment"] != "/"))

    def test_a_small_section_is_not_highlighted(self):
        """На трёх страницах любая доля — шум."""
        self.section("big", 30)
        tiny = self.section("tiny", 3)
        pages = self.load()
        everything = [SITE + "/"] + [p.url for p in pages]
        indexed = [u for u in everything if u not in tiny]
        got = self.segments(pages, everything, indexed)
        self.assertEqual(got["highlighted"], [])

    def test_a_sitemap_gap_is_a_gap_too(self):
        """Раздел, выпавший из sitemap, — самый частый разрыв на конвейере."""
        city = self.section("city", 10)
        self.section("guide", 10)
        pages = self.load()
        sitemap = [p.url for p in pages if p.url not in city[2:]]
        got = self.segments(pages, sitemap)
        self.assertEqual(self.flagged(got), [("/city/", 8, 10)])
        row = next(r for r in got["rows"] if r["segment"] == "/city/")
        self.assertEqual(row["missing_from_sitemap"], 8)
        self.assertIsNone(row["not_indexed"])        # индекса не давали — не выдумываем

    def test_closed_pages_are_not_counted_as_lost(self):
        """noindex — решение владельца, а не разрыв: такой раздел не подсвечивается."""
        self.section("drafts", 10, head='<meta name="robots" content="noindex">')
        live = self.section("live", 10)
        pages = self.load()
        got = self.segments(pages, [SITE + "/"] + live, [SITE + "/"] + live)
        self.assertEqual(got["highlighted"], [])
        self.assertNotIn("/drafts/", [r["segment"] for r in got["rows"]])


class TestWhereToLook(SiteCase):
    def test_one_big_section_is_split_one_level_down(self):
        """
        Блог, где всё лежит в /blog/, давал таблицу из одной строки — общую
        цифру ещё раз. Уровень разбивки опускается сам.
        """
        tags = self.section("blog/tags", 10, flat=True)
        self.section("blog/posts", 30, flat=True)
        pages = self.load()
        everything = [p.url for p in pages]
        indexed = [u for u in everything if u not in tags[:9]]
        got = self.segments(pages, everything, indexed)
        self.assertEqual(got["base"], "/blog/")
        self.assertEqual(self.flagged(got), [("/blog/tags/", 9, 10)])

    def test_flat_files_belong_to_their_folder(self):
        """`/rent/moscow.html` лежит в /rent/, а не в разделе из одной страницы."""
        self.section("rent", 6, flat=True)
        self.section("buy", 6, flat=True)
        pages = self.load()
        got = self.segments(pages, [p.url for p in pages])
        names = {r["segment"]: r["pages"] for r in got["rows"]}
        self.assertEqual(names.get("/rent/"), 6)
        self.assertEqual(names.get("/buy/"), 6)

    def test_a_subsection_that_holds_the_loss_replaces_its_parent(self):
        """Потери сосредоточены в /rent/moscow/ — виноват он, а не весь /rent/."""
        moscow = self.section("rent/moscow", 10)
        self.section("rent/spb", 10)
        self.section("buy", 20)
        pages = self.load()
        everything = [p.url for p in pages]
        indexed = [u for u in everything if u not in moscow]
        got = self.segments(pages, everything, indexed)
        self.assertEqual(self.flagged(got), [("/rent/moscow/", 10, 10)])

    def test_encoded_and_plain_addresses_are_one_section(self):
        """
        Пакет хранит кириллический адрес процент-кодированным, а выгрузка
        панели — обычной кириллицей. Это один раздел и одни страницы.
        """
        visa = self.section("виза", 10)
        self.section("guide", 10)
        pages = self.load()
        from urllib.parse import unquote
        everything = [p.url for p in pages]
        plain = [u for u in map(unquote, everything) if u not in visa[:7]]
        got = self.segments(pages, everything, plain)
        self.assertEqual(self.flagged(got), [("/виза/", 7, 10)])

    def test_nothing_to_compare_is_an_empty_answer(self):
        self.section("a", 10)
        pages = self.load()
        got = doctor.segments(doctor.funnel(pages), pages)
        self.assertEqual(got["rows"], [])
        self.assertEqual(doctor.segments({}, [])["rows"], [])

    def test_the_whole_site_is_never_its_own_gap(self):
        """Всё не в индексе — это беда сайта, она в воронке, а не в «разделе»."""
        a = self.section("a", 10)
        pages = self.load()
        got = self.segments(pages, [SITE + "/"] + a, [])
        self.assertEqual(got["highlighted"], [])


class TestShown(SiteCase):
    def run_doctor(self, *extra, lang=()):
        rent = self.section("rent", 20)
        buy = self.section("buy", 20)
        self.load()
        sm = os.path.join(self.dir, "..", os.path.basename(self.dir) + "-sitemap.xml")
        self.addCleanup(lambda: os.path.exists(sm) and os.remove(sm))
        listed = [SITE + "/"] + rent[:4] + buy
        with open(sm, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                     + "".join(f"<url><loc>{u}</loc></url>" for u in listed) + "</urlset>")
        out = io.StringIO()
        report = os.path.join(self.dir, "..", os.path.basename(self.dir) + "-report.html")
        for path in (report, report[:-5] + ".json"):
            self.addCleanup(lambda p=path: os.path.exists(p) and os.remove(p))
        with mock.patch.object(sys, "stdout", out):
            code = cli.main([*lang, "doctor", self.dir, "--site", SITE, "--sitemap", sm,
                             "--out", report, *extra])
        return code, out.getvalue(), report

    def test_doctor_points_at_the_section(self):
        code, out, report = self.run_doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("Разрывы по разделам", out)
        line = next(l for l in out.splitlines() if "/rent/" in l and "←" in l)
        self.assertIn("16", line)
        with open(report[:-5] + ".json", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual([h["segment"] for h in data["segments"]["highlighted"]], ["/rent/"])
        with open(report, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('class="hl"', html)
        self.assertIn("Разрывы по разделам", html)

    def test_the_english_output_is_english(self):
        from indexgap import i18n
        self.addCleanup(i18n.set_lang, "ru")
        _, out, _ = self.run_doctor(lang=("--lang", "en"))
        self.assertIn("Gaps by section", out)
        self.assertIn("the gap is here", out)


if __name__ == "__main__":
    unittest.main()
