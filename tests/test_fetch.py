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
        with open(os.path.join(self.out, "keep.txt"), "w") as fh:
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



class ConsoleSafety(unittest.TestCase):
    def test_remote_text_cannot_inject_ci_commands(self):
        from indexgap import fetch
        self.assertEqual(fetch._safe("/a\n::error::x\x1b[31m"), "/a%0A::error::x%1B[31m")

if __name__ == "__main__":
    unittest.main()
