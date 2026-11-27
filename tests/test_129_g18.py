# -*- coding: utf-8 -*-
"""
1.29 (g18): doctor — выгрузки индекса и логи серверов.

* xlsx «одной причины» из Search Console: лист Metadata с Issue не читался;
* столбец статуса под `coverageState`, `coverage_state`, `Coverage Status`;
* «Not yet indexed», «Never indexed», «Indexed — No», неразрывный пробел;
* `sep=;` и строка-заголовок отчёта над таблицей ломали чтение CSV;
* «200 OK» в столбце Status — ответ сервера, а не вердикт индекса;
* безымянный архив причины GSC читался как простой список;
* Issue на нидерландском, китайском, турецком, корейском;
* немецкие вердикты «Gesendet und indexiert», «Indexiert, obwohl…»;
* показы и позиция на чешском, финском, венгерском, греческом, румынском;
* логи: `/rent/st.louis` без слэша, 403 после одного 200, битый .gz,
  1e400 и глубокий JSON, форматы GCP / Caddy / nginx escape=json,
  `"status": "info"`, robots.txt сайта против логов, 5xx на robots.txt,
  Amazonbot, ошибки ботов в HTML-отчёте, Apache vhost_combined.
"""

import gzip
import json
import os
import shutil
import tempfile
import unittest
import zipfile

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, core, crawlers, doctor, report, sources

SITE = "https://demo.example"
SEARCH_UA = "Mozilla/5.0 (compatible; OAI-SearchBot/1.3; +https://openai.com/searchbot)"
USER_UA = "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)"
URLS = [f"{SITE}/", f"{SITE}/about/", f"{SITE}/rent/berlin/", f"{SITE}/rent/munich/"]


def combined(path, status=200, ua=SEARCH_UA, prefix=""):
    return (f'{prefix}203.0.113.7 - - [02/Nov/2026:10:00:00 +0000] "GET {path} HTTP/1.1" '
            f'{status} 512 "-" "{ua}"')


def page(title):
    words = " ".join(f"{title} слово{j}" for j in range(150))
    return (f"<html><head><title>{title} — достаточно длинный заголовок</title></head>"
            f"<body><h1>{title}</h1><p>{words}</p><a href='/'>главная</a></body></html>")


def xlsx(path, sheets):
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("[Content_Types].xml", "<Types/>")
        book.writestr("xl/workbook.xml", "<workbook/>")
        for i, rows in enumerate(sheets, 1):
            xml = ['<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<sheetData>']
            for r, row in enumerate(rows, 1):
                xml.append(f'<row r="{r}">')
                for c, value in enumerate(row):
                    xml.append(f'<c r="{chr(65 + c)}{r}" t="inlineStr"><is><t>{value}</t></is></c>')
                xml.append("</row>")
            xml.append("</sheetData></worksheet>")
            book.writestr(f"xl/worksheets/sheet{i}.xml", "".join(xml))


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-129-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.path(name)

    def drilldown(self, name, key, issue):
        path = self.path(name)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Table.csv", "URL,Last crawled\n"
                             + "".join(f"{u},2026-11-01\n" for u in URLS))
            archive.writestr("Metadata.csv", f"Property,Value\n{key},{issue}\n")
        return path

    def site(self, slugs):
        root = self.path("site")
        for slug in slugs:
            d = os.path.join(root, *slug.strip("/").split("/"))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(page(slug))
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page("главная"))
        pages, _ = core.load_pages(root, SITE)
        return pages

    def indexed(self, name, text):
        return doctor.read_indexed(self.write(name, text), SITE, index_status=True)["urls"]


