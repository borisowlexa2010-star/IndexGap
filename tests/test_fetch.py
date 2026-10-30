# -*- coding: utf-8 -*-
"""
`indexgap fetch`: живой сайт → каталог, который читает `check`.

Сайт поднимается здесь же, на 127.0.0.1: тесты в сеть не ходят, и это
проверяет `nonetwork`. Главное свойство — круг замыкается: адреса, под
которыми страницы скачаны, это ровно те адреса, которые `load_pages` видит
в скачанном каталоге. Иначе каждая страница в отчёте стояла бы не под своим
адресом, и сверка с sitemap врала бы.
"""

import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, fetch, i18n


def html(title, links=(), words=160):
    body = " ".join(f"слово{i}" for i in range(words))
    refs = "".join(f'<a href="{href}">ссылка</a> ' for href in links)
    return (f"<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            f"<title>{title}</title></head><body><main><h1>{title}</h1>"
            f"<p>{body}</p><p>{refs}</p></main></body></html>").encode("utf-8")


CYR = "/%D0%BA%D0%B8%D1%80%D0%B8%D0%BB%D0%BB%D0%B8%D1%86%D0%B0/"


def routes(base):
    """Путь запроса как он приходит на сервер → (код, заголовки, тело)."""
    page = {"Content-Type": "text/html; charset=utf-8"}
    pages = ["/", "/a/b/", "/flat", "/doc.html", "/v2.0", CYR, "/page.php",
             "/old", "/gone/", "/err/", "/file.pdf", "/private/x/",
             "/offsite", "/big/", "/loop"]
    sitemap_pages = "".join(f"<url><loc>{base}{p}</loc></url>" for p in pages[:8])
    sitemap_more = "".join(f"<url><loc>{base}{p}</loc></url>" for p in pages[8:])
    return {
        "/robots.txt": (200, {"Content-Type": "text/plain"},
                        (f"User-agent: *\nDisallow: /private/\n\n"
                         f"Sitemap: {base}/sitemap.xml\n").encode()),
        "/sitemap.xml": (200, {"Content-Type": "application/xml"}, (
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<sitemap><loc>{base}/sitemaps/pages.xml</loc></sitemap>"
            f"<sitemap><loc>{base}/sitemaps/more.xml.gz</loc></sitemap>"
            "</sitemapindex>").encode()),
        "/sitemaps/pages.xml": (200, {"Content-Type": "application/xml"}, (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + sitemap_pages + "</urlset>").encode()),
        "/sitemaps/more.xml.gz": (200, {"Content-Type": "application/gzip"}, gzip.compress((
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + sitemap_more + "</urlset>").encode())),
        "/": (200, page, html("Главная", ["/a/b/", "/doc.html"])),
        "/a/b/": (200, dict(page, **{"X-Robots-Tag": "noindex"}), html("Закрытая")),
        "/flat": (200, page, html("Плоская")),
        "/doc.html": (200, page, html("Документ")),
        "/v2.0": (200, page, html("Версия")),
        CYR: (200, page, html("Кириллица")),
        "/page.php": (200, page, html("PHP")),
        "/old": (301, {"Location": "/new/"}, b""),
        "/new/": (200, page, html("Новая")),
        "/gone/": (404, page, html("Нет")),
        "/err/": (500, page, b"oops"),
        "/file.pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4"),
        "/private/x/": (200, page, html("Секрет")),
        "/offsite": (302, {"Location": "http://example.org/away"}, b""),
        "/big/": (200, page, html("Большая", words=10) + b"<!--" + b"x" * (2 * 1024 * 1024 + 10) + b"-->"),
        "/loop": (302, {"Location": "/loop"}, b""),
    }


class Server:
    def __init__(self, make=routes):
        self.log, self.agents = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.log.append(self.path)
                owner.agents.append(self.headers.get("User-Agent") or "")
                table = owner.routes
                status, headers, body = table.get(self.path, (404, {}, b"not found"))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.routes = make(self.base)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def pages_requested(self):
        return [p for p in self.log if not p.startswith(("/robots.txt", "/sitemap"))]


