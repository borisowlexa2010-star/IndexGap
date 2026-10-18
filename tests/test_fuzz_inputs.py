# -*- coding: utf-8 -*-
"""
Грязный ввод из жизни: третий проход, на этот раз «на что сломается».

Каждый случай воспроизведён ревьюером на 3.9 и 3.15: падение с трассировкой,
квадратичный разбор, страница, прочитанная в чужой кодировке или пропавшая
без следа, черновик, ушедший в sitemap из-за комментария в YAML.
"""

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unicodedata
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, doctor, publish

SITE = "https://example.com"


class Dir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-fuzz-")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for current, dirs, _ in os.walk(self.dir):
            for d in dirs:
                try:
                    os.chmod(os.path.join(current, d), 0o755)
                except OSError:
                    pass
        shutil.rmtree(self.dir, True)

    def path(self, name):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def write(self, name, data):
        mode = "wb" if isinstance(data, bytes) else "w"
        kw = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
        with open(self.path(name), mode, **kw) as fh:
            fh.write(data)
        return self.path(name)

    def page(self, name, data):
        return core.load_page(self.write(name, data), self.dir, SITE)

    def cli(self, *argv):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return cli.main(list(argv))


PAGE = ("<!doctype html><html><head><title>Home</title></head><body><main>"
        "<p>Text of the page.</p></main></body></html>")


class Crashes(Dir):
    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "права на запись так не отнять")
    def test_read_only_output_is_one_line_not_a_traceback(self):
        self.write("site/index.html", PAGE)
        ro = self.path("ro/x")
        os.chmod(os.path.dirname(ro), stat.S_IRUSR | stat.S_IXUSR)
        code = self.cli("check", self.path("site"), "--site", SITE,
                        "--out", os.path.join(os.path.dirname(ro), "r.html"))
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", self.stderr.getvalue())
        self.assertIn("r.html", self.stderr.getvalue())

    def test_config_values_of_the_wrong_type(self):
        self.write("site/index.html", PAGE)
        for config in ({"pages": "site", "site": 123},
                       {"pages": "site", "site": SITE, "profile": 5},
                       {"pages": "site", "site": SITE, "dataset": 7}):
            with self.subTest(config=config):
                self.write("indexgap.json", json.dumps(config))
                code = self.cli("check", "--config", self.path("indexgap.json"),
                                "--out", self.path("o.html"))
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", self.stderr.getvalue())

    def test_deeply_nested_jsonld_does_not_kill_the_run(self):
        deep = "[" * 100000 + "]" * 100000
        self.write("site/index.html",
                   "<!doctype html><html><head><title>T</title>"
                   f"<script type=\"application/ld+json\">{deep}</script></head>"
                   "<body><main><p>Text of the page.</p></main></body></html>")
        self.assertEqual(self.cli("check", self.path("site"), "--site", SITE,
                                  "--out", self.path("o.html")), 0)

    def test_nul_byte_in_a_keyword_csv(self):
        path = self.write("nul.csv", b"keyword,volume\nvi\x00sa,1\nvisa singapore,2\n")
        code = self.cli("plan", path)
        self.assertIn(code, (0, 1))
        self.assertNotIn("Traceback", self.stderr.getvalue())


class Linear(Dir):
    BUDGET = 3.0

    def timed(self, text):
        path = self.write("p.html", text)
        start = time.perf_counter()
        core.load_page(path, self.dir, SITE)
        return time.perf_counter() - start

    def test_stray_closing_tags(self):
        text = ("<html><head><title>S</title></head><body><main>" + "<div>" * 20000
                + "<p>hi</p>" + "</span>" * 20000 + "</main></body></html>")
        self.assertLess(self.timed(text), self.BUDGET)

    def test_many_open_inline_tags(self):
        text = ("<html><head><title>S</title></head><body><main>" + "<span>" * 5000
                + "<p>x</p>" * 5000 + "</main></body></html>")
        self.assertLess(self.timed(text), self.BUDGET)


class Encodings(Dir):
    RU = "<title>Виза в Сингапур</title>"

    def doc(self, head="", body="<p>Подробное руководство</p>"):
        return (f"<!doctype html><html><head>{head}{self.RU}</head>"
                f"<body><main>{body}</main></body></html>")

    def test_one_stray_byte_keeps_utf8(self):
        data = self.doc('<meta charset="utf-8">').encode().replace(
            b"</main>", b"</main><footer>\xa9 2024</footer>")
        page = self.page("stray.html", data)
        self.assertEqual(page.title, "Виза в Сингапур")
        self.assertTrue(any("UTF-8" in n for n in page.notes))

    def test_charset_in_a_description_is_not_a_declaration(self):
        data = self.doc('<meta name="description" content="How to set charset=iso-8859-1">').encode()
        self.assertEqual(self.page("d.html", data).title, "Виза в Сингапур")

    def test_a_commented_out_meta_is_not_a_declaration(self):
        data = self.doc('<!-- <meta charset="koi8-r"> -->').encode()
        self.assertEqual(self.page("c.html", data).title, "Виза в Сингапур")

    def test_valid_utf8_beats_a_stale_cp1251_declaration(self):
        data = self.doc('<meta charset="windows-1251">').encode()
        self.assertEqual(self.page("s.html", data).title, "Виза в Сингапур")

    def test_cp1251_declared_and_undeclared_still_read(self):
        for head in ('<meta charset="windows-1251">', ""):
            with self.subTest(head=head):
                page = self.page("w.html", self.doc(head).encode("cp1251"))
                self.assertEqual(page.title, "Виза в Сингапур")

    def test_latin1_without_declaration_is_not_read_as_cyrillic(self):
        data = ("<!doctype html><html><head><title>Visa pour Singapour : guide "
                "détaillé</title></head><body><main><p>Préparez votre dossier, "
                "réservez l'hôtel et vérifiez la validité du passeport.</p></main>"
                "</body></html>").encode("cp1252")
        self.assertEqual(self.page("fr.html", data).title,
                         "Visa pour Singapour : guide détaillé")

    def test_iso_8859_1_label_means_windows_1252(self):
        data = ('<!doctype html><html><head><meta charset="iso-8859-1">'
                "<title>Don’t miss “Singapore”</title></head>"
                "<body><main><p>x</p></main></body></html>").encode("cp1252")
        self.assertEqual(self.page("q.html", data).title, "Don’t miss “Singapore”")

    def test_utf16_without_bom_is_a_page(self):
        data = PAGE.replace("Home", "Visa guide").encode("utf-16-le")
        self.write("site/u16.html", data)
        pages = core.load_pages(self.path("site"), SITE)[0]
        self.assertEqual([p.title for p in pages], ["Visa guide"])

    def test_meta_utf16_on_a_utf8_file_means_utf8(self):
        self.write("site/m16.html", PAGE.replace("<head>", '<head><meta charset="utf-16">'))
        pages = core.load_pages(self.path("site"), SITE)[0]
        self.assertEqual([p.title for p in pages], ["Home"])


