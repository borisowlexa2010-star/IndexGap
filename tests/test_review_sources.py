# -*- coding: utf-8 -*-
"""
Чтение выгрузок: находки ревью десяти агентов перед публичным запуском.

Воронка говорит «в индексе N» на основании файла, который ей дали. Файл со
списком адресов и подписью «google» она принимала за доказательство индекса —
в том числе выгрузку Search Console по причине «Просканировано, но не
проиндексировано». Список того, что поисковик отказался индексировать,
превращался в «в индексе 3», а действительно проиндексированное — в потерю.
"""

import os
import shutil
import tempfile
import unittest
import zipfile

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import doctor

SITE = "https://example.com"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-src-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def archive(self, name, members):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, "w") as zf:
            for member, text in members.items():
                zf.writestr(member, text)
        return path


class TestNotIndexedIsNotIndexed(Fixture):
    TABLE = ("URL,Last crawled\n"
             f"{SITE}/d,2026-09-01\n{SITE}/e,2026-09-02\n{SITE}/f,2026-09-03\n")

    def test_coverage_drilldown_of_a_not_indexed_reason_is_not_index_proof(self):
        path = self.archive("example.com-Coverage-Drilldown-2026-09-30.zip", {
            "Table.csv": self.TABLE,
            "Metadata.csv": "Property,Value\nIssue,Crawled - currently not indexed\n",
            "Chart.csv": "Date,Affected pages\n2026-09-01,3\n"})
        result = doctor.read_sources([f"google={path}"])
        self.assertEqual(result["by_engine"], {})
        self.assertEqual(sorted(result["excluded"]["google"]),
                         [f"{SITE}/d", f"{SITE}/e", f"{SITE}/f"])
        self.assertTrue(any("Crawled - currently not indexed" in n for n in result["notes"]),
                        result["notes"])

    def test_the_indexed_pages_drilldown_is_still_index_proof(self):
        path = self.archive("example.com-Coverage-Valid-2026-09-30.zip", {
            "Table.csv": self.TABLE,
            "Metadata.csv": "Property,Value\nSitemap,All known pages\n"})
        result = doctor.read_sources([f"google={path}"])
        self.assertEqual(len(result["by_engine"]["google"]), 3)

    def test_a_status_column_decides_row_by_row(self):
        path = self.write("inspection.csv",
                          "URL,Coverage State\n"
                          f"{SITE}/a,Submitted and indexed\n"
                          f"{SITE}/b,\"Indexed, not submitted in sitemap\"\n"
                          f"{SITE}/c,URL is unknown to Google\n"
                          f"{SITE}/d,Crawled - currently not indexed\n"
                          f"{SITE}/e,Excluded by 'noindex' tag\n")
        result = doctor.read_sources([f"google={path}"])
        self.assertEqual(sorted(result["by_engine"]["google"]), [f"{SITE}/a", f"{SITE}/b"])
        self.assertEqual(len(result["excluded"]["google"]), 3)

    def test_yandex_excluded_pages_are_not_in_search(self):
        path = self.write("yandex-excluded.csv",
                          "Url;Статус\n"
                          f"{SITE}/a;Исключена: малоценная или маловостребованная страница\n"
                          f"{SITE}/b;Исключена: дубль\n")
        result = doctor.read_sources([f"yandex={path}"])
        self.assertEqual(result["by_engine"], {})
        self.assertEqual(len(result["excluded"]["yandex"]), 2)

    def test_a_submission_log_is_not_an_index(self):
        path = self.write("bing-url-submission.csv",
                          f"URL,Status\n{SITE}/a,Submitted\n{SITE}/b,Submitted\n")
        result = doctor.read_sources([f"bing={path}"])
        self.assertEqual(result["by_engine"], {})

    def test_an_http_status_column_is_not_an_index_status(self):
        path = self.write("pages.csv", f"URL,Status\n{SITE}/a,200\n{SITE}/b,200\n")
        result = doctor.read_sources([f"google={path}"])
        self.assertEqual(len(result["by_engine"]["google"]), 2)


class TestImpressions(Fixture):
    def impressions(self, name, text):
        return doctor.read_sources([f"google={self.write(name, text)}"])["impressions"]

    def test_compare_mode_export_is_impressions_only(self):
        self.assertEqual(self.impressions(
            "pages.csv",
            "Top pages,Last 28 days Clicks,Previous 28 days Clicks,"
            "Last 28 days Impressions,Previous 28 days Impressions,"
            "Last 28 days CTR,Previous 28 days CTR,Last 28 days Position,Previous 28 days Position\n"
            f"{SITE}/a,3,1,40,20,7.5%,5%,8,9\n"), ["google"])

    def test_localized_performance_export_is_impressions_only(self):
        for header in ("上位のページ,クリック数,表示回数,CTR,掲載順位",
                       "Die häufigsten Seiten,Klicks,Impressionen,CTR,Position",
                       "Páginas principales,Clics,Impresiones,CTR,Posición",
                       "Самые популярные страницы,Клики,Показы,CTR,Позиция"):
            self.assertEqual(self.impressions("p.csv", f"{header}\n{SITE}/a,3,40,7.5%,8\n"),
                             ["google"], header)

    def test_an_indexing_export_is_still_not_impressions(self):
        self.assertEqual(self.impressions(
            "c.csv", f"URL,Last crawled\n{SITE}/a,2026-09-01\n"), [])


