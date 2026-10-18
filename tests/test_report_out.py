# -*- coding: utf-8 -*-
"""
`--out report.json` писал HTML-отчёт в файл с расширением .json, а данные —
туда же, и второй запуск отказывался: «report.json уже существует и это не
данные отчёта». Имя с .json — это имя данных; отчёт ложится рядом, .html.
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
from indexgap.core import REPORT_MARK

SITE = "https://example.com"
PAGE = ("<!doctype html><html lang=\"ru\"><head><title>Аренда техники в Омске</title>"
        "<meta name=\"description\" content=\"Аренда экскаватора в Омске\"></head>"
        "<body><main><h1>Аренда техники</h1><p>Текст страницы про аренду.</p></main>"
        "</body></html>")


class OutNamedJson(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-out-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.site = os.path.join(self.dir, "site")
        os.makedirs(self.site)
        with open(os.path.join(self.site, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(PAGE)

    def run_check(self, out):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return cli.main(["check", self.site, "--site", SITE, "--out", out])

    def test_json_name_gets_data_and_the_report_goes_beside_it(self):
        out = os.path.join(self.dir, "report.json")
        self.assertEqual(self.run_check(out), 0)
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["pages"], 1)
        with open(os.path.join(self.dir, "report.html"), encoding="utf-8") as fh:
            self.assertIn(REPORT_MARK, fh.read())

    def test_second_run_overwrites_its_own_files(self):
        out = os.path.join(self.dir, "report.json")
        self.assertEqual(self.run_check(out), 0)
        self.assertEqual(self.run_check(out), 0)

    def test_html_name_still_works_as_before(self):
        out = os.path.join(self.dir, "r.html")
        self.assertEqual(self.run_check(out), 0)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "r.json")))


if __name__ == "__main__":
    unittest.main()
