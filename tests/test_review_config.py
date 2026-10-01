# -*- coding: utf-8 -*-
"""
Настройки, портфель, наряды и сборка пакета: находки ревью десяти агентов.

Порог, вписанный с опечаткой, молча не действовал; вписанный строкой — ронял
прогон трейсбеком; а `near_duplicate: 80` вместо `0.8` тихо выключал главную
проверку. Настройка, которую человек сделал руками, обязана либо сработать,
либо быть названной.
"""

import json
import os
import re
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core, portfolio, repair

SITE = "https://example.com"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def html(title):
    return (f"<html><head><title>{title} — страница сайта</title></head><body><main>"
            f"<h1>{title}</h1><p>{'слово ' * 300}</p><a href='/'>домой</a></main></body></html>")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-cfg-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def pages(self, prefix="site"):
        for name in ("index", "a/index", "b/index"):
            self.write(f"{prefix}/{name}.html", html(name))
        return core.load_pages(os.path.join(self.dir, prefix), SITE)[0]


class TestThresholds(Fixture):
    def test_unknown_or_mistyped_threshold_is_reported(self):
        result = checks.run_all(self.pages(), SITE + "/", cfg={"thin_wrods": 100})
        self.assertTrue(any("thin_wrods" in n and "thin_words" in n for n in result["notes"]),
                        result["notes"])

    def test_a_threshold_of_the_wrong_kind_is_an_error_with_words(self):
        pages = self.pages()
        for bad in ({"thin_words": "250"}, {"near_duplicate": 80}, {"shingle_size": 0},
                    {"lsh_bands": 0}, {"near_duplicate": 0.5, "similar": 0.7},
                    {"minhash_perms": 8, "lsh_bands": 16}):
            with self.assertRaises(core.SourceError, msg=bad):
                checks.run_all(pages, SITE + "/", cfg=bad)

    def test_valid_thresholds_pass(self):
        result = checks.run_all(self.pages(), SITE + "/", cfg={
            "thin_words": 100, "near_duplicate": 0.9, "similar": 0.6, "cjk_length_factor": 0.5})
        self.assertFalse(any("не знаю" in n for n in result["notes"]))


class TestPortfolio(Fixture):
    def test_broken_project_config_does_not_kill_portfolio(self):
        """Ошибка одного проекта записывается в его результат — так сказано в
        описании `run_one`, а битый indexgap.json ронял весь портфель."""
        self.pages("good")
        self.pages("bad")
        self.write("bad/indexgap.json", "{ not json")
        good = portfolio.run_one({"name": "good", "site": SITE,
                                  "root": os.path.join(self.dir, "good")}, quiet=True)
        bad = portfolio.run_one({"name": "bad", "site": SITE,
                                 "root": os.path.join(self.dir, "bad")}, quiet=True)
        self.assertEqual(good["error"], "")
        self.assertTrue(bad["error"])

    def test_a_project_name_cannot_leave_the_reports_directory(self):
        for name, safe in (("../../escaped", "escaped"), ("shop/de", "shop-de"),
                           ("my site", "my-site"), ("..", "project"), ("visa", "visa")):
            self.assertEqual(portfolio.report_name(name), safe)


class TestBriefs(Fixture):
    def test_stale_briefs_are_removed(self):
        out = os.path.join(self.dir, "briefs")
        first = [{"name": "x.md", "kind": "page", "title": "X", "body": "b", "count": 1},
                 {"name": "y.md", "kind": "page", "title": "Y", "body": "b", "count": 1},
                 {"name": "_duplicates/group-001.md", "kind": "group", "title": "G",
                  "body": "b", "count": 2}]
        repair.write(first, out)
        with open(os.path.join(out, "notes.md"), "w", encoding="utf-8") as fh:
            fh.write("мои заметки\n")
        repair.write(first[:1], out)
        left = sorted(os.path.relpath(os.path.join(base, f), out)
                      for base, _d, files in os.walk(out) for f in files)
        self.assertEqual(left, ["notes.md", "x.md"])


class TestPackaging(unittest.TestCase):
    def test_pyproject_version_matches_package(self):
        """Версия пишется в одном месте. Раньше поднять её только в `__init__`
        значило пройти все проверки и собрать колесо со старым номером."""
        from indexgap import __version__
        text = open(os.path.join(REPO, "pyproject.toml"), encoding="utf-8").read()
        self.assertNotRegex(text, r'(?m)^version\s*=\s*"')
        self.assertIn('dynamic = ["version"]', text)
        self.assertRegex(text, r'version\s*=\s*\{\s*attr\s*=\s*"indexgap\.__version__"')
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_the_test_helpers_ship_with_the_tests(self):
        manifest = open(os.path.join(REPO, "MANIFEST.in"), encoding="utf-8").read()
        self.assertIn("tests", manifest)
        self.assertIn("examples", manifest)


if __name__ == "__main__":
    unittest.main()
