# -*- coding: utf-8 -*-
"""
1.29 (g09): чтение sitemap в check/doctor и вывод команды sitemap.

* Индекс с диска не подменяет пропавший дочерний файл посторонним с тем же
  именем и не ходит за ним в сеть.
* Повтор дочернего файла в индексе — не «индекс ссылается сам на себя».
* Недочитанный sitemap и нарушения протокола (предел 50 000, пространство
  имён, относительные <loc>, lastmod, http/www вместо --site) попадают в
  JSON и HTML, а не только в консоль.
* sitemap не затирает чужой sitemap-N.xml, кодирует --public-prefix и хост
  IDN, понимает unavailable_after с датой RFC 822 и предупреждает о правилах
  хостинга, canonical-form, обвале числа адресов и robots.txt.
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
from indexgap import cli, doctor, publish

SITE = "https://demo.example"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def urlset(*locs, lastmod="", ns=NS):
    extra = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    return (f"<urlset {ns}>" + "".join(f"<url><loc>{u}</loc>{extra}</url>" for u in locs)
            + "</urlset>")


def index(*locs):
    return f"<sitemapindex {NS}>" + "".join(
        f"<sitemap><loc>{u}</loc></sitemap>" for u in locs) + "</sitemapindex>"


def page(title, body="Plain words about a small example topic for readers.", head=""):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{title}</title>{head}</head>'
            f'<body><main><h1>{title}</h1><p>{body}</p></main></body></html>')


def run(*argv):
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, printed.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-129g09-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def site(self, root, paths):
        for p in paths:
            write(os.path.join(root, p.strip("/"), "index.html") if p != "/"
                  else os.path.join(root, "index.html"), page(f"Page {p}"))


class TestReadSitemapIndex(Base):
    def test_missing_child_is_not_replaced_by_a_same_named_file(self):
        write(self.path("en", "sitemap.xml"), urlset(f"{SITE}/en/a/"))
        write(self.path("sitemap.xml"), urlset(f"{SITE}/stale/"))
        source = self.path("sitemap_index.xml")
        write(source, index(f"{SITE}/en/sitemap.xml", f"{SITE}/de/sitemap.xml"))
        result = doctor.read_sitemap(source)
        self.assertEqual(result["urls"], [f"{SITE}/en/a/"])
        self.assertIn("de/sitemap.xml", result["error"])

    def test_unique_name_still_falls_back_to_the_flat_copy(self):
        write(self.path("pages.xml"), urlset(f"{SITE}/a/"))
        source = self.path("index.xml")
        write(source, index(f"{SITE}/maps/pages.xml"))
        result = doctor.read_sitemap(source)
        self.assertEqual(result["urls"], [f"{SITE}/a/"])
        self.assertEqual(result["error"], "")

    def test_local_index_never_fetches_a_missing_child(self):
        source = self.path("idx.xml")
        write(source, index("http://127.0.0.1:9/internal.xml"))
        with mock.patch("urllib.request.urlopen") as opened:
            result = doctor.read_sitemap(source)
        opened.assert_not_called()
        self.assertEqual(result["urls"], [])
        self.assertIn("internal.xml", result["error"])

    def test_child_listed_twice_is_not_a_loop(self):
        write(self.path("a.xml"), urlset(f"{SITE}/a/"))
        source = self.path("idx.xml")
        write(source, index(f"{SITE}/a.xml", f"{SITE}/a.xml"))
        result = doctor.read_sitemap(source)
        self.assertEqual(result["urls"], [f"{SITE}/a/"])
        self.assertEqual(result["error"], "")

    def test_child_shared_by_two_indexes_is_not_a_loop(self):
        write(self.path("a.xml"), urlset(f"{SITE}/a/"))
        write(self.path("i1.xml"), index(f"{SITE}/a.xml"))
        write(self.path("i2.xml"), index(f"{SITE}/a.xml"))
        source = self.path("top.xml")
        write(source, index(f"{SITE}/i1.xml", f"{SITE}/i2.xml"))
        result = doctor.read_sitemap(source)
        self.assertEqual(result["urls"], [f"{SITE}/a/"])
        self.assertEqual(result["error"], "")

    def test_a_real_loop_is_still_reported(self):
        write(self.path("i1.xml"), index(f"{SITE}/i2.xml"))
        write(self.path("i2.xml"), index(f"{SITE}/i1.xml"))
        result = doctor.read_sitemap(self.path("i1.xml"))
        self.assertIn("сам на себя", result["error"])


class TestProtocolWarnings(Base):
    def warnings(self, text):
        source = self.path("s.xml")
        write(source, text)
        result = doctor.read_sitemaps([source])
        self.assertEqual(result["errors"], [])
        return " ".join(result["warnings"])

    def test_a_valid_file_gives_no_warnings(self):
        locs = [f"{SITE}/p{i}/" for i in range(12)]
        self.assertEqual(self.warnings(urlset(*locs, lastmod="2026-01-05")), "")

    def test_over_the_url_limit(self):
        locs = [f"{SITE}/p{i}/" for i in range(doctor.MAX_SITEMAP_URLS + 1)]
        self.assertIn("предела протокола", self.warnings(urlset(*locs)))

    def test_relative_locs_are_named(self):
        self.assertIn("не полные адреса", self.warnings(urlset("/", "/about/")))

    def test_missing_or_old_namespace(self):
        self.assertIn("пространстве имён", self.warnings(urlset(f"{SITE}/", ns="")))
        old = 'xmlns="http://www.google.com/schemas/sitemap/0.84"'
        self.assertIn("пространстве имён", self.warnings(urlset(f"{SITE}/", ns=old)))
        https = 'xmlns="https://www.sitemaps.org/schemas/sitemap/0.9"'
        self.assertEqual(self.warnings(urlset(f"{SITE}/", ns=https)), "")

    def test_bad_and_future_lastmod(self):
        self.assertIn("не дата W3C", self.warnings(urlset(f"{SITE}/", lastmod="2031-13-45")))
        self.assertIn("в будущем", self.warnings(urlset(f"{SITE}/", lastmod="2999-01-01")))
        self.assertEqual(self.warnings(urlset(f"{SITE}/", lastmod="2024-05")), "")

    def test_one_build_timestamp_on_every_url(self):
        locs = [f"{SITE}/p{i}/" for i in range(6)]
        self.assertIn("время сборки",
                      self.warnings(urlset(*locs, lastmod="2026-01-05T03:00:00+00:00")))
        # Голая одинаковая дата бывает честной: сайт выложен в один день.
        self.assertEqual(self.warnings(urlset(*locs, lastmod="2026-01-05")), "")


class TestNotesReachTheReport(Base):
    def setUp(self):
        super().setUp()
        self.root = self.path("site")
        self.site(self.root, ["/", "/a/", "/b/"])
        self.out = self.path("out", "r.html")

    def json(self):
        with open(self.path("out", "r.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_unread_child_is_in_check_json_and_html(self):
        write(self.path("sm", "a.xml"), urlset(f"{SITE}/", f"{SITE}/a/"))
        write(self.path("sm", "idx.xml"), index(f"{SITE}/a.xml", f"{SITE}/b.xml"))
        code, _ = run("check", self.root, "--site", SITE,
                      "--sitemap", self.path("sm", "idx.xml"), "--out", self.out)
        notes = " ".join(self.json()["notes"])
        self.assertIn("b.xml", notes)
        self.assertIn("не целиком", notes)
        with open(self.out, encoding="utf-8") as fh:
            self.assertIn("b.xml", fh.read())

    def test_unread_child_is_in_doctor_json(self):
        write(self.path("sm", "a.xml"), urlset(f"{SITE}/", f"{SITE}/a/"))
        write(self.path("sm", "idx.xml"), index(f"{SITE}/a.xml", f"{SITE}/b.xml"))
        run("doctor", self.root, "--site", SITE,
            "--sitemap", self.path("sm", "idx.xml"), "--out", self.out)
        self.assertIn("b.xml", " ".join(self.json()["notes"]))

    def test_http_www_sitemap_for_an_https_apex_site(self):
        write(self.path("sm", "s.xml"), urlset("http://www.demo.example/",
                                               "http://www.demo.example/a/",
                                               "http://www.demo.example/b/"))
        run("doctor", self.root, "--site", SITE,
            "--sitemap", self.path("sm", "s.xml"), "--out", self.out)
        self.assertIn("другой схеме или хосте", " ".join(self.json()["notes"]))

    def test_matching_sitemap_adds_no_sitemap_notes(self):
        write(self.path("sm", "s.xml"), urlset(f"{SITE}/", f"{SITE}/a/", f"{SITE}/b/"))
        run("doctor", self.root, "--site", SITE,
            "--sitemap", self.path("sm", "s.xml"), "--out", self.out)
        notes = " ".join(self.json()["notes"])
        self.assertNotIn("sitemap прочитан", notes)
        self.assertNotIn("другой схеме", notes)


class TestExpired(unittest.TestCase):
    def test_rfc_dates_with_commas(self):
        class P:
            meta = {}

        for robots in ("unavailable_after: Mon, 21 Sep 2020 15:00:00 GMT",
                       "unavailable_after: Monday, 21-Sep-2020 15:00:00 GMT",
                       "noindex, unavailable_after: 2020-09-21",
                       "unavailable_after: Mon, 21 Sep 2020 15:00:00 GMT, nofollow"):
            p = P()
            p.robots = robots
            self.assertTrue(publish.is_expired(p, today="2026-01-01"), robots)
        p = P()
        p.robots = "unavailable_after: Mon, 21 Sep 2099 15:00:00 GMT"
        self.assertFalse(publish.is_expired(p, today="2026-01-01"))


class TestSitemapCommand(Base):
    def test_foreign_shard_is_not_overwritten(self):
        root = self.path("big")
        with mock.patch.object(publish, "MAX_URLS_PER_FILE", 2):
            self.site(root, ["/", "/a/", "/b/"])
            foreign = '<?xml version="1.0"?>' + urlset("https://demo.example/news-1/")
            write(os.path.join(root, "sitemap-1.xml"), foreign)
            code, _ = run("sitemap", root, "--site", SITE)
            self.assertNotEqual(code, 0)
            with open(os.path.join(root, "sitemap-1.xml"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), foreign)
            self.assertFalse(os.path.exists(os.path.join(root, "sitemap.xml")))
            code, _ = run("sitemap", root, "--site", SITE, "--force")
            self.assertEqual(code, 0)

    def test_own_shards_are_rewritten_without_force(self):
        root = self.path("big")
        with mock.patch.object(publish, "MAX_URLS_PER_FILE", 2):
            self.site(root, ["/", "/a/", "/b/"])
            self.assertEqual(run("sitemap", root, "--site", SITE)[0], 0)
            self.assertEqual(run("sitemap", root, "--site", SITE)[0], 0)

    def test_public_prefix_is_encoded_and_full_urls_refused(self):
        root = self.path("big")
        with mock.patch.object(publish, "MAX_URLS_PER_FILE", 2):
            self.site(root, ["/", "/a/", "/b/"])
            code, _ = run("sitemap", root, "--site", SITE, "--out-dir", self.path("o1"),
                          "--public-prefix", "site maps/карта")
            self.assertEqual(code, 0)
            with open(self.path("o1", "sitemap.xml"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn(f"{SITE}/site%20maps/%D0%BA%D0%B0%D1%80%D1%82%D0%B0/sitemap-1.xml",
                          text)
            code, _ = run("sitemap", root, "--site", SITE, "--out-dir", self.path("o2"),
                          "--public-prefix", "https://cdn.example/maps/")
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(self.path("o2", "sitemap.xml")))

    def test_idn_host_is_punycode_in_loc(self):
        root = self.path("idn")
        self.site(root, ["/", "/кот/"])
        self.assertEqual(run("sitemap", root, "--site", "https://пример.example/")[0], 0)
        with open(os.path.join(root, "sitemap.xml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("<loc>https://xn--e1afmkfd.example/</loc>", text)
        self.assertIn("https://xn--e1afmkfd.example/%D0%BA%D0%BE%D1%82/", text)
        self.assertNotIn("пример", text)

    def test_ascii_url_keeps_port_and_plain_hosts(self):
        self.assertEqual(publish.ascii_url("https://example.com/a/"), "https://example.com/a/")
        self.assertEqual(publish.ascii_url("https://пример.example:8080/a"),
                         "https://xn--e1afmkfd.example:8080/a")

    def test_host_redirect_rule_is_named(self):
        root = self.path("v")
        self.site(root, ["/", "/old/", "/new/"])
        write(os.path.join(root, "vercel.json"), json.dumps(
            {"redirects": [{"source": "/old/", "destination": "/new/", "permanent": True}]}))
        code, out = run("sitemap", root, "--site", SITE)
        self.assertEqual(code, 0)
        self.assertIn("правило хостинга", out)
        self.assertIn(f"{SITE}/old/", out)

    def test_plain_site_has_no_new_warnings(self):
        root = self.path("plain")
        self.site(root, ["/", "/a/", "/b/"])
        write(os.path.join(root, "robots.txt"), f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
        code, out = run("sitemap", root, "--site", SITE)
        self.assertEqual(code, 0)
        for text in ("правило хостинга", "canonical-form", "объявляет другой sitemap",
                     "в прошлый раз", "кода ответа"):
            self.assertNotIn(text, out)

    def test_robots_declares_another_sitemap(self):
        root = self.path("r")
        self.site(root, ["/", "/a/"])
        write(os.path.join(root, "robots.txt"),
              f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap_index.xml\n")
        code, out = run("sitemap", root, "--site", SITE)
        self.assertEqual(code, 0)
        self.assertIn("объявляет другой sitemap", out)

    def test_collapse_against_the_previous_run_is_named(self):
        root = self.path("c")
        paths = ["/", "/about/"] + [f"/rent/c{i}/" for i in range(6)]
        self.site(root, paths)
        self.assertEqual(run("sitemap", root, "--site", SITE)[0], 0)
        for p in paths[2:]:
            write(os.path.join(root, p.strip("/"), "index.html"),
                  page(f"Page {p}", head='<meta name="robots" content="noindex">'))
        code, out = run("sitemap", root, "--site", SITE)
        self.assertEqual(code, 0)
        self.assertIn("в прошлый раз было 8", out)

    def test_canonical_form_is_named(self):
        root = self.path("cf")
        self.site(root, ["/"])
        write(os.path.join(root, "c4", "index.html"),
              page("C4", head=f'<link rel="canonical" href="{SITE}/c4">'))
        code, out = run("sitemap", root, "--site", SITE)
        self.assertEqual(code, 0)
        self.assertIn("canonical-form", out)

    def test_unlinked_page_under_a_status_code_directory_is_named(self):
        root = self.path("e")
        self.site(root, ["/", "/http/404/"])
        code, out = run("sitemap", root, "--site", SITE)
        self.assertEqual(code, 0)
        self.assertIn("кода ответа", out)
        self.assertIn("/http/404/", out)


if __name__ == "__main__":
    unittest.main()
