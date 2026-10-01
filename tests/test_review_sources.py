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


if __name__ == "__main__":
    unittest.main()
