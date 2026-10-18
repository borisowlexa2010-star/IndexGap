# -*- coding: utf-8 -*-
"""
`check --baseline`: CI падает только на новых находках.

Сайт, у которого уже есть сотня старых критичных находок, не может включить
`--strict` в CI: сборка красная с первого дня, и её отключают. Базовая
линия — данные прошлого прогона (`indexgap-check.json`). Находка, которая
в ней уже была, считается долгом, а не поломкой; новая — поломкой.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli

SITE = "https://example.com"


def page(title, body="Текст страницы про аренду техники в городе."):
    head = f"<title>{title}</title>" if title else ""
    return (f"<!doctype html><html lang=\"ru\"><head>{head}"
            "<meta name=\"description\" content=\"Аренда техники\"></head>"
            f"<body><main><h1>Аренда</h1><p>{body}</p>"
            "<a href=\"/\">Главная</a> <a href=\"/a/\">Аренда А</a> "
            "<a href=\"/b/\">Аренда Б</a> <a href=\"/c/\">Аренда В</a></main></body></html>")


class Baseline(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-baseline-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.site = os.path.join(self.dir, "site")
        self.write("index.html", page("Аренда техники"))
        self.write("a/index.html", page(""))          # старый долг: нет title
        self.base = os.path.join(self.dir, "base.json")
        self.assertEqual(self.check("--out", self.base), 0)

    def write(self, name, text):
        path = os.path.join(self.site, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self, *extra):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return cli.main(["check", self.site, "--site", SITE, *extra])

    def data(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_old_debt_does_not_fail_the_build(self):
        out = os.path.join(self.dir, "now.json")
        self.assertEqual(self.check("--baseline", self.base, "--strict", "--out", out), 0)
        self.assertEqual(self.data(out)["baseline"]["new"], [])

    def test_without_baseline_strict_still_fails_on_debt(self):
        self.assertEqual(self.check("--strict", "--out", os.path.join(self.dir, "x.json")), 1)

    def test_a_new_critical_fails_and_is_named(self):
        self.write("b/index.html", page(""))
        out = os.path.join(self.dir, "now.json")
        self.assertEqual(self.check("--baseline", self.base, "--strict", "--out", out), 1)
        new = self.data(out)["baseline"]["new"]
        self.assertIn({"level": "critical", "url": SITE + "/b/", "code": "no-title"},
                      [{k: i[k] for k in ("level", "url", "code")} for i in new])
        self.assertNotIn(SITE + "/a/", [i["url"] for i in new])
        self.assertIn("/b/", self.stdout.getvalue())

    def test_a_new_warning_does_not_fail_strict(self):
        # --strict падает на критичных; база этого не меняет.
        self.write("b/index.html", page("Аренда Б", body="коротко"))
        out = os.path.join(self.dir, "now.json")
        code = self.check("--baseline", self.base, "--strict", "--out", out)
        new = self.data(out)["baseline"]["new"]
        self.assertFalse([i for i in new if i["level"] == "critical"])
        self.assertEqual(code, 0)

    def test_fixed_findings_are_listed(self):
        self.write("a/index.html", page("Аренда А"))
        out = os.path.join(self.dir, "now.json")
        self.assertEqual(self.check("--baseline", self.base, "--out", out), 0)
        fixed = self.data(out)["baseline"]["fixed"]
        self.assertIn(("no-title", SITE + "/a/"), [(i["code"], i["url"]) for i in fixed])

    def test_url_spelling_does_not_make_a_finding_new(self):
        # Базу могли снять с другим --site: со слэшем на конце, в другом регистре хоста.
        out = os.path.join(self.dir, "now.json")
        self.stdout = io.StringIO()
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", self.site, "--site", "https://EXAMPLE.com/",
                             "--baseline", self.base, "--strict", "--out", out])
        self.assertEqual(code, 0)
        self.assertEqual(self.data(out)["baseline"]["new"], [])

    def test_baseline_can_be_the_file_being_written(self):
        # Обычный CI: один и тот же indexgap-check.json — и база, и результат.
        self.assertEqual(self.check("--baseline", self.base, "--strict", "--out", self.base), 0)
        self.assertEqual(self.data(self.base)["baseline"]["new"], [])

    def test_a_foreign_file_is_refused(self):
        foreign = os.path.join(self.dir, "package.json")
        with open(foreign, "w", encoding="utf-8") as fh:
            json.dump({"name": "site"}, fh)
        self.assertEqual(self.check("--baseline", foreign, "--out",
                                    os.path.join(self.dir, "x.json")), 2)
        self.assertIn("package.json", self.stderr.getvalue())

    def test_a_missing_baseline_says_how_to_make_one(self):
        missing = os.path.join(self.dir, "nope.json")
        self.assertEqual(self.check("--baseline", missing, "--out",
                                    os.path.join(self.dir, "x.json")), 2)
        self.assertIn("--out", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()


class ExitCodes(Baseline):
    def test_a_missing_sitemap_file_is_an_error(self):
        self.assertEqual(self.check("--sitemap", os.path.join(self.dir, "nope.xml"),
                                    "--out", os.path.join(self.dir, "x.json")), 2)
        self.assertIn("nope.xml", self.stderr.getvalue())

    def test_a_missing_robots_file_is_an_error(self):
        self.assertEqual(self.check("--robots", os.path.join(self.dir, "robots.txt"),
                                    "--out", os.path.join(self.dir, "x.json")), 2)