class TestIndexExports(Case):
    def test_xlsx_metadata_issue_excludes_the_pages(self):
        path = self.path("gsc.xlsx")
        xlsx(path, [[["URL", "Last crawled"]] + [[u, "2026-11-01"] for u in URLS],
                    [["Property", "Value"], ["Issue", "Crawled - currently not indexed"]]])
        got = doctor.read_sources([f"google={path}"], SITE)
        self.assertNotIn("google", got["by_engine"])
        self.assertEqual(len(got["excluded"]["google"]), 4)

    def test_xlsx_without_issue_stays_indexed(self):
        path = self.path("gsc.xlsx")
        xlsx(path, [[["URL", "Clicks"]] + [[u, "3"] for u in URLS]])
        self.assertEqual(len(doctor.read_sources([f"google={path}"], SITE)["by_engine"]["google"]), 4)

    def test_status_header_spellings(self):
        for header in ("coverageState", "coverage_state", "Coverage Status", "Abdeckung"):
            got = self.indexed("a.csv", f"URL,{header}\n{URLS[0]},Submitted and indexed\n"
                                        f"{URLS[1]},Crawled - currently not indexed\n")
            self.assertEqual(got, [URLS[0]], header)

    def test_api_json_coverage_state(self):
        rows = [{"url": URLS[0], "coverageState": "Submitted and indexed"},
                {"url": URLS[1], "coverageState": "URL is unknown to Google"}]
        self.assertEqual(self.indexed("api.json", json.dumps(rows)), [URLS[0]])

    def test_negated_phrasings_are_not_indexed(self):
        for status in ("Not yet indexed", "Never indexed", "No longer indexed",
                       "Indexed — No", "Indexed – no", "Indexed / No", "Not\xa0indexed",
                       "Crawled\xa0-\xa0currently\xa0not\xa0indexed"):
            self.assertFalse(doctor._is_indexed_status(status), status)
        for status in ("Indexed", "Indexed, no issues", "Indexed - not submitted in sitemap",
                       "Submitted and indexed", "Indexed: Yes"):
            self.assertTrue(doctor._is_indexed_status(status), status)

    def test_excel_sep_line(self):
        got = self.indexed("sep.csv", f"sep=;\nURL;Coverage\n{URLS[0]};Submitted and indexed\n"
                                      f"{URLS[1]};Crawled - currently not indexed\n")
        self.assertEqual(got, [URLS[0]])

    def test_title_line_above_the_table(self):
        got = self.indexed("pre.csv", f"Pages report\n\nURL,Coverage\n{URLS[0]},Submitted and indexed\n"
                                      f"{URLS[1]},Crawled - currently not indexed\n")
        self.assertEqual(got, [URLS[0]])

    def test_list_with_header_and_comma_in_url_is_still_a_list(self):
        rows = sources._rows_from_text(f"URL\n{SITE}/a/?x=1,2\n{SITE}/b/\n")
        self.assertEqual(rows, [["URL"], [f"{SITE}/a/?x=1,2"], [f"{SITE}/b/"]])

    def test_http_code_with_reason_is_not_an_index_verdict(self):
        got = self.indexed("s.csv", f"URL,Status\n{URLS[0]},200 OK\n{URLS[1]},301 Moved Permanently\n")
        self.assertEqual(got, URLS[:2])

    def test_unlabelled_drilldown_zip_is_google(self):
        path = self.drilldown("demo.example-Coverage-Drilldown-2026-11-10.zip",
                              "Issue", "Crawled - currently not indexed")
        got = doctor.read_sources([path], SITE)
        self.assertEqual(got["unlabeled"], [])
        self.assertEqual(got["by_source"], {})
        self.assertEqual(len(got["excluded"]["google"]), 4)

    def test_localized_issue_keys(self):
        for key, issue in (("Probleem", "Gecrawld - momenteel niet geïndexeerd"),
                           ("问题", "已抓取 - 尚未编入索引"),
                           ("Sorun", "Tarandı - şu anda dizine eklenmedi"),
                           ("문제", "크롤링됨 - 현재 색인이 생성되지 않음")):
            got = doctor.read_sources([f"google={self.drilldown('x.zip', key, issue)}"], SITE)
            self.assertNotIn("google", got["by_engine"], key)

    def test_localized_indexed_issue_stays_indexed(self):
        for key, issue in (("Problem", "Indexiert, obwohl durch robots.txt-Datei blockiert"),
                           ("Probleem", "Geïndexeerd, hoewel geblokkeerd door robots.txt"),
                           ("Sorun", "robots.txt tarafından engellenmiş olsa da dizine eklendi")):
            got = doctor.read_sources([f"google={self.drilldown('x.zip', key, issue)}"], SITE)
            self.assertEqual(len(got["by_engine"]["google"]), 4, key)

    def test_german_status_column(self):
        got = self.indexed("de.csv", f"URL,Status\n{URLS[0]},Gesendet und indexiert\n"
                                     f"{URLS[1]},Indexiert und nicht in Sitemap gesendet\n"
                                     f"{URLS[2]},Gecrawlt – zurzeit nicht indexiert\n")
        self.assertEqual(got, URLS[:2])

    def test_performance_headers_in_more_languages(self):
        pages = self.site(["rent/berlin"])
        for header in ("Nejčastější stránky,Kliknutí,Zobrazení,CTR,Pozice",
                       "Suosituimmat sivut,Klikkaukset,Näyttökerrat,CTR,Sijainti",
                       "Leggyakoribb oldalak,Kattintások,Megjelenések,CTR,Pozíció",
                       "Κορυφαίες σελίδες,Κλικ,Εμφανίσεις,CTR,Θέση",
                       "Populære sider,Klik,Visninger,CTR,Placering",
                       "Pagini principale,Clicuri,Afișări,CTR,Poziție"):
            path = self.write("perf.csv", header + f'\n{SITE}/rent/berlin/,3,500,"0,6%","12,3"\n')
            got = doctor.near_page_one([f"google={path}"], pages, SITE)
            self.assertEqual([r["position"] for r in got], [12.3], header)


