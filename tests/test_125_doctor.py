# -*- coding: utf-8 -*-
"""
1.25: doctor — входные данные, которые читались не так, как написаны.

* «Indexed: No», «Non-indexed», «De-indexed» засчитывались в индекс;
* раздел вне «главного» пропадал из разбивки по разделам;
* --baseline без --indexed объявлял, что всё вернулось в индекс;
* при --site с префиксом путь из выгрузки и из лога удваивал префикс;
* точка в имени раздела (`/rent/st.louis/`) считалась расширением файла;
* хост из JSON-лога (staging) терялся, если задан --site;
* столбец «Status: OK» побеждал «Coverage»;
* архив «Indexed, though blocked by robots.txt» читался как не в индексе;
* статус под `response.status` не читался, и об этом никто не говорил;
* 301 и HEAD засчитывались как «бот открыл страницу»;
* процитированный поддомен печатался ключом и назывался удалённой страницей;
* сводка «Индексация — google: N» считала написания адреса, а не страницы.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, crawlers, doctor

SITE = "https://demo.example"
SEARCH_UA = ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
             "OAI-SearchBot/1.0; +https://openai.com/searchbot")


def combined(path, status=200, method="GET", ua=SEARCH_UA):
    return (f'203.0.113.7 - - [02/Nov/2026:10:00:00 +0000] "{method} {path} HTTP/1.1" '
            f'{status} 512 "-" "{ua}"')


def page(title):
    words = " ".join(f"{title} слово{j}" for j in range(150))
    return (f"<html><head><title>{title} — достаточно длинный заголовок</title></head>"
            f"<body><h1>{title}</h1><p>{words}</p><a href='/'>главная</a></body></html>")


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.path(name)

    def site(self, slugs, base=SITE):
        root = self.path("site")
        for slug in slugs:
            d = os.path.join(root, *slug.strip("/").split("/"))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(page(slug))
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page("главная"))
        pages, _ = core.load_pages(root, base)
        return pages


class TestNegatedStatus(unittest.TestCase):
    def test_no_false_and_non_are_not_indexed(self):
        for status in ("Indexed: No", "Indexed? No", "Indexed (No)", "Indexed: false",
                       "Non-indexed", "De-indexed", "В поиске нет", "Нет в индексе"):
            self.assertFalse(doctor._is_indexed_status(status), status)

    def test_real_indexed_verdicts_stay_indexed(self):
        for status in ("Submitted and indexed", "Indexed, not submitted in sitemap",
                       "Indexed, though blocked by robots.txt", "Indexed: Yes",
                       "Indexed (no issues)", "URL is on Google", "Page indexed without content",
                       "Проиндексирована"):
            self.assertTrue(doctor._is_indexed_status(status), status)


class TestColumnsAndZips(Case):
    def test_coverage_column_wins_over_http_status(self):
        path = self.write("crawl.csv", "Address,Status Code,Status,Coverage\n"
                          f"{SITE}/a/,200,OK,Submitted and indexed\n"
                          f"{SITE}/b/,200,OK,Crawled - currently not indexed\n")
        got = doctor.read_indexed(path, SITE, index_status=True)
        self.assertEqual(got["urls"], [f"{SITE}/a/"])
        self.assertEqual(list(got["excluded"]), [f"{SITE}/b/"])

    def test_http_only_status_column_is_not_an_index_verdict(self):
        path = self.write("crawl.csv", f"Address,Status\n{SITE}/a/,OK\n{SITE}/b/,OK\n")
        got = doctor.read_indexed(path, SITE, index_status=True)
        self.assertEqual(got["urls"], [f"{SITE}/a/", f"{SITE}/b/"])

    def test_zip_of_indexed_issue_counts_as_indexed(self):
        path = self.path("demo.example-Coverage-Drilldown-2026-11-10.zip")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Table.csv", f"URL,Last crawled\n{SITE}/a/,2026-11-01\n"
                                          f"{SITE}/b/,2026-11-01\n")
            archive.writestr("Metadata.csv", "Property,Value\n"
                                             "Issue,\"Indexed, though blocked by robots.txt\"\n")
        got = doctor.read_sources([f"google={path}"], SITE)
        self.assertEqual(got["by_engine"]["google"], {f"{SITE}/a/", f"{SITE}/b/"})
        self.assertEqual(got["excluded"], {})

    def test_zip_of_not_indexed_issue_is_still_excluded(self):
        path = self.path("demo.example-Coverage-Drilldown-2026-11-10.zip")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Table.csv", f"URL,Last crawled\n{SITE}/a/,2026-11-01\n")
            archive.writestr("Metadata.csv", "Property,Value\n"
                                             "Issue,Crawled - currently not indexed\n")
        got = doctor.read_sources([f"google={path}"], SITE)
        self.assertNotIn("google", got["by_engine"])
        self.assertIn("google", got["excluded"])


class TestPathPrefix(Case):
    def test_root_relative_export_is_joined_to_the_host(self):
        path = self.write("ga4.csv", "Page path,Views\n/en/rent/berlin/,10\n/en/,4\n")
        got = doctor.read_indexed(path, SITE + "/en")
        self.assertEqual(got["urls"], [f"{SITE}/en/rent/berlin/", f"{SITE}/en/"])

    def test_root_relative_log_path_is_joined_to_the_host(self):
        path = self.write("access.log", combined("/en/rent/berlin/") + "\n")
        logs = crawlers.read_logs([path], SITE + "/en")
        self.assertEqual(logs["events"][0][6], f"{SITE}/en/rent/berlin/")


class TestLogs(Case):
    def test_dot_in_a_section_name_is_a_page(self):
        self.assertTrue(crawlers._is_page("/rent/st.louis/"))
        self.assertFalse(crawlers._is_page("/app.js"))
        pages = self.site(["rent/st.louis", "rent/berlin"])
        logs = crawlers.read_logs([self.write("a.log", combined("/rent/st.louis/") + "\n")], SITE)
        cov = crawlers.coverage(pages, logs)
        self.assertIn(f"{SITE}/rent/st.louis/", cov["fetched"][crawlers.AI_SEARCH])

    def test_json_host_of_another_site_is_not_production(self):
        pages = self.site(["rent/berlin"])
        line = json.dumps({"ClientRequestURI": "/rent/berlin/",
                           "ClientRequestHost": "staging.demo.example",
                           "ClientRequestUserAgent": SEARCH_UA, "EdgeResponseStatus": 200})
        logs = crawlers.read_logs([self.write("a.jsonl", line + "\n")], SITE)
        self.assertEqual(crawlers.coverage(pages, logs)["fetched"][crawlers.AI_SEARCH], [])

    def test_json_host_of_this_site_still_counts(self):
        pages = self.site(["rent/berlin"])
        lines = [json.dumps({"ClientRequestURI": "/rent/berlin/", "ClientRequestHost": host,
                             "ClientRequestUserAgent": SEARCH_UA, "EdgeResponseStatus": 200})
                 for host in ("www.demo.example", "localhost:3000")]
        logs = crawlers.read_logs([self.write("a.jsonl", "\n".join(lines) + "\n")], SITE)
        self.assertEqual(crawlers.coverage(pages, logs)["fetched"][crawlers.AI_SEARCH],
                         [f"{SITE}/rent/berlin/"])

    def test_status_under_response_is_read(self):
        hit = crawlers.parse_line(json.dumps({
            "request": {"path": "/rent/berlin/", "userAgent": SEARCH_UA},
            "response": {"status": 200}}))
        self.assertEqual((hit["target"], hit["status"]), ("/rent/berlin/", 200))

    def test_missing_status_is_said_out_loud(self):
        pages = self.site(["rent/berlin"])
        line = json.dumps({"path": "/rent/berlin/", "userAgent": SEARCH_UA,
                           "outcome": {"code": 200}})
        cov = crawlers.coverage(pages, crawlers.read_logs([self.write("a.jsonl", line + "\n")], SITE))
        self.assertEqual(cov["fetched"][crawlers.AI_SEARCH], [])
        self.assertTrue(any("не нашёлся код ответа" in n for n in cov["notes"]), cov["notes"])

    def test_redirect_and_head_are_not_an_opened_page(self):
        pages = self.site(["rent/berlin", "rent/munich", "rent/hamburg"])
        path = self.write("a.log", "\n".join([
            combined("/rent/munich/", 301),
            combined("/rent/hamburg/", 200, "HEAD"),
            # Слэш-вариант: редирект, а затем сама страница — открыта, не ошибка.
            combined("/rent/berlin", 301), combined("/rent/berlin/", 200)]) + "\n")
        cov = crawlers.coverage(pages, crawlers.read_logs([path], SITE))
        self.assertEqual(cov["fetched"][crawlers.AI_SEARCH], [f"{SITE}/rent/berlin/"])
        self.assertEqual([e["url"] for e in cov["errors"]], [f"{SITE}/rent/munich/"])
        self.assertEqual(cov["bots"][0]["errors"], 1)

    def test_not_modified_is_an_opened_page(self):
        pages = self.site(["rent/berlin"])
        path = self.write("a.log", combined("/rent/berlin/", 304) + "\n")
        cov = crawlers.coverage(pages, crawlers.read_logs([path], SITE))
        self.assertEqual(cov["fetched"][crawlers.AI_SEARCH], [f"{SITE}/rent/berlin/"])


class TestSections(unittest.TestCase):
    def test_small_section_beside_a_dominant_one_is_shown(self):
        urls = [f"{SITE}/rent/city{i:02d}/" for i in range(28)]
        urls += [f"{SITE}/buy/city{i:02d}/" for i in range(5)] + [f"{SITE}/"]
        publishable = {core.url_key(u): u for u in urls}
        lost = {core.url_key(u) for u in urls if "/buy/" in u}

        def stats(keys):
            return {"pages": len(keys), "reached": len(keys - lost)}

        got = doctor.section_gaps(publishable, stats)
        self.assertIn("/buy/", [r["segment"] for r in got["rows"]])
        self.assertEqual([h["segment"] for h in got["highlighted"]], ["/buy/"])
        # Каждая страница сайта — в одной из строк верхнего уровня.
        self.assertEqual(sum(r["pages"] for r in got["rows"] if r["depth"] <= 1), 34)

    def test_descent_into_a_real_subsection_still_happens(self):
        urls = [f"{SITE}/blog/{y}/post{i}/" for y in (2024, 2025) for i in range(10)]
        publishable = {core.url_key(u): u for u in urls}
        got = doctor.section_gaps(publishable, lambda keys: {"pages": len(keys),
                                                             "reached": len(keys)})
        self.assertEqual(got["base"], "/blog/")


class TestBaseline(unittest.TestCase):
    def run_of(self, has_index, not_indexed):
        return {"site": SITE, "funnel": {"has_index": has_index, "has_sitemap": True,
                                         "not_indexed": not_indexed,
                                         "missing_from_sitemap": [], "steps": []},
                "segments": {"rows": [{"segment": "/buy/", "lost": len(not_indexed)}],
                             "highlighted": [{"segment": "/buy/"}] if not_indexed else []}}

    def test_run_without_index_does_not_report_recovery(self):
        before = self.run_of(True, [f"{SITE}/buy/a/", f"{SITE}/buy/b/"])
        trend = doctor.compare_runs(self.run_of(False, []), before)
        self.assertEqual(trend["recovered"], [])
        self.assertEqual(trend["segments"]["closed_gaps"], [])
        self.assertEqual(trend["not_compared"], ["index"])

    def test_both_runs_with_index_still_compare(self):
        before = self.run_of(True, [f"{SITE}/buy/a/", f"{SITE}/buy/b/"])
        trend = doctor.compare_runs(self.run_of(True, [f"{SITE}/buy/a/"]), before)
        self.assertEqual(trend["recovered"], [f"{SITE}/buy/b/"])
        self.assertEqual(trend["not_compared"], [])


class TestCitedAndCounts(Case):
    def test_cited_subdomain_is_another_host_printed_as_cited(self):
        pages = self.site(["rent/berlin"])
        result = doctor.funnel(pages, cited={"cite": {f"{SITE}/rent/berlin/": 3,
                                                      "https://blog.demo.example/post/": 1,
                                                      f"{SITE}/rent/gone/": 1}})
        self.assertEqual(result["cited_other_hosts"], ["https://blog.demo.example/post/"])
        self.assertEqual(result["cited_unknown"], [f"{SITE}/rent/gone/"])
        self.assertIn(("https://blog.demo.example/post/", 1), result["cited_top"])

    def test_source_summary_counts_pages_not_spellings(self):
        self.assertEqual(doctor.count_pages([
            f"{SITE}/rent/berlin/", f"{SITE}/rent/berlin",
            "http://www.demo.example/rent/berlin/index.html",
            f"{SITE}/rent/berlin/?utm_source=x", f"{SITE}/rent/munich/",
            f"{SITE}/list/?page=2"]), 3)

    def test_console_summary_uses_page_count(self):
        path = self.write("idx.csv", "URL\n" + "\n".join([
            f"{SITE}/rent/berlin/", f"{SITE}/rent/berlin", f"{SITE}/rent/munich/"]) + "\n")
        args = mock.Mock(indexed=[f"google={path}"], gsc=None, site=SITE)
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            cli._collect_indexed(args)
        self.assertIn("google: 2", out.getvalue())


if __name__ == "__main__":
    unittest.main()
