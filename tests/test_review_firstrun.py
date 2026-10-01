# -*- coding: utf-8 -*-
"""
Первые десять минут: находки ревью десяти агентов перед публичным запуском.

Ревьюер прошёл путь новичка по README. Падений не было ни одного, но в трёх
местах пакет заводил в тупик: на сборке Next.js `init` называл страницами
каталог `./content`, которого нет, и записывал его в конфиг; собственные
наряды и отчёты он на следующем прогоне принимал за страницы сайта; а главный
совет в консоли обрезался на восьмидесятом символе — ровно перед тем, что
нужно сделать.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, install

SITE = "https://example.com"


def html(title, links=("/",)):
    anchors = "".join(f'<a href="{h}">ссылка</a>' for h in links)
    return (f"<html><head><title>{title} — страница сайта</title></head><body><main>"
            f"<h1>{title}</h1><p>{'слово ' * 150}</p>{anchors}</main></body></html>")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-first-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()


class TestInit(Fixture):
    def test_init_finds_a_next_build(self):
        self.write("package.json", '{"name": "shop", "homepage": "https://example.com"}')
        for name in ("index", "a", "b", "c"):
            self.write(f".next/server/app/{name}.html", html(name))
        result = install.run(self.dir)
        self.assertEqual(result["detected"]["content"],
                         os.path.join(".", ".next", "server", "app"))

    def test_a_static_export_is_found_too(self):
        self.write("package.json", "{}")
        for name in ("index", "a", "b"):
            self.write(f"out/{name}.html", html(name))
        self.assertEqual(install.run(self.dir)["detected"]["content"], os.path.join(".", "out"))

    def test_sources_win_over_their_own_build(self):
        self.write("hugo.toml", 'baseURL = "https://example.com/"')
        for name in ("a", "b", "c"):
            self.write(f"content/{name}.md", f"---\ntitle: {name}\n---\n\nтекст")
            self.write(f"public/{name}/index.html", html(name))
        self.assertEqual(install.run(self.dir)["detected"]["content"],
                         os.path.join(".", "content"))

    def test_no_pages_means_no_invented_path(self):
        self.write("package.json", "{}")
        code, out = self.run_cli(["init", self.dir])
        self.assertNotIn("./content", out)
        self.assertEqual(code, 1)
        self.assertIn("indexgap init", out)
        import json
        config = json.load(open(os.path.join(self.dir, "indexgap.json"), encoding="utf-8"))
        self.assertEqual(config["pages"], "")

    def test_init_trusts_an_existing_config(self):
        """После `brief --write` повторный `init` называл страницами каталог нарядов."""
        self.write("indexgap.json", '{"site": "https://example.com", "pages": "."}')
        self.write("index.html", html("Главная"))
        for i in range(6):
            self.write(f"indexgap-briefs/p{i}.md", f"# Наряд {i}\n\nтекст")
        detected = install.run(self.dir)["detected"]
        self.assertEqual(detected["content"], ".")
        self.assertEqual(detected["site"], "https://example.com")


class TestOwnOutput(Fixture):
    def test_briefs_and_reports_are_not_pages(self):
        self.write("index.html", html("Главная", ["/a/"]))
        self.write("a/index.html", html("А"))
        self.write("indexgap-briefs/a.md", "---\ntitle: Наряд\n---\n\n# Наряд\n\nтекст")
        self.write("reports/my.html", "<!doctype html><!-- indexgap-report --><html><head>"
                                      "<title>Отчёт</title></head><body><p>отчёт</p></body></html>")
        pages, problems = core.load_pages(self.dir, SITE)
        self.assertEqual(sorted(p.url.replace(SITE, "") for p in pages), ["/", "/a/"])
        self.assertEqual(problems, [])


class TestConsole(Fixture):
    def test_version_flag(self):
        from indexgap import __version__
        code, out = self.run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)

    def test_the_advice_is_not_cut_and_warnings_are_named(self):
        self.write("index.html", html("Главная", ["/a/"]))
        self.write("a/index.html", html("А"))
        self.write("lost/index.html", html("Потерянная"))
        self.write("thin/index.html", "<html><head><title>Тонкая страница сайта</title></head>"
                                      '<body><main><h1>Тонкая</h1><p>мало</p><a href="/">д</a>'
                                      "</main></body></html>")
        self.write("index.html", html("Главная", ["/a/", "/thin/"]))
        _, out = self.run_cli(["check", self.dir, "--site", SITE,
                               "--out", os.path.join(self.dir, "r.html")])
        from indexgap import report
        advice = report._help("orphan")
        self.assertGreater(len(advice), 80)
        self.assertIn(" ".join(advice.split()[-3:]), " ".join(out.split()))
        self.assertIn("thin", out)


if __name__ == "__main__":
    unittest.main()