class TestCitationsUnderAnotherLabel(Fixture):
    def test_citation_export_labelled_bing_is_still_citation(self):
        """Иначе выборка из двух цитируемых страниц объявляет непроиндексированным
        весь остальной сайт — ровно то, от чего отделён шаг цитирований."""
        path = self.write("AIPerformance_Pages.csv",
                          f'"Page","Citations"\r\n"{SITE}/a","12"\r\n"{SITE}/b","3"\r\n')
        result = doctor.read_sources([f"bing={path}"])
        self.assertEqual(result["by_engine"], {})
        self.assertEqual(sum(sum(v.values()) for v in result["cited"].values()), 15)


class TestWhoseFile(Fixture):
    def identify(self, name, header="URL,Clicks"):
        from indexgap import sources
        path = self.write(name, header + f"\n{SITE}/a,1\n")
        return sources.identify(path, header.split(","))[0]

    def test_domain_substring_in_filename_does_not_pick_a_tool(self):
        """`bing` внутри `plumbing-pros.com` и `climbing.shop`, `gsc` внутри
        `dogscare.com` — это имя сайта, а не инструмента."""
        for name in ("plumbing-pros.com-organic.Pages-us.csv", "climbing.shop-top-pages.csv",
                     "dogscare.com-top-pages.csv"):
            self.assertEqual(self.identify(name), "", name)

    def test_a_tool_named_in_the_file_is_still_found(self):
        for name, tool in (("bing-pages.csv", "bing"), ("gsc_export.csv", "google"),
                           ("example.com-Performance-on-Search-2026-09-24.csv", "google"),
                           ("ahrefs-top-pages.csv", "ahrefs"),
                           ("yandex-webmaster-pages.csv", "yandex"),
                           ("google-analytics-landing.csv", "ga4"),
                           ("internal_html.csv", "screamingfrog")):
            self.assertEqual(self.identify(name), tool, name)

    def test_unknown_source_label_is_reported(self):
        path = self.write("pages.csv", f"URL\n{SITE}/a\n")
        result = doctor.read_sources([f"gogle={path}"])
        self.assertTrue(any("gogle" in n and "google" in n for n in result["notes"]),
                        result["notes"])

    def test_a_path_with_an_equals_sign_is_a_path(self):
        from indexgap import sources
        os.makedirs(os.path.join(self.dir, "x", "utm=1"))
        path = os.path.join(self.dir, "x", "utm=1", "pages.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"URL\n{SITE}/a\n")
        self.assertEqual(sources.parse_spec(path), ("", path))
        self.assertEqual(sources.parse_spec(f"google={path}"), ("google", path))


class TestTables(Fixture):
    def xlsx(self, name, sheets):
        """sheets: {имя листа: [[(ссылка ячейки, значение), …], …]}"""
        path = os.path.join(self.dir, name)
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        with zipfile.ZipFile(path, "w") as zf:
            for i, rows in enumerate(sheets, 1):
                body = "".join(
                    "<row>" + "".join(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
                                      for ref, value in row) + "</row>" for row in rows)
                zf.writestr(f"xl/worksheets/sheet{i}.xml",
                            f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")
        return path

    def test_xlsx_sparse_row_keeps_columns_aligned(self):
        """Excel не пишет пустые ячейки: без чтения ссылки `D3` строка съезжает влево."""
        path = self.xlsx("kw.xlsx", [[
            [("A1", "Keyword"), ("B1", "Previous position"), ("C1", "Position"), ("D1", "URL")],
            [("A2", "visa"), ("B2", "5"), ("C2", "3"), ("D2", f"{SITE}/a")],
            [("A3", "rent"), ("C3", "7"), ("D3", f"{SITE}/b")],
            [("A4", "flat"), ("C4", "9"), ("D4", f"{SITE}/c")],
        ]])
        self.assertEqual(doctor.read_indexed(path)["urls"],
                         [f"{SITE}/a", f"{SITE}/b", f"{SITE}/c"])

    def test_xlsx_picks_the_sheet_with_addresses(self):
        path = self.xlsx("gsc.xlsx", [
            [[("A1", "Top queries"), ("B1", "Clicks")], [("A2", "visa"), ("B2", "3")]],
            [[("A1", "Top pages"), ("B1", "Clicks")], [("A2", f"{SITE}/a"), ("B2", "3")]],
        ])
        self.assertEqual(doctor.read_indexed(path)["urls"], [f"{SITE}/a"])

    def test_ga4_comment_preamble_is_skipped(self):
        path = self.write("ga4.csv",
                          "# ----------------------------------------\n# Pages and screens\n"
                          "# 20260701-20260930\n# ----------------------------------------\n\n"
                          "Page path and screen class,Views,Users\n/a/,10,5\n/b/,3,2\n")
        self.assertEqual(doctor.read_indexed(path, site=SITE)["urls"], [f"{SITE}/a/", f"{SITE}/b/"])

    def test_headerless_list_keeps_its_first_url(self):
        path = self.write("indexed.txt", "/locations/berlin/\n/locations/munich/\n/pages/a/\n")
        self.assertEqual(len(doctor.read_indexed(path, site=SITE)["urls"]), 3)

    def test_a_cell_too_large_for_csv_is_an_error_with_words(self):
        from indexgap import core
        path = self.write("big.csv", 'URL,Note\n' + f'{SITE}/a,"' + "x" * 200_000 + '"\n')
        try:
            doctor.read_indexed(path)
        except core.SourceError:
            pass

    def test_citation_counts_with_thin_spaces(self):
        path = self.write("AIPerformance_Pages.csv",
                          f'"Page","Citations"\r\n"{SITE}/a","1\u00a0866"\r\n"{SITE}/b","1\u202f200"\r\n')
        self.assertEqual(doctor.read_citations(path), {f"{SITE}/a": 1866, f"{SITE}/b": 1200})


if __name__ == "__main__":
    unittest.main()
