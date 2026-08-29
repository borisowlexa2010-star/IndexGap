# -*- coding: utf-8 -*-
"""
Выгрузки бывают не только из панели вебмастера.

Search Console есть не у каждого, а Ahrefs, Semrush, Screaming Frog, GA4
или просто список адресов — почти у всех. Читать их надо. Но приравнивать
нельзя: «Google знает про страницу» и «Screaming Frog до неё дошёл» —
разные утверждения, и подменять одно другим уверенным тоном хуже,
чем не отвечать вовсе.

Здесь закреплено и то, что все эти форматы читаются, и то, что смысл
каждого источника не теряется по дороге.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexgap import doctor, sources
from indexgap.core import SourceError

SITE = "https://example.com"


def make_xlsx(path, rows):
    """Минимальная книга: xlsx — это zip с XML, сторонних библиотек не нужно."""
    def esc(value):
        return str(value).replace("&", "&amp;").replace("<", "&lt;")
    sheet = ['<?xml version="1.0"?><worksheet xmlns="http://schemas.'
             'openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for r, row in enumerate(rows, 1):
        cells = "".join(f'<c r="A{r}" t="inlineStr"><is><t>{esc(v)}</t></is></c>'
                        for v in row)
        sheet.append(f'<row r="{r}">{cells}</row>')
    sheet.append("</sheetData></worksheet>")
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        book.writestr("xl/worksheets/sheet1.xml", "".join(sheet))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-src-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, text, encoding="utf-8"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        return path

    def path(self, name):
        return os.path.join(self.dir, name)


# ── форматы ───────────────────────────────────────────────────────────────────

class TestFormats(Fixture):
    def test_xlsx_is_read_without_third_party_libraries(self):
        """Ahrefs и Semrush по умолчанию отдают xlsx. Раньше пакет отказывался."""
        path = self.path("ahrefs-top-pages.xlsx")
        make_xlsx(path, [["Current URL", "Current traffic"],
                         [SITE + "/a/", "10"], [SITE + "/b/", "4"]])
        self.assertEqual(doctor.read_indexed(path)["urls"],
                         [SITE + "/a/", SITE + "/b/"])

    def test_a_broken_archive_is_explained_not_crashed(self):
        path = self.path("gsc.csv")
        with open(path, "wb") as fh:
            fh.write(b"PK\x03\x04not-really-a-zip")
        with self.assertRaises(SourceError) as ctx:
            doctor.read_indexed(path)
        self.assertIn("zip", str(ctx.exception).lower())

    def test_semicolon_cp1251_export_is_read(self):
        """Русский Excel и половина панелей отдают cp1251 с точкой с запятой."""
        path = self.write("вебмастер.csv",
                          "Адрес страницы;Показы\r\n" + SITE + "/жильё/;12\r\n",
                          encoding="cp1251")
        self.assertEqual(doctor.read_indexed(path)["urls"], [SITE + "/жильё/"])

    def test_plain_list_of_addresses(self):
        path = self.write("my-urls.txt", f"{SITE}/a/\n{SITE}/b/\n\n{SITE}/a/\n")
        self.assertEqual(doctor.read_indexed(path)["urls"],
                         [SITE + "/a/", SITE + "/b/"])

    def test_json_and_ndjson(self):
        one = self.write("custom.json",
                         json.dumps([{"url": SITE + "/a/", "status": "ok"}]))
        many = self.write("custom.ndjson",
                          json.dumps({"url": SITE + "/a/"}) + "\n" +
                          json.dumps({"url": SITE + "/b/"}) + "\n")
        self.assertEqual(doctor.read_indexed(one)["urls"], [SITE + "/a/"])
        self.assertEqual(doctor.read_indexed(many)["urls"],
                         [SITE + "/a/", SITE + "/b/"])

    def test_xml_sitemap_can_be_passed_as_a_source(self):
        path = self.write("export.xml",
                          f"<urlset><url><loc>{SITE}/a/</loc></url></urlset>")
        self.assertEqual(doctor.read_indexed(path)["urls"], [SITE + "/a/"])


# ── относительные пути ────────────────────────────────────────────────────────

class TestRelativePaths(Fixture):
    """
    GA4 и Matomo выгружают `/guide/visa/`, а не полный адрес. Без домена
    такой файл читался как пустой, и отчёт уверенно сообщал «в индексе ноль».
    """

    def test_paths_are_completed_with_site(self):
        path = self.write("ga4-pages.csv",
                          "Page path and screen class,Views\n/a/,10\n/b/,3\n")
        result = doctor.read_indexed(path, site=SITE)
        self.assertEqual(result["urls"], [SITE + "/a/", SITE + "/b/"])
        self.assertTrue(any("относительн" in n for n in result["notes"]))

    def test_without_site_the_file_is_not_silently_empty(self):
        path = self.write("ga4-pages.csv", "Page path,Views\n/a/,10\n")
        with self.assertRaises(SourceError) as ctx:
            doctor.read_indexed(path)
        self.assertIn("--site", str(ctx.exception))


# ── чей это файл ──────────────────────────────────────────────────────────────

class TestIdentify(Fixture):
    def test_name_in_the_file_wins(self):
        for name, expected, kind in (
                ("ahrefs-pages.xlsx", "ahrefs", sources.THIRDPARTY),
                ("semrush-organic.csv", "semrush", sources.THIRDPARTY),
                ("screamingfrog_internal_html.csv", "screamingfrog", sources.CRAWL),
                ("gsc-pages.csv", "google", sources.INDEX),
                ("ga4-export.csv", "ga4", sources.ANALYTICS)):
            tool, got, confident = sources.identify(name, [])
            self.assertEqual((tool, got, confident), (expected, kind, True), name)

    def test_generic_headers_do_not_decide_anything(self):
        """
        `url, status` на живом JSON уверенно назначало файл краулером Sitebulb.
        Слова, которые есть у всех, голосовать не должны.
        """
        tool, kind, confident = sources.identify("custom.json", ["url", "status"])
        self.assertEqual(tool, "")
        self.assertFalse(confident)

    def test_a_tie_is_answered_with_i_do_not_know(self):
        tool, _, _ = sources.identify("export.csv", ["URL", "Clicks", "Impressions"])
        self.assertEqual(tool, "")

    def test_unknown_name_is_just_a_list(self):
        self.assertEqual(sources.kind_of("что-то-своё"), sources.LIST)

    def test_explicit_label_beats_everything(self):
        self.assertEqual(sources.parse_spec("ahrefs=/tmp/gsc-pages.csv"),
                         ("ahrefs", "/tmp/gsc-pages.csv"))


# ── смысл источника не теряется ───────────────────────────────────────────────

class TestMeaningSurvives(Fixture):
    def sources_for(self, *names):
        specs = []
        for name in names:
            path = self.write(name, "URL\n" + SITE + "/a/\n")
            specs.append(path)
        return doctor.read_sources(specs, site=SITE)

    def test_panels_and_the_rest_are_kept_apart(self):
        result = self.sources_for("gsc-pages.csv", "ahrefs-pages.csv",
                                  "screamingfrog_internal_html.csv")
        self.assertEqual(sorted(result["by_engine"]), ["google"])
        self.assertEqual(sorted(result["by_source"]), ["ahrefs", "screamingfrog"])

    def test_step_label_follows_the_evidence(self):
        self.assertEqual(sources.index_grade(["google", "bing"]),
                         "Хотя бы в одном индексе")
        self.assertIn("сторонн", sources.index_grade(["ahrefs"]))
        self.assertIn("обход", sources.index_grade(["screamingfrog"]))
        self.assertIn("источник", sources.index_grade(["google", "ahrefs"]))

    def test_a_crawler_export_does_not_quietly_inflate_indexation(self):
        pages = []
        funnel = doctor.funnel(pages, None, None,
                               by_engine={"google": [SITE + "/a/"]},
                               by_source={"screamingfrog": [SITE + "/b/"]})
        self.assertTrue(any("индексом не являются" in n for n in funnel["foreign"]),
                        funnel["foreign"])

    def test_cross_engine_never_compares_a_panel_with_a_crawler(self):
        """
        «Есть в Google, нет в Screaming Frog» — не диагноз, а бессмыслица.
        Сравниваются только панели, и при одной панели сравнения нет вовсе.
        """
        funnel = doctor.funnel([], None, None,
                               by_engine={"google": [SITE + "/a/"]},
                               by_source={"screamingfrog": [SITE + "/b/"],
                                          "ahrefs": [SITE + "/c/"]})
        self.assertEqual(doctor.cross_engine(funnel, []), [])

    def test_every_source_says_what_it_proves(self):
        lines = sources.describe(["google", "ahrefs", "screamingfrog", "ga4"])
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertTrue(line.strip())


# ── колонка с ключом ──────────────────────────────────────────────────────────

class TestKeywordColumn(Fixture):
    def test_exports_name_the_keyword_column_differently(self):
        for header, expected in (
                (["Keyword", "Volume"], 0),
                (["Фраза", "Частотность"], 0),
                (["#", "Запрос", "WS"], 1),
                (["Search Term", "Clicks"], 0)):
            self.assertEqual(
                sources.guess_column(header, sources.KEYWORD_COLUMN_HINTS),
                expected, header)

    def test_a_table_without_a_keyword_column_is_not_guessed(self):
        self.assertEqual(
            sources.guess_column(["City", "Price"], sources.KEYWORD_COLUMN_HINTS), -1)

    def test_plan_accepts_an_ahrefs_export_as_is(self):
        from indexgap import cli
        path = self.write("ahrefs-keywords.csv",
                          "Keyword,Volume,KD\nвиза сингапур,1200,12\n"
                          "аренда авто бали,900,11\n")
        out = io.StringIO()
        from unittest import mock
        with mock.patch.object(sys, "stdout", out):
            code = cli.main(["plan", path])
        self.assertEqual(code, 0)
        self.assertIn("Keyword", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