class TestLogs(Case):
    def logs(self, lines, name="a.log"):
        return crawlers.read_logs([self.write(name, "\n".join(lines) + "\n")], SITE)

    def test_dotted_slug_without_slash_is_a_page(self):
        self.assertTrue(crawlers._is_page("/rent/st.louis"))
        self.assertTrue(crawlers._is_page("/docs/v1.2"))
        self.assertFalse(crawlers._is_page("/static/app.css"))
        pages = self.site(["rent/st.louis"])
        cov = crawlers.coverage(pages, self.logs([combined("/rent/st.louis", 200, USER_UA)]))
        self.assertEqual(cov["fetched"][crawlers.AI_USER], [f"{SITE}/rent/st.louis/"])

    def test_403s_after_one_200_are_listed(self):
        pages = self.site(["rent/berlin", "rent/munich"])
        cov = crawlers.coverage(pages, self.logs(
            [combined("/rent/berlin/")] + [combined("/rent/berlin/", 403)] * 5
            + [combined("/rent/munich/", 403), combined("/rent/munich/")]))
        self.assertEqual([e["url"] for e in cov["errors"]], [f"{SITE}/rent/berlin/"])
        self.assertEqual(cov["bots"][0]["errors"], 1)

    def test_truncated_gzip(self):
        good = self.path("good.log.gz")
        with gzip.open(good, "wt", encoding="utf-8") as fh:
            for i in range(400):
                fh.write(combined(f"/rent/x{i}/") + "\n")
        with open(good, "rb") as fh:
            data = fh.read()
        trunc = self.path("trunc.log.gz")
        with open(trunc, "wb") as fh:
            fh.write(data[:len(data) // 2])
        logs = crawlers.read_logs([trunc], SITE)
        self.assertTrue(logs["broken"])
        cov = crawlers.coverage(self.site(["rent/x1"]), logs)
        self.assertTrue(any("обрезан" in n for n in cov["notes"]), cov["notes"])
        with open(trunc, "wb") as fh:
            fh.write(data[:30])
        with self.assertRaises(core.SourceError) as ctx:
            crawlers.read_logs([trunc], SITE)
        self.assertIn("trunc.log.gz", str(ctx.exception))
        plain = self.write("plain.log.gz", combined("/a/") + "\n")
        with self.assertRaises(core.SourceError) as ctx:
            crawlers.read_logs([plain], SITE)
        self.assertIn("plain.log.gz", str(ctx.exception))

    def test_malformed_json_lines_are_skipped(self):
        self.assertEqual(crawlers.parse_line('{"path":"/a/","status":1e400,"ua":"x"}')["status"], 0)
        self.assertEqual(crawlers.parse_line("{" + '"a":' + "[" * 100000), {})

    def test_more_json_formats(self):
        gcp = {"httpRequest": {"requestMethod": "GET", "requestUrl": f"{SITE}/rent/berlin/",
                               "status": 403, "userAgent": SEARCH_UA, "remoteIp": "203.0.113.7"}}
        caddy = {"level": "info", "request": {"remote_ip": "203.0.113.7", "method": "GET",
                                              "host": "demo.example", "uri": "/rent/berlin/",
                                              "headers": {"User-Agent": [SEARCH_UA]}},
                 "status": 403}
        nginx = {"remote_addr": "203.0.113.7", "request": "GET /rent/berlin/ HTTP/1.1",
                 "status": "403", "http_user_agent": SEARCH_UA}
        for record in (gcp, caddy, nginx):
            hit = crawlers.parse_line(json.dumps(record))
            self.assertEqual((hit["status"], hit["ua"], hit["ip"]), (403, SEARCH_UA, "203.0.113.7"))
            self.assertTrue(hit["target"].endswith("/rent/berlin/"))

    def test_log_level_status_does_not_hide_http_status(self):
        hit = crawlers.parse_line(json.dumps({"status": "info", "http": {
            "url": "/rent/berlin/", "method": "GET", "status_code": 403, "user_agent": SEARCH_UA}}))
        self.assertEqual(hit["status"], 403)

    def test_robots_closed_bot(self):
        pages = self.site(["rent/berlin"])
        robots = aeo.read_robots(self.write("robots.txt", "User-agent: *\nAllow: /\n\n"
                                                          "User-agent: OAI-SearchBot\nDisallow: /\n"))
        cov = crawlers.coverage(pages, self.logs([combined("/rent/berlin/", 403)] * 6), robots=robots)
        self.assertFalse(any("хотя robots.txt" in n for n in cov["notes"]), cov["notes"])
        self.assertTrue(any("закрыты дважды" in n for n in cov["notes"]), cov["notes"])
        cov = crawlers.coverage(pages, self.logs([combined("/rent/berlin/")]), robots=robots)
        self.assertTrue(any("подделан" in n for n in cov["notes"]), cov["notes"])
        open_robots = aeo.read_robots(self.write("robots.txt", "User-agent: *\nAllow: /\n"))
        cov = crawlers.coverage(pages, self.logs([combined("/rent/berlin/", 403)] * 6),
                                robots=open_robots)
        self.assertTrue(any("хотя robots.txt" in n for n in cov["notes"]), cov["notes"])
        self.assertFalse(any("подделан" in n for n in cov["notes"]), cov["notes"])

    def test_robots_txt_5xx_is_reported(self):
        pages = self.site(["rent/berlin"])
        cov = crawlers.coverage(pages, self.logs([combined("/robots.txt", 503)] * 3
                                                 + [combined("/rent/berlin/")]))
        self.assertTrue(any("503" in n for n in cov["notes"]), cov["notes"])
        cov = crawlers.coverage(pages, self.logs([combined("/robots.txt", 200)] * 3
                                                 + [combined("/rent/berlin/")]))
        self.assertFalse(any("5xx" in n for n in cov["notes"]), cov["notes"])

    def test_amazonbot_is_not_ai_search(self):
        self.assertEqual(crawlers.identify("Mozilla/5.0 (compatible; Amazonbot/0.1)")[2],
                         crawlers.TRAINING)
        pages = self.site(["rent/berlin"])
        cov = crawlers.coverage(pages, self.logs(
            [combined("/rent/berlin/", ua="Mozilla/5.0 (compatible; Amazonbot/0.1)")]))
        self.assertEqual(cov["ai_fetched_count"], 0)
        self.assertTrue(any("нет ни одного бота ИИ-поиска" in n for n in cov["notes"]))

    def test_html_report_lists_bot_errors(self):
        pages = self.site(["rent/berlin"])
        cov = crawlers.coverage(pages, self.logs([combined("/rent/berlin/", 403, USER_UA)]))
        html = report._crawlers_html(cov)
        self.assertIn(f"{SITE}/rent/berlin/", html)
        self.assertIn("403", html)

    def test_vhost_combined(self):
        hit = crawlers.parse_line(combined("/rent/berlin/", 403, prefix="staging.demo.example:443 "))
        self.assertEqual((hit["target"], hit["status"], hit["host"], hit["ip"]),
                         ("/rent/berlin/", 403, "staging.demo.example", "203.0.113.7"))
        self.assertEqual(crawlers.parse_line(combined("/a/"))["host"], "")
        ipv6 = combined("/a/").replace("203.0.113.7", "2001:db8::1")
        self.assertEqual(crawlers.parse_line(ipv6)["ip"], "2001:db8::1")


if __name__ == "__main__":
    unittest.main()