class FetchCase(unittest.TestCase):
    make = staticmethod(routes)

    def setUp(self):
        self.server = Server(self.make)
        self.addCleanup(self.server.close)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.out = os.path.join(self.dir, "live")

    def run_cli(self, *extra, out=None):
        argv = ["fetch", self.server.base, "--out-dir", out or self.out,
                "--delay", "0", *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            code = cli.main(argv)
        return code, stdout.getvalue() + stderr.getvalue()

    def manifest(self):
        with open(os.path.join(self.out, "fetch.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def record(self, path):
        url = self.server.base + path
        found = [r for r in self.manifest()["pages"] if r["url"] == url]
        self.assertEqual(len(found), 1, url)
        return found[0]


class TestRoundTrip(FetchCase):
    def test_fetched_urls_are_the_urls_load_pages_reports(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        saved = {r["final_url"] for r in self.manifest()["pages"] if r.get("file")}
        self.assertIn(self.server.base + "/new/", saved)
        self.assertIn(self.server.base + "/flat", saved)
        self.assertIn(self.server.base + "/page.php", saved)
        pages, problems = core.load_pages(self.out, self.server.base + "/")
        self.assertEqual({p.url for p in pages}, saved, problems)
        # Единственное, что load_pages говорит, — правило из _headers.
        self.assertEqual([p for p in problems if "_headers" not in p], [])

    def test_keys_match_even_without_the_manifest(self):
        """fetch.json даёт точную форму адреса; без него сходятся хотя бы ключи."""
        self.run_cli()
        saved = {core.url_key(r["final_url"]) for r in self.manifest()["pages"]
                 if r.get("file")}
        os.remove(os.path.join(self.out, "fetch.json"))
        pages, _ = core.load_pages(self.out, self.server.base + "/")
        self.assertEqual({p.key for p in pages}, saved)

    def test_the_mapping(self):
        cases = {
            "https://e.com/": "index.html",
            "https://e.com/a/b/": "a/b/index.html",
            "https://e.com/a/b": "a/b.html",
            "https://e.com/a/b.html": "a/b.html",
            "https://e.com/a/b.htm": "a/b.htm",
            "https://e.com/v2.0": "v2.0.html",
            "https://e.com/p.php": "p.php.html",
            "https://e.com/%D0%BA/": "к/index.html",
            "https://e.com": "index.html",
        }
        for url, rel in cases.items():
            with self.subTest(url=url):
                self.assertEqual(fetch.url_to_file(url), (rel, ""))

    def test_unsafe_or_unreadable_paths_are_not_files(self):
        for url in ("https://e.com/../etc/passwd", "https://e.com/a/%2e%2e/b",
                    "https://e.com/.git/config", "https://e.com/node_modules/x/",
                    "https://e.com/search?q=1", "https://e.com/a%2Fb",
                    "https://e.com/a//b", "https://e.com/404.html",
                    "https://e.com/x%00y"):
            with self.subTest(url=url):
                rel, reason = fetch.url_to_file(url)
                self.assertEqual(rel, "")
                self.assertTrue(reason)


class TestUnits(unittest.TestCase):
    def test_charset_only_in_the_header_is_carried_into_the_file(self):
        body = "<html><head><title>Тест</title></head><body>Привет</body></html>".encode("cp1251")
        out = fetch._as_declared(body, "text/html; charset=windows-1251")
        self.assertEqual(out.decode("utf-8"), body.decode("cp1251"))
        # Объявлено в самой странице — файл не трогается.
        meta = b'<meta charset="windows-1251">' + body
        self.assertEqual(fetch._as_declared(meta, "text/html; charset=windows-1251"), meta)
        self.assertEqual(fetch._as_declared(body, "text/html"), body)

    def test_someone_elses_fetch_json_does_not_move_pages(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "flat.html"), "wb") as fh:
            fh.write(html("Плоская"))
        entry = {"file": "flat.html", "final_url": "https://e.com/elsewhere"}
        for data, expected in (({"pages": [entry]}, "https://e.com/flat.html"),
                               ({"generator": "indexgap fetch", "pages": [entry]},
                                "https://e.com/elsewhere")):
            with open(os.path.join(root, "fetch.json"), "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            pages, _ = core.load_pages(root, "https://e.com/")
            self.assertEqual([p.url for p in pages], [expected])

    def test_www_is_the_same_site_another_subdomain_is_not(self):
        site = "https://example.com/"
        self.assertTrue(fetch.same_site("https://www.example.com/a", site))
        self.assertTrue(fetch.same_site("http://example.com/a", site))
        self.assertFalse(fetch.same_site("https://cdn.example.com/a", site))
        self.assertFalse(fetch.same_site("https://example.com.evil.org/a", site))
        self.assertFalse(fetch.same_site("ftp://example.com/a", site))


class TestFacts(FetchCase):
    def test_robots_is_respected_and_counted(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertNotIn("/private/x/", self.server.log)
        self.assertIn(self.server.base + "/private/x/", self.manifest()["skipped_robots"])
        self.assertIn("robots.txt: 1", out)

    def test_x_robots_tag_becomes_headers_file_that_check_reads(self):
        self.run_cli()
        with open(os.path.join(self.out, "_headers"), encoding="utf-8") as fh:
            self.assertIn("/a/b/\n  X-Robots-Tag: noindex", fh.read())
        pages, _ = core.load_pages(self.out, self.server.base + "/")
        closed = {p.url for p in pages if p.noindex}
        self.assertEqual(closed, {self.server.base + "/a/b/"})

    def test_statuses_and_redirects_go_to_the_manifest(self):
        self.run_cli()
        old = self.record("/old")
        self.assertEqual(old["status"], 200)
        self.assertEqual(old["final_url"], self.server.base + "/new/")
        self.assertEqual(old["redirects"], [{"url": self.server.base + "/old", "status": 301}])
        self.assertTrue(old["file"])
        for path, status in (("/gone/", 404), ("/err/", 500)):
            rec = self.record(path)
            self.assertEqual(rec["status"], status)
            self.assertIsNone(rec["file"])
        pdf = self.record("/file.pdf")
        self.assertEqual(pdf["content_type"], "application/pdf")
        self.assertIsNone(pdf["file"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "gone")))

    def test_redirect_to_another_host_is_recorded_not_followed(self):
        # nonetwork уронил бы тест, уйди запрос на example.org.
        self.run_cli()
        rec = self.record("/offsite")
        self.assertEqual(rec["status"], 302)
        self.assertEqual(rec["final_url"], "http://example.org/away")
        self.assertIsNone(rec["file"])

    def test_a_redirect_loop_ends(self):
        self.run_cli()
        rec = self.record("/loop")
        self.assertIsNone(rec["file"])
        self.assertLessEqual(self.server.log.count("/loop"), fetch.MAX_REDIRECTS + 1)

    def test_over_two_megabytes_is_recorded(self):
        code, out = self.run_cli()
        rec = self.record("/big/")
        self.assertTrue(rec["over_2mb"])
        self.assertTrue(rec["file"])
        self.assertFalse(self.record("/flat")["over_2mb"])
        self.assertIn("2 МБ: 1", out)

    def test_robots_and_sitemaps_are_saved_for_check(self):
        self.run_cli()
        for rel in ("robots.txt", "sitemap.xml", "sitemaps/pages.xml", "sitemaps/more.xml.gz"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, rel)), rel)

    def test_summary_names_the_next_command_and_it_works_offline(self):
        code, out = self.run_cli()
        sitemap = os.path.join(self.out, "sitemap.xml")
        self.assertIn(f"indexgap check {self.out} --site {self.server.base}/ "
                      f"--sitemap {sitemap}", out)
        before = len(self.server.log)
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout):
            code = cli.main(["check", self.out, "--site", self.server.base + "/",
                             "--sitemap", sitemap,
                             "--out", os.path.join(self.dir, "r.html")])
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertNotIn("не прочитан", stdout.getvalue())
        # Сверка шла по скачанным файлам: на сервер — ни одного запроса.
        self.assertEqual(self.server.log[before:], [])
        with open(os.path.join(self.dir, "r.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertTrue(data["robots"])

    def test_the_package_introduces_itself(self):
        self.run_cli("--limit", "2")
        self.assertTrue(self.server.agents)
        for agent in self.server.agents:
            self.assertTrue(agent.startswith("indexgap/"), agent)


class TestLimits(FetchCase):
    def test_limit_is_never_exceeded(self):
        code, out = self.run_cli("--limit", "3", "--jobs", "4")
        self.assertEqual(code, 0, out)
        self.assertLessEqual(len(self.server.pages_requested()), 3 + fetch.MAX_REDIRECTS)
        self.assertEqual(len(self.manifest()["pages"]), 3)
        self.assertGreater(self.manifest()["over_limit"], 0)

    def test_zero_needs_all(self):
        code, out = self.run_cli("--limit", "0")
        self.assertEqual(code, 2)
        self.assertIn("--all", out)
        self.assertEqual(self.server.log, [])
        code, out = self.run_cli("--limit", "0", "--all", out=os.path.join(self.dir, "all"))
        self.assertEqual(code, 0, out)

    def test_all_and_a_limit_contradict(self):
        code, _ = self.run_cli("--limit", "10", "--all")
        self.assertEqual(code, 2)

    def test_bad_jobs_or_delay_are_refused(self):
        for extra in (("--jobs", "0"), ("--jobs", "100"), ("--delay", "-1"), ("--limit", "-5")):
            with self.subTest(extra=extra):
                code, _ = self.run_cli(*extra)
                self.assertEqual(code, 2)

    def test_a_sitemap_on_another_host_is_refused(self):
        code, out = self.run_cli("--sitemap", "https://example.org/sitemap.xml")
        self.assertEqual(code, 2)
        self.assertIn("example.org", out)

    def test_a_non_empty_out_dir_is_refused(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "keep.txt"), "w", encoding="utf-8") as fh:
            fh.write("мой файл")
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(self.server.log, [])
        self.assertTrue(os.path.isfile(os.path.join(self.out, "keep.txt")))

    def test_a_site_without_scheme_is_refused(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stderr", stdout):
            code = cli.main(["fetch", "example.com", "--out-dir", self.out])
        self.assertEqual(code, 2)
        self.assertIn("https://example.com", stdout.getvalue())

    def test_explicit_sitemap_wins(self):
        code, out = self.run_cli("--sitemap", self.server.base + "/sitemaps/pages.xml")
        self.assertEqual(code, 0, out)
        self.assertNotIn("/sitemap.xml", self.server.log)
        self.assertEqual(len(self.manifest()["pages"]), 8)
        self.assertIn("--sitemap " + os.path.join(self.out, "sitemaps", "pages.xml"), out)


def no_robots(base):
    table = routes(base)
    del table["/robots.txt"]
    table["/sitemap.xml"] = (200, {"Content-Type": "application/xml"}, (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{base}/</loc></url><url><loc>{base}/private/x/</loc></url>"
        "</urlset>").encode())
    return table


class TestWithoutRobots(FetchCase):
    make = staticmethod(no_robots)

    def test_falls_back_to_sitemap_xml_and_fetches_everything(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertIn("/sitemap.xml", self.server.log)
        self.assertIn("/private/x/", self.server.log)
        self.assertFalse(os.path.exists(os.path.join(self.out, "robots.txt")))
        self.assertEqual(self.manifest()["robots"]["status"], 404)


def robots_down(base):
    table = routes(base)
    table["/robots.txt"] = (503, {}, b"busy")
    return table


class TestRobotsDown(FetchCase):
    make = staticmethod(robots_down)

    def test_a_failing_robots_stops_the_crawl(self):
        """5xx на robots.txt Google читает как «не обходить» — и пакет тоже."""
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("503", out)
        self.assertEqual(self.server.pages_requested(), [])


def nothing_saved(base):
    table = routes(base)
    table["/sitemap.xml"] = (200, {"Content-Type": "application/xml"}, (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{base}/gone/</loc></url></urlset>").encode())
    return table


class TestNothingSaved(FetchCase):
    make = staticmethod(nothing_saved)

    def test_nothing_to_check_is_exit_one(self):
        code, out = self.run_cli()
        self.assertEqual(code, 1, out)
        self.assertIn("404", out)


def no_sitemap(base):
    table = routes(base)
    table["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow:\n")
    del table["/sitemap.xml"]
    return table


class TestNoSitemap(FetchCase):
    make = staticmethod(no_sitemap)

    def test_a_missing_sitemap_is_an_input_error_and_leaves_nothing_behind(self):
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("/sitemap.xml", out)
        self.assertIn("404", out)
        self.assertEqual(self.server.pages_requested(), [])
        # robots.txt успел записаться — и убран: повтор не упрётся в «не пуст».
        self.assertFalse(os.path.exists(self.out))
        code, _ = self.run_cli("--sitemap", self.server.base + "/sitemaps/pages.xml")
        self.assertEqual(code, 0)


class TestEnglish(FetchCase):
    def tearDown(self):
        os.environ["INDEXGAP_LANG"] = "ru"
        i18n.set_lang("ru")

    def test_output_is_english_only(self):
        import re
        code, out = self.run_cli("--lang", "en")
        self.assertEqual(code, 0, out)
        # Кириллица из адреса страницы — не текст пакета.
        self.assertEqual(re.findall(r"[А-Яа-яЁё]", out.replace("кириллица", "")), [], out)

    def test_crawl_output_is_english_only(self):
        import re
        code, out = self.run_cli("--lang", "en", "--crawl")
        self.assertEqual(code, 0, out)
        self.assertEqual(re.findall(r"[А-Яа-яЁё]", out.replace("кириллица", "")), [], out)



class ConsoleSafety(unittest.TestCase):
    def test_remote_text_cannot_inject_ci_commands(self):
        from indexgap import fetch
        self.assertEqual(fetch._safe("/a\n::error::x\x1b[31m"), "/a%0A::error::x%1B[31m")


class WindowsCommand(unittest.TestCase):
    def test_a_hostile_sitemap_name_never_reaches_the_command(self):
        from indexgap import fetch
        with mock.patch.object(fetch.os, "name", "nt"):
            line = fetch.next_command("C:\\live", {
                "site": "https://example.com/",
                "root_sitemaps": ["a&calc.xml", "b%PATH%.xml", "c d.xml", "sitemap.xml",
                                  "e\u201d;calc.xml", "f.xml\n&calc"]})
        self.assertNotIn("calc", line)
        self.assertNotIn("%PATH%", line)
        self.assertRegex(line, r'"C:\\live.c d\.xml"')
        self.assertIn("sitemap.xml", line)
        with mock.patch.object(fetch.os, "name", "nt"):
            line = fetch.next_command("C:\\Разработка\\live", {
                "site": "https://example.com/", "root_sitemaps": ["sitemap.xml"]})
        self.assertIn('"C:\\Разработка\\live"', line)
        self.assertRegex(line, r'--sitemap "C:\\Разработка\\live.sitemap\.xml"')
        self.assertIn("--site https://example.com/", line)


# ── --crawl: обход по ссылкам ────────────────────────────────────────────────

def crawl_site(base):
    """
    /, /a/, /orphan/ — в sitemap; /b/, /c/, /d/ — только по ссылкам;
    /missing/ — битая ссылка; /orphan/ — в sitemap, но на неё не ссылается никто.
    """
    page = {"Content-Type": "text/html; charset=utf-8"}
    sitemap = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/", "/a/", "/orphan/"))
    return {
        "/robots.txt": (200, {"Content-Type": "text/plain"},
                        (f"User-agent: *\nDisallow: /private/\n\n"
                         f"Sitemap: {base}/sitemap.xml\n").encode()),
        "/sitemap.xml": (200, {"Content-Type": "application/xml"}, (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + sitemap + "</urlset>").encode()),
        "/": (200, page, html("Главная", [
            "/a/", "b/", "/private/p/", "/search?q=1", "http://example.org/x",
            "mailto:a@b.c", "/img.png", "#top", "/missing/"])),
        "/a/": (200, page, html("А", ["/", "/b/", "../c/"])),
        "/b/": (200, page, html("Б", ["/a", base + "/a/#x"])),
        "/c/": (200, page, html("В", ["/d/"])),
        "/d/": (200, page, html("Г")),
        "/orphan/": (200, page, html("Сирота")),
        "/private/p/": (200, page, html("Секрет")),
        "/search?q=1": (200, page, html("Поиск")),
        "/img.png": (200, {"Content-Type": "image/png"}, b"\x89PNG"),
    }


class TestCrawl(FetchCase):
    make = staticmethod(crawl_site)

    def urls(self):
        return [r["url"][len(self.server.base):] for r in self.manifest()["pages"]]

    def test_default_stays_sitemap_only(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.urls(), ["/", "/a/", "/orphan/"])
        self.assertNotIn("/b/", self.server.log)
        self.assertEqual({r["found_by"] for r in self.manifest()["pages"]}, {"sitemap"})

    def test_links_are_followed_breadth_first(self):
        code, out = self.run_cli("--crawl", "--jobs", "4")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.urls(), ["/", "/a/", "/orphan/", "/b/", "/missing/", "/c/", "/d/"])
        found = {r["url"][len(self.server.base):]: r["found_by"] for r in self.manifest()["pages"]}
        self.assertEqual(found, {"/": "sitemap", "/a/": "sitemap", "/orphan/": "sitemap",
                                 "/b/": "link", "/missing/": "link", "/c/": "link",
                                 "/d/": "link"})
        self.assertEqual(self.record("/d/")["linked_from"], self.server.base + "/c/")
        self.assertEqual(self.record("/missing/")["status"], 404)

    def test_what_is_never_requested(self):
        self.run_cli("--crawl")
        for path in ("/private/p/", "/search?q=1", "/img.png"):
            self.assertNotIn(path, self.server.log)
        # /a и /a/#x — та же страница, что /a/: второй раз не запрашивается.
        self.assertEqual(self.server.log.count("/a/"), 1)
        self.assertNotIn("/a", self.server.log)
        self.assertIn(self.server.base + "/private/p/", self.manifest()["skipped_robots"])

    def test_summary_names_link_only_pages_and_orphans(self):
        code, out = self.run_cli("--crawl")
        data = self.manifest()
        base = self.server.base
        self.assertEqual(data["link_only"], [base + "/b/", base + "/c/", base + "/d/"])
        self.assertEqual(data["orphan_candidates"], [base + "/orphan/"])
        self.assertIn("только по ссылкам: 3", out)
        self.assertIn("ни одной ссылки: 1", out)
        self.assertIn(base + "/orphan/", out)
        self.assertIn("битые ссылки: 1", out)

    def test_the_result_round_trips_into_check(self):
        self.run_cli("--crawl")
        saved = {r["final_url"] for r in self.manifest()["pages"] if r.get("file")}
        pages, _ = core.load_pages(self.out, self.server.base + "/")
        self.assertEqual({p.url for p in pages}, saved)

    def test_limit_counts_every_request(self):
        code, out = self.run_cli("--crawl", "--limit", "4")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.urls(), ["/", "/a/", "/orphan/", "/b/"])
        self.assertEqual(self.manifest()["over_limit"], 2)
        # Обход неполный — про сирот сказано, что это оценка.
        self.assertIn("обход неполный", out)

    def test_output_is_deterministic(self):
        self.run_cli("--crawl", "--jobs", "8")
        first = self.urls()
        self.run_cli("--crawl", "--jobs", "1", out=os.path.join(self.dir, "again"))
        self.out = os.path.join(self.dir, "again")
        self.assertEqual(self.urls(), first)


def crawl_without_sitemap(base):
    table = crawl_site(base)
    table["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow:\n")
    del table["/sitemap.xml"]
    return table


class TestCrawlWithoutSitemap(FetchCase):
    make = staticmethod(crawl_without_sitemap)

    def test_crawl_needs_no_sitemap(self):
        code, out = self.run_cli("--crawl")
        self.assertEqual(code, 0, out)
        found = {r["url"][len(self.server.base):]: r["found_by"]
                 for r in self.manifest()["pages"]}
        # На главную ссылается /a/ — она найдена и по ссылке.
        self.assertEqual(found["/"], "link")
        self.assertEqual(found["/d/"], "link")
        self.assertNotIn("/orphan/", found)
        self.assertIn("/sitemap.xml", out)
        self.assertNotIn("ни одной ссылки", out)
        self.assertEqual(self.manifest()["orphan_candidates"], [])


# ── --render: страницы, которые рисует JavaScript ────────────────────────────

SHELL = (b'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>App</title>'
         b'<script type="module" src="/app.js"></script></head>'
         b'<body><div id="root"></div></body></html>')


def shell_site(base):
    page = {"Content-Type": "text/html; charset=utf-8"}
    sitemap = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/", "/slow/", "/fail/"))
    return {
        "/robots.txt": (200, {"Content-Type": "text/plain"},
                        f"User-agent: *\nDisallow:\nSitemap: {base}/sitemap.xml\n".encode()),
        "/sitemap.xml": (200, {"Content-Type": "application/xml"}, (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + sitemap + "</urlset>").encode()),
        "/": (200, page, SHELL),
        "/slow/": (200, page, SHELL),
        "/fail/": (200, page, SHELL),
        "/js-only/": (200, page, SHELL),
    }


# Поддельный браузер: печатает DOM, как `--dump-dom`, и пишет свои аргументы.
FAKE_BROWSER = r"""
import json, os, sys, time
url = sys.argv[-1]
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "argv.log"), "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
# Зависает, только когда тест об этом попросил: ждать таймаут в каждом тесте дорого.
if "/slow/" in url and os.path.exists(os.path.join(here, "hang")):
    time.sleep(30)
if "/fail/" in url:
    sys.exit(3)
words = " ".join("отрисовано%d" % i for i in range(160))
dom = ('<html lang="ru"><head><meta charset="utf-8"><title>Отрисовано</title></head>'
       '<body><main><h1>Отрисовано</h1><p>' + words + '</p>'
       '<a href="/js-only/">ещё</a></main></body></html>')
sys.stdout.buffer.write(dom.encode("utf-8"))
"""


class RenderCase(FetchCase):
    make = staticmethod(shell_site)

    def setUp(self):
        super().setUp()
        tools = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tools, True)
        script = os.path.join(tools, "browser.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(f"#!{sys.executable}\n" + FAKE_BROWSER)
        os.chmod(script, 0o755)
        self.argv_log = os.path.join(tools, "argv.log")
        self.hang = os.path.join(tools, "hang")
        if os.name == "nt":
            self.browser = os.path.join(tools, "browser.bat")
            with open(self.browser, "w", encoding="utf-8") as fh:
                fh.write(f'@"{sys.executable}" "{script}" %*\n')
        else:
            self.browser = script
        timeout = mock.patch.object(fetch, "RENDER_TIMEOUT", 3)
        timeout.start()
        self.addCleanup(timeout.stop)

    def calls(self):
        with open(self.argv_log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]


class TestRender(RenderCase):
    def test_the_rendered_dom_is_what_is_saved(self):
        code, out = self.run_cli("--render", "--browser", self.browser)
        self.assertEqual(code, 0, out)
        home = self.record("/")
        self.assertTrue(home["rendered"])
        # Факты ответа — о сыром HTML, а не о том, что нарисовал браузер.
        self.assertEqual(home["bytes"], len(SHELL))
        self.assertEqual(home["status"], 200)
        with open(os.path.join(self.out, "index.html"), encoding="utf-8") as fh:
            saved = fh.read()
        self.assertIn("Отрисовано", saved)
        self.assertNotIn('id="root"', saved)
        pages, _ = core.load_pages(self.out, self.server.base + "/")
        self.assertIn("Отрисовано", [p.title for p in pages])
        self.assertIn("Отрисовано браузером: 2 из 3", out)

    def test_the_browser_gets_an_argument_list_not_a_shell_line(self):
        self.run_cli("--render", "--browser", self.browser)
        call = [c for c in self.calls() if c[-1] == self.server.base + "/"][0]
        for flag in ("--headless=new", "--disable-gpu", "--dump-dom",
                     "--virtual-time-budget=5000"):
            self.assertIn(flag, call)
        self.assertEqual(call[-1], self.server.base + "/")

    def test_a_hanging_or_failing_browser_keeps_the_raw_html(self):
        open(self.hang, "w").close()
        started = time.monotonic()
        code, out = self.run_cli("--render", "--browser", self.browser)
        # Зависший браузер остановлен по таймауту, а не дождан до конца.
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(code, 0, out)
        self.assertIn("не уложился", self.record("/slow/")["render_error"])
        for path, rel in (("/slow/", "slow/index.html"), ("/fail/", "fail/index.html")):
            rec = self.record(path)
            self.assertFalse(rec["rendered"])
            self.assertTrue(rec["render_error"])
            with open(os.path.join(self.out, *rel.split("/")), "rb") as fh:
                self.assertEqual(fh.read(), SHELL)
        self.assertIn("не отрисованы", out)

    def test_render_and_crawl_find_links_that_only_javascript_draws(self):
        code, out = self.run_cli("--render", "--crawl", "--browser", self.browser)
        self.assertEqual(code, 0, out)
        rec = self.record("/js-only/")
        self.assertEqual(rec["found_by"], "link")
        self.assertTrue(rec["rendered"])

    def test_shells_get_a_hint_without_render(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertIn("3 страниц(ы) похожи на пустой JS-каркас", out)
        self.assertIn("--render", out)
        self.assertTrue(self.record("/")["js_shell"])
        self.assertEqual(self.manifest()["js_shells"], 3)

    def test_no_hint_when_rendered(self):
        code, out = self.run_cli("--render", "--browser", self.browser)
        self.assertNotIn("похожи на пустой JS-каркас", out)


class TestRenderRefusals(RenderCase):
    def test_without_a_browser_render_is_an_input_error(self):
        with mock.patch.object(fetch.shutil, "which", return_value=None), \
                mock.patch.object(fetch, "_known_browser_paths", return_value=[]):
            code, out = self.run_cli("--render")
        self.assertEqual(code, 2, out)
        self.assertIn("--browser", out)
        self.assertIn("Chromium", out)
        self.assertEqual(self.server.log, [])

    def test_a_missing_browser_path_is_refused(self):
        code, out = self.run_cli("--render", "--browser", os.path.join(self.dir, "nope"))
        self.assertEqual(code, 2, out)
        self.assertEqual(self.server.log, [])

    def test_browser_without_render_is_refused(self):
        code, out = self.run_cli("--browser", self.browser)
        self.assertEqual(code, 2, out)
        self.assertIn("--render", out)

    def test_found_on_path(self):
        with mock.patch.object(fetch.shutil, "which",
                               side_effect=lambda n: "/opt/x/chromium" if n == "chromium" else None):
            self.assertEqual(fetch.find_browser(None), "/opt/x/chromium")


class TestRenderUnits(unittest.TestCase):
    def test_only_http_urls_on_the_site_reach_the_browser(self):
        site = "https://example.com/"
        with mock.patch.object(fetch.subprocess, "Popen",
                               side_effect=AssertionError("браузер не должен запускаться")):
            for url in ("file:///etc/passwd", "https://evil.org/", "javascript:alert(1)",
                        "https://example.com/a b", "https://example.com/\n--x",
                        "--remote-debugging-port=9222"):
                with self.subTest(url=url):
                    dom, error = fetch.render("/bin/chrome", url, site)
                    self.assertIsNone(dom)
                    self.assertTrue(error)

    def test_no_sandbox_only_when_asked(self):
        self.assertNotIn("--no-sandbox", fetch.browser_args("/bin/chrome", "https://e.com/"))
        self.assertIn("--no-sandbox",
                      fetch.browser_args("/bin/chrome", "https://e.com/", no_sandbox=True))
        args = fetch.browser_args("/bin/chrome", "https://e.com/")
        self.assertEqual(args[0], "/bin/chrome")
        self.assertEqual(args[-1], "https://e.com/")

    def test_root_on_linux_must_opt_out_of_the_sandbox(self):
        with mock.patch.object(fetch, "needs_no_sandbox", return_value=True), \
                mock.patch.object(fetch, "find_browser", return_value="/bin/chrome"):
            with self.assertRaises(fetch.SourceError) as caught:
                fetch.run("https://e.com/", os.path.join(tempfile.mkdtemp(), "out"),
                          render_pages=True)
        self.assertIn("--browser-no-sandbox", str(caught.exception))

    def test_the_browser_may_only_reach_the_site(self):
        args = fetch.browser_args("/bin/chrome", "https://www.e.com/a/", site="https://e.com/")
        rules = next(a for a in args if a.startswith("--host-resolver-rules="))
        self.assertIn("MAP * ~NOTFOUND", rules)
        self.assertIn("EXCLUDE e.com", rules)
        self.assertIn("EXCLUDE www.e.com", rules)
        self.assertIn("--proxy-server=127.0.0.1:9", args)
        bypass = next(a for a in args if a.startswith("--proxy-bypass-list="))
        self.assertIn("<-loopback>", bypass)
        self.assertNotIn("169.254", bypass)
        self.assertIn("--force-webrtc-ip-handling-policy=disable_non_proxied_udp", args)

    def test_the_site_is_pinned_to_the_address_resolved_once(self):
        args = fetch.browser_args("/bin/chrome", "https://e.com/", site="https://e.com/",
                                  proxy_port=4321, pins={"e.com": "93.184.215.14"})
        rules = next(a for a in args if a.startswith("--host-resolver-rules="))
        self.assertIn("MAP e.com 93.184.215.14", rules)
        self.assertTrue(rules.endswith("MAP * ~NOTFOUND"))
        self.assertIn("--proxy-server=127.0.0.1:4321", args)
        self.assertEqual(fetch._pin_hosts("http://127.0.0.1:8000/"), {})

    def test_a_local_site_keeps_loopback_direct(self):
        # С `<-loopback>` Chromium не пускает напрямую и явно названный 127.0.0.1.
        args = fetch.browser_args("/bin/chrome", "http://127.0.0.1:8000/",
                                  site="http://127.0.0.1:8000/")
        bypass = next(a for a in args if a.startswith("--proxy-bypass-list="))
        self.assertEqual(bypass, "--proxy-bypass-list=127.0.0.1")

    def test_the_proxy_sink_closes_every_connection(self):
        import socket
        sink = fetch._Sink()
        try:
            conn = socket.create_connection(("127.0.0.1", sink.port), timeout=2)
            conn.settimeout(2)
            self.assertEqual(conn.recv(10), b"")
            conn.close()
        finally:
            sink.close()

    def test_a_batch_browser_gets_only_plain_urls(self):
        for url in ("https://e.com/a&calc/", "https://e.com/%PATH%/", "https://e.com/(x)/"):
            with self.subTest(url=url):
                dom, error = fetch.render("C:\\tools\\chrome.bat", url, "https://e.com/")
                self.assertIsNone(dom)
                self.assertTrue(error)


if __name__ == "__main__":
    unittest.main()
