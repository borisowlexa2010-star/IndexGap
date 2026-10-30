# -*- coding: utf-8 -*-
"""
`ignore` в indexgap.json: находки, принятые намеренно.

`--strict` нельзя было включить на сайте, где `/login/` закрыт от индекса
сознательно, а OAI-SearchBot заблокирован по решению владельца: каждая
сборка падала на них же. База (`--baseline`) решает это для старого долга,
но не для решения, которое останется навсегда. Принятые находки не исчезают
молча — они считаются и названы отдельно.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli
from indexgap.core import SourceError

SITE = "https://example.com"


def page(title, robots=""):
    meta = f'<meta name="robots" content="{robots}">' if robots else ""
    return (f"<!doctype html><html lang=\"ru\"><head><title>{title} — страница сайта</title>"
            f"<meta name=\"viewport\" content=\"width=device-width\">{meta}"
            "<meta name=\"description\" content=\"Описание страницы сайта для проверки длины\">"
            f"</head><body><main><h1>{title}</h1><p>{' '.join(f'{title} слово{i} {title[::-1]}{i}' for i in range(80))}</p>"
            "<a href=\"/\">Главная</a> <a href=\"/login/\">Вход</a> <a href=\"/a/\">А</a>"
            "</main></body></html>")


class Ignore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-ignore-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name, text in {"index.html": page("Главная"), "a/index.html": page("Страница А"),
                           "login/index.html": page("Вход", robots="noindex")}.items():
            path = os.path.join(self.dir, "site", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    def config(self, ignore):
        path = os.path.join(self.dir, "indexgap.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pages": "site", "site": SITE, "ignore": ignore}, fh)
        return path

    def check(self, *extra):
        self.out = io.StringIO()
        self.err = io.StringIO()
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
            return cli.main(["check", "--config", self.config_path, "--no-aeo",
                             "--out", os.path.join(self.dir, "r.json"), *extra])

    def data(self):
        return json.load(open(os.path.join(self.dir, "r.json"), encoding="utf-8"))

    def test_without_ignore_strict_fails_on_the_closed_login(self):
        self.config_path = self.config({})
        self.assertEqual(self.check("--strict"), 1)

    def test_an_accepted_finding_does_not_fail_strict_and_is_counted(self):
        self.config_path = self.config({"noindex": ["/login/"]})
        self.assertEqual(self.check("--strict"), 0)
        data = self.data()
        self.assertNotIn("noindex", [i["code"] for i in data["issues"]])
        self.assertEqual([(i["code"], i["url"]) for i in data["accepted"]],
                         [("noindex", SITE + "/login/")])
        self.assertIn("1", self.out.getvalue())
        self.assertIn("ignore", self.out.getvalue())

    def test_patterns_and_true(self):
        issues = [("critical", SITE + "/login/", "noindex", ""),
                  ("critical", SITE + "/search/q/", "noindex", ""),
                  ("critical", SITE + "/a/", "noindex", ""),
                  ("critical", "robots.txt", "ai-crawler-blocked", ""),
                  ("warning", SITE + "/drafts/x/", "thin", "")]
        kept, accepted = checks.apply_ignore(issues, {
            "noindex": ["/login/", "/search/*"], "ai-crawler-blocked": True,
            "*": ["/drafts/*"]}, SITE)
        self.assertEqual([(i[1], i[2]) for i in kept], [(SITE + "/a/", "noindex")])
        self.assertEqual(len(accepted), 4)

    def test_a_typo_in_a_code_is_named(self):
        with self.assertRaises(SourceError) as caught:
            checks.apply_ignore([], {"noindx": ["/login/"]}, SITE)
        self.assertIn("noindex", str(caught.exception))

    def test_a_value_of_the_wrong_kind(self):
        with self.assertRaises(SourceError):
            checks.apply_ignore([], {"noindex": "/login/"}, SITE)


if __name__ == "__main__":
    unittest.main()
