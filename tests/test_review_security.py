# -*- coding: utf-8 -*-
"""
Безопасность: находки ревью десяти агентов перед публичным запуском.

Пакет читает то, что написал не его владелец: sitemap по сети, выгрузку от
подрядчика, манифест из клонированного репозитория. Каждое из этих мест
доверяло содержимому. Манифест мог назвать «старым шардом» любой файл, и
`indexgap sitemap` его удалял. Индекс sitemap с чужого сервера мог назвать
дочерним файлом локальный путь, и он читался. Архив в сто килобайт
разворачивался в сотни мегабайт памяти.
"""

import gzip
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import core, doctor, publish, sources

SITE = "https://example.com"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*urls):
    return (f'<?xml version="1.0"?><urlset {NS}>'
            + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")


def index(*locs):
    return (f'<?xml version="1.0"?><sitemapindex {NS}>'
            + "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in locs) + "</sitemapindex>")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-sec-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, text, mode="w"):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
            fh.write(text)
        return path

    def pages(self):
        self.write("site/index.html",
                   "<html><head><title>Главная страница</title></head><body><main>"
                   f"<h1>Главная</h1><p>{'слово ' * 80}</p></main></body></html>")
        return core.load_pages(os.path.join(self.dir, "site"), SITE)[0]


class Web:
    """Подменяет сеть таблицей {адрес: байты} и считает запросы."""

    def __init__(self, table):
        self.table, self.asked = table, []

    def __call__(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        self.asked.append(url)
        if url not in self.table:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        body = self.table[url]
        response = mock.MagicMock()
        response.read.side_effect = lambda n=-1: body if n is None or n < 0 else body[:n]
        response.__enter__.return_value = response
        return response


class TestManifest(Fixture):
    def test_manifest_shards_cannot_delete_outside_out_dir(self):
        victim = self.write("outside/victim.txt", "важный файл")
        absolute = self.write("outside/absolute.txt", "важный файл")
        out = os.path.join(self.dir, "site")
        pages = self.pages()
        result = publish.build_sitemap(pages, out, SITE, manifest={
            "_shards": ["../outside/victim.txt", absolute, "sitemap-news.xml"]})
        self.assertTrue(os.path.exists(victim))
        self.assertTrue(os.path.exists(absolute))
        self.assertEqual(result["removed"], [])

    def test_its_own_stale_shard_is_still_removed(self):
        out = os.path.join(self.dir, "site")
        pages = self.pages()
        stale = self.write("site/sitemap-7.xml", urlset(SITE + "/old/"))
        result = publish.build_sitemap(pages, out, SITE, manifest={"_shards": ["sitemap-7.xml"]})
        self.assertFalse(os.path.exists(stale))
        self.assertEqual([os.path.basename(p) for p in result["removed"]], ["sitemap-7.xml"])

    def test_hostile_manifest_cannot_crash_or_break_the_xml(self):
        out = os.path.join(self.dir, "site")
        pages = self.pages()
        url = pages[0].url
        for manifest in ({url: "oops"}, {"_shards": "abc"}, {url: ["x"]},
                         {url: {"hash": pages[0].content_hash,
                                "lastmod": "31.12.2099</lastmod><x>&"}}):
            publish.build_sitemap(pages, out, SITE, manifest=manifest, today="2026-10-01")
            publish.diff_changed(pages, manifest)
            from xml.etree import ElementTree
            tree = ElementTree.parse(os.path.join(out, "sitemap.xml"))
            lastmods = [el.text for el in tree.iter() if el.tag.endswith("lastmod")]
            self.assertEqual(lastmods, ["2026-10-01"], manifest)


class TestSitemapReading(Fixture):
    def test_remote_sitemap_index_cannot_open_local_path(self):
        secret = self.write("secret.xml", urlset("https://internal.example/private-1"))
        web = Web({f"{SITE}/sitemap.xml": index(secret, "file://" + secret,
                                                f"{SITE}/pages.xml").encode(),
                   f"{SITE}/pages.xml": urlset(f"{SITE}/a").encode()})
        with mock.patch("urllib.request.urlopen", web):
            result = doctor.read_sitemap(f"{SITE}/sitemap.xml")
        self.assertEqual(result["urls"], [f"{SITE}/a"])
        self.assertTrue(result["error"])

    def test_remote_index_does_not_send_requests_to_other_hosts(self):
        web = Web({f"{SITE}/sitemap.xml": index("http://127.0.0.1:8080/admin",
                                                "https://other.example/s.xml",
                                                f"https://www.example.com/pages.xml").encode(),
                   "https://www.example.com/pages.xml": urlset(f"{SITE}/a").encode()})
        with mock.patch("urllib.request.urlopen", web):
            result = doctor.read_sitemap(f"{SITE}/sitemap.xml")
        self.assertEqual(sorted(web.asked),
                         ["https://example.com/sitemap.xml", "https://www.example.com/pages.xml"])
        self.assertEqual(result["urls"], [f"{SITE}/a"])
        self.assertIn("other.example", result["error"])

    def test_local_index_cannot_escape_its_directory(self):
        self.write("secret.xml", urlset("https://internal.example/private-1"))
        source = self.write("pub/sitemap.xml", index("../secret.xml",
                                                     os.path.join(self.dir, "secret.xml")))
        result = doctor.read_sitemap(source)
        self.assertEqual(result["urls"], [])
        self.assertTrue(result["error"])

    def test_sitemap_index_fanout_is_capped(self):
        table = {f"{SITE}/sitemap.xml":
                 index(*[f"{SITE}/s{i}.xml" for i in range(500)]).encode()}
        for i in range(500):
            table[f"{SITE}/s{i}.xml"] = urlset(f"{SITE}/p{i}").encode()
        web = Web(table)
        with mock.patch("urllib.request.urlopen", web):
            result = doctor.read_sitemap(f"{SITE}/sitemap.xml")
        self.assertLessEqual(len(web.asked), doctor.MAX_SITEMAPS)
        self.assertTrue(result["error"])

    def test_index_with_same_named_children_in_subdirs_is_not_a_silent_zero(self):
        """Многоязычный Hugo: индекс `sitemap.xml` и дочерние `en/sitemap.xml`."""
        self.write("pub/en/sitemap.xml", urlset(f"{SITE}/en/a", f"{SITE}/en/b"))
        self.write("pub/de/sitemap.xml", urlset(f"{SITE}/de/a"))
        source = self.write("pub/sitemap.xml", index(f"{SITE}/en/sitemap.xml",
                                                     f"{SITE}/de/sitemap.xml"))
        result = doctor.read_sitemap(source)
        self.assertEqual(sorted(result["urls"]),
                         [f"{SITE}/de/a", f"{SITE}/en/a", f"{SITE}/en/b"])
        self.assertEqual(result["error"], "")

    def test_an_index_that_refers_to_itself_says_so(self):
        source = self.write("pub/sitemap.xml", index("sitemap.xml"))
        result = doctor.read_sitemap(source)
        self.assertEqual(result["urls"], [])
        self.assertTrue(result["error"])

    def test_sitemap_with_doctype_is_refused(self):
        """Раздувание сущностей: 494 байта давали адрес в сто миллионов символов."""
        bomb = ('<?xml version="1.0"?><!DOCTYPE urlset [<!ENTITY a "aaaaaaaaaa">'
                '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
                f'<urlset {NS}><url><loc>https://example.com/&b;</loc></url></urlset>')
        result = doctor.read_sitemap(self.write("bomb.xml", bomb))
        self.assertEqual(result["urls"], [])
        self.assertTrue(result["error"])

    def test_compressed_sitemap_is_size_capped(self):
        body = urlset(*[f"{SITE}/{'x' * 200}{i}" for i in range(2000)]).encode()
        path = self.write("big.xml.gz", gzip.compress(body), mode="wb")
        with mock.patch.object(core, "MAX_INPUT_BYTES", 50_000):
            result = doctor.read_sitemap(path)
        self.assertEqual(result["urls"], [])
        self.assertTrue(result["error"])

    def test_broken_gzip_and_unencodable_urls_are_errors_not_tracebacks(self):
        body = gzip.compress(urlset(f"{SITE}/a").encode())
        for name, data in (("cut.xml.gz", body[:-12]),
                           ("bad.xml.gz", body[:20] + b"\x00" * 30 + body[50:])):
            result = doctor.read_sitemap(self.write(name, data, mode="wb"))
            self.assertEqual(result["urls"], [], name)
            self.assertTrue(result["error"], name)
        web = Web({})
        with mock.patch("urllib.request.urlopen", web):
            for url in (f"{SITE}/site map.xml", f"{SITE}/карта.xml"):
                result = doctor.read_sitemap(url)
                self.assertTrue(result["error"], url)

    def test_a_directory_or_a_pipe_is_not_read(self):
        result = doctor.read_sitemap(self.dir)
        self.assertEqual(result["urls"], [])
        self.assertTrue(result["error"])


class TestArchives(Fixture):
    def test_export_zip_member_is_size_capped(self):
        path = os.path.join(self.dir, "export.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Pages.csv", "Top pages,Clicks\n"
                             + "".join(f"{SITE}/{'x' * 100}{i},1\n" for i in range(3000)))
        with mock.patch.object(core, "MAX_INPUT_BYTES", 50_000):
            with self.assertRaises(core.SourceError):
                sources.read_table(path)

    def test_xlsx_with_doctype_is_refused(self):
        path = os.path.join(self.dir, "book.xlsx")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml",
                             '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
                             '<worksheet xmlns="http://schemas.openxmlformats.org/'
                             'spreadsheetml/2006/main"><sheetData/></worksheet>')
        with self.assertRaises(core.SourceError):
            sources.read_table(path)


class TestPathologicalInput(Fixture):
    """
    Ввод, подобранный под выражение: сорок килобайт открывающих скобок,
    незакрытых блоков кода, пустых строк. Каждое из прежних выражений работало
    на таком за квадрат — от шести до тридцати четырёх секунд на страницу. В CI
    это страница из пользовательского контента, которая останавливает сборку.
    """

    BUDGET = 3.0

    def timed(self, call):
        import time
        started = time.time()
        call()
        return time.time() - started

    def load(self, name, text):
        path = self.write(name, text)
        return lambda: core.load_page(path, self.dir, SITE)

    def test_pathological_inputs_parse_in_linear_time(self):
        head = "---\ntitle: x\n---\n\n"
        cases = {
            "fences.md": head + "```a\n" * 12000,
            "brackets.md": head + "[" * 48000,
            "blank.md": head + "\n" * 39000 + "text",
            "comments.md": head + "<!-- " * 12000,
            "backticks.md": head + "`" * 40000,
        }
        for name, text in cases.items():
            self.assertLess(self.timed(self.load(name, text)), self.BUDGET, name)

    def test_unclosed_html_blocks_do_not_stall_the_checks(self):
        from indexgap import checks, content, freshness
        for tag in ("<pre ", "<code ", "<noscript ", "<!-- ", "<time ", "<meta "):
            page = core.load_page(self.write("p.html", "<html><head>"
                                  '<meta http-equiv="refresh" content="5; url=/x/"></head>'
                                  "<body><p>TODO: x " + tag * 20000 + "</p></body></html>"),
                                  self.dir, SITE)
            page.jsonld = ['{"@type": "Event"}']
            took = self.timed(lambda: (checks._redirect_target(page), content.check_brief([page]),
                                       freshness.page_dates(page)))
            self.assertLess(took, self.BUDGET, tag)

    def test_fences_and_spans_still_mean_what_they_meant(self):
        self.assertEqual(core._strip_fences("a\n```py\n# not a heading\n```\nb"), "a\n\nb")
        self.assertEqual(core._strip_fences("a\n~~~\ncode\n"), "a")
        self.assertEqual(core.drop_spans("a <PRE>x</pre> b <preview>c</preview>",
                                         (("<pre", "</pre>"),)), "a   b <preview>c</preview>")
        self.assertEqual(core.drop_spans("a <!-- x --> b <!-- open", (("<!--", "-->"),)),
                         "a   b <!-- open")


class TestInitInAHostileRepo(Fixture):
    def repo(self):
        root = os.path.join(self.dir, "repo")
        os.makedirs(os.path.join(root, "content"))
        for i in range(3):
            with open(os.path.join(root, "content", f"p{i}.md"), "w", encoding="utf-8") as fh:
                fh.write(f"---\ntitle: Page {i}\n---\n\ntext")
        return root

    def test_init_refuses_symlinked_targets(self):
        """Клонированный репозиторий может прислать вместо файла ссылку на чужой:
        `init` перезаписывал то, на что она ведёт, — вне проекта."""
        from indexgap import install
        for name in (".gitignore", "indexgap.json", "AGENTS.md"):
            root = self.repo()
            outside = os.path.join(self.dir, "outside-" + name.strip("."))
            with open(outside, "w", encoding="utf-8") as fh:
                fh.write("чужой файл\n")
            os.symlink(outside, os.path.join(root, name))
            with self.assertRaises(core.SourceError, msg=name):
                install.run(root, site="https://example.com", agents=True, force=True)
            self.assertEqual(open(outside, encoding="utf-8").read(), "чужой файл\n", name)
            shutil.rmtree(root)

    def test_a_symlinked_skills_directory_is_refused_too(self):
        from indexgap import install
        root = self.repo()
        outside = os.path.join(self.dir, "elsewhere")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(root, ".claude"))
        with self.assertRaises(core.SourceError):
            install.run(root, site="https://example.com")
        self.assertEqual(os.listdir(outside), [])

    def test_detect_site_rejects_non_hostname_cname(self):
        """Содержимое CNAME попадало в напечатанную команду и в блок ```bash
        в AGENTS.md как есть — вместе с `; echo …`, если он там был."""
        from indexgap import install
        root = self.repo()
        with open(os.path.join(root, "CNAME"), "w", encoding="utf-8") as fh:
            fh.write("evil.example/ ; echo INJECTED #\n")
        self.assertEqual(install.detect_site(root), "")
        with open(os.path.join(root, "CNAME"), "w", encoding="utf-8") as fh:
            fh.write("docs.example.com\n")
        self.assertEqual(install.detect_site(root), "https://docs.example.com/")


class TestOutputIsNotAWeapon(Fixture):
    def test_url_key_keeps_control_characters_encoded(self):
        """Адрес из выгрузки с `%0a::error file=…` печатался раскодированным:
        строка с начала столбца — команда для GitHub Actions."""
        key = core.url_key("https://example.com/gone%0a::error file=app.py::X%1b]0;T%07")
        self.assertNotRegex(key, r"[\x00-\x1f\x7f]")
        self.assertIn("%0A", key)
        self.assertEqual(core.url_key("https://example.com/%D0%B2%D0%B8%D0%B7%D0%B0"),
                         "//example.com/виза")

    def run_cli(self, argv):
        import contextlib
        from indexgap import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                return cli.main(argv), out.getvalue()
            except SystemExit as exc:
                return exc.code, out.getvalue()

    def site(self):
        self.write("site/index.html", "<html><head><title>Главная страница</title></head><body>"
                                      f"<main><h1>Главная</h1><p>{'слово ' * 80}</p></main></body></html>")
        return os.path.join(self.dir, "site")

    def test_out_never_overwrites_foreign_json(self):
        """`--out package.html` заменял соседний `package.json`."""
        root = self.site()
        foreign = self.write("package.json", '{"name": "my-app"}')
        code, _ = self.run_cli(["check", root, "--site", SITE,
                                "--out", os.path.join(self.dir, "package.html")])
        self.assertEqual(code, 2)
        self.assertEqual(open(foreign, encoding="utf-8").read(), '{"name": "my-app"}')

    def test_its_own_report_pair_is_rewritten(self):
        root = self.site()
        out = os.path.join(self.dir, "r.html")
        self.assertEqual(self.run_cli(["check", root, "--site", SITE, "--out", out])[0], 0)
        self.assertEqual(self.run_cli(["check", root, "--site", SITE, "--out", out])[0], 0)

    def test_portfolio_does_not_overwrite_its_own_input(self):
        root = self.site()
        spec = self.write("pf.json", '{"projects": [{"name": "a", "root": "%s", '
                                     '"site": "https://example.com"}]}' % root.replace("\\", "/"))
        before = open(spec, encoding="utf-8").read()
        code, _ = self.run_cli(["portfolio", spec, "--out", os.path.join(self.dir, "pf.html")])
        self.assertEqual(code, 2)
        self.assertEqual(open(spec, encoding="utf-8").read(), before)


class TestKeysStayOutOfUrls(unittest.TestCase):
    def test_gemini_key_goes_in_a_header(self):
        from indexgap import cite
        seen = {}

        def fake(url, payload, headers):
            seen["url"], seen["headers"] = url, headers
            return {}
        with mock.patch.object(cite, "_post", fake), \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "secret-key-value"}):
            try:
                cite.ask("gemini", "question")
            except Exception:
                pass
        self.assertNotIn("secret-key-value", seen.get("url", ""))
        self.assertIn("secret-key-value", "".join(seen.get("headers", {}).values()))


if __name__ == "__main__":
    unittest.main()