class FrontMatter(Dir):
    def test_comment_after_a_value(self):
        page = self.page("d.md", "---\ntitle: \"Visa guide: Singapore\" # SEO title\n"
                                 "draft: true # flip before launch\n---\n\nbody text\n")
        self.assertEqual(page.title, "Visa guide: Singapore")
        self.assertTrue(publish.is_draft(page))

    def test_a_hash_inside_quotes_stays(self):
        page = self.page("h.md", "---\ntitle: \"C# for beginners\"\n---\n\nbody\n")
        self.assertEqual(page.title, "C# for beginners")

    def test_a_hash_without_a_space_stays(self):
        page = self.page("h2.md", "---\ntitle: Issue#42 fixed\n---\n\nbody\n")
        self.assertEqual(page.title, "Issue#42 fixed")

    def test_space_hash_is_a_comment_as_in_yaml(self):
        # Так прочитают и Hugo, и Jekyll: « #» начинает комментарий.
        page = self.page("h3.md", "---\ntitle: Issue #42 fixed\n---\n\nbody\n")
        self.assertEqual(page.title, "Issue")


class SearchConsoleStates(Dir):
    def test_indexed_states_are_indexed(self):
        path = self.write("s.csv", "URL,Coverage state\n"
                                   "https://example.com/,Submitted and indexed\n"
                                   "https://example.com/a/,\"Indexed, though blocked by robots.txt\"\n"
                                   "https://example.com/b/,URL is on Google\n"
                                   "https://example.com/c/,Blocked by robots.txt\n")
        got = doctor.read_indexed(path, SITE, index_status=True)
        keys = {core.url_key(u) for u in got["urls"]}
        self.assertEqual(keys, {core.url_key(SITE + p) for p in ("/", "/a/", "/b/")})


class FileNames(Dir):
    def test_nfd_file_name_and_nfc_link_are_one_page(self):
        self.write("site/index.html", '<!doctype html><html><head><title>Home</title></head>'
                                      '<body><main><a href="/café.html">c</a></main></body></html>')
        self.write("site/" + unicodedata.normalize("NFD", "café") + ".html", PAGE)
        pages = core.load_pages(self.path("site"), SITE)[0]
        from indexgap import checks
        graph = checks.link_graph(pages, SITE + "/")
        self.assertEqual(graph["orphans"], [])

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "права на чтение так не отнять")
    def test_an_unreadable_directory_is_named(self):
        self.write("site/index.html", PAGE)
        self.write("site/locked/p1.html", PAGE)
        os.chmod(self.path("site/locked"), 0)
        pages, problems = core.load_pages(self.path("site"), SITE)[:2]
        self.assertTrue(any("locked" in p for p in problems), problems)


class UrlLists(Dir):
    def test_a_comma_inside_a_url_is_not_a_column(self):
        path = self.write("list.txt", "https://example.com/a/?x=1,2\nhttps://example.com/b/\n"
                                      "https://example.com/c,d/\n")
        urls = doctor.read_indexed(path, SITE)["urls"]
        self.assertIn("https://example.com/a/?x=1,2", urls)
        self.assertIn("https://example.com/c,d/", urls)


class FirstWins(Dir):
    def test_duplicated_attributes_and_tags_keep_the_first(self):
        page = self.page("dup.html", '<html lang="en" lang="ru"><head>'
                         '<meta name="description" name="robots" content="Visa guide">'
                         '<base href="/a/"><base href="/b/"><title>First</title></head>'
                         '<body><main><p>Text</p><title>Second</title></main></body></html>')
        self.assertEqual(page.lang, "en")
        self.assertFalse(page.noindex)
        self.assertEqual(page.title, "First")
        self.assertEqual(page.description, "Visa guide")

    def test_unclosed_svg_does_not_hide_the_page(self):
        page = self.page("sv.html", "<html><head><title>SV</title></head><body><main>"
                         "<svg><path d=\"M0\"/><p>" + "long text " * 50 + "</p></main></body></html>")
        self.assertGreater(page.word_count, 50)


if __name__ == "__main__":
    unittest.main()
