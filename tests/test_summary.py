# -*- coding: utf-8 -*-
"""Сводка прогона для страницы сборки в CI: `python -m indexgap.summary`."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import summary

DATA = {
    "_indexgap": "1.13.0", "site": "https://example.com", "pages": 3,
    "issues": [
        {"level": "critical", "url": "https://example.com/a/", "code": "no-title", "message": "нет title"},
        {"level": "critical", "url": "https://example.com/b/", "code": "no-title", "message": "нет title"},
        {"level": "warning", "url": "https://example.com/b/", "code": "thin", "message": "мало | текста"},
        {"level": "info", "url": "https://example.com/", "code": "no-date", "message": "нет даты"},
    ],
}


class Summary(unittest.TestCase):
    def test_counts_by_level_and_most_frequent_codes(self):
        text = summary.render(DATA)
        self.assertIn("| 2 | 1 | 1 |", text)
        self.assertIn("`no-title` | 2 |", text)
        # Сведения в «чаще всего» не попадают: там то, что чинить.
        self.assertNotIn("`no-date`", text)

    def test_new_critical_findings_against_the_baseline_are_listed(self):
        data = dict(DATA, baseline={"new": [DATA["issues"][1], DATA["issues"][2]],
                                    "fixed": [DATA["issues"][0]]})
        text = summary.render(data)
        self.assertIn("новых 2, из них критичных 1; исчезло 1", text)
        self.assertIn("https://example.com/b/", text)
        # Показываются критичные: предупреждение в списке новых критичных — шум.
        self.assertNotIn("мало", text)

    def test_a_pipe_in_a_message_does_not_break_the_table(self):
        data = dict(DATA, baseline={"new": [DATA["issues"][2]], "fixed": []})
        self.assertIn("мало \\| текста", summary.render(data))

    def test_empty_run(self):
        self.assertIn("Находок нет.", summary.render({"pages": 0, "issues": []}))

    def test_main_reads_the_file(self):
        root = tempfile.mkdtemp(prefix="indexgap-summary-")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "indexgap-check.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(DATA, fh)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(summary.main([path]), 0)
        self.assertIn("### indexgap: 3", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(summary.main([os.path.join(root, "nope.json")]), 2)


class SummaryOutput(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-summary-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def _file(self, payload, name="indexgap-check.json"):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        return path

    def _run(self, stdout, path):
        old = sys.stdout
        sys.stdout = stdout
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = summary.main([path])
        finally:
            sys.stdout = old
        return code, err.getvalue()

    def test_cyrillic_url_on_a_cp1252_console_is_written_as_utf8(self):
        """Windows, Python 3.12: stdout в cp1252, а в отчёте — кириллический домен."""
        data = dict(DATA, site="https://пример.рф")
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding="cp1252")
        code, _ = self._run(stdout, self._file(data))
        stdout.flush()
        self.assertEqual(code, 0)
        self.assertIn("https://пример.рф", raw.getvalue().decode("utf-8"))

    def test_a_stream_that_cannot_be_reconfigured_gets_utf8_bytes(self):
        class Locked(io.TextIOWrapper):
            def reconfigure(self, **kwargs):
                raise ValueError("locked")

        raw = io.BytesIO()
        stdout = Locked(raw, encoding="cp1252")
        code, _ = self._run(stdout, self._file(dict(DATA, site="https://пример.рф")))
        stdout.flush()
        self.assertEqual(code, 0)
        self.assertIn("https://пример.рф", raw.getvalue().decode("utf-8"))

    def test_doctor_and_portfolio_data_are_refused(self):
        doctor = {"_indexgap": "1.15.0", "schema": 2, "site": "https://example.com",
                  "funnel": {}, "causes": [], "cross_engine": None, "notes": []}
        portfolio = {"_indexgap": "1.15.0", "schema": 2, "projects": [], "patterns": [],
                     "unique": []}
        plan = {"_indexgap": "1.15.0", "schema": 2, "total": 1, "keep": [], "rejected": []}
        for name, payload, word in (("doctor", doctor, "doctor"),
                                    ("portfolio", portfolio, "portfolio"),
                                    ("plan", plan, "plan")):
            with self.subTest(name):
                out = io.StringIO()
                code, err = self._run(out, self._file(payload, name + ".json"))
                self.assertEqual(code, 2)
                self.assertEqual(out.getvalue(), "")
                self.assertIn("indexgap " + word, err)
                self.assertIn("indexgap check", err)

    def test_unknown_object_is_refused(self):
        code, err = self._run(io.StringIO(), self._file({"hello": 1}, "x.json"))
        self.assertEqual(code, 2)
        self.assertIn("это не данные прогона indexgap check", err)



DIFF = {
    "_indexgap": "1.17.0", "schema": 2, "site": "https://example.com",
    "old": {"root": "old", "pages": 9}, "new": {"root": "new", "pages": 8},
    "redirects": [], "dataset": None,
    "summary": {"critical": 2, "warning": 1, "info": 1},
    "items": [
        {"level": "critical", "url": "https://example.com/city/c3/", "code": "page-removed",
         "message": "была открыта для индекса | 404"},
        {"level": "critical", "url": "https://example.com/city/c5/", "code": "new-finding",
         "message": "no-title — нет title"},
        {"level": "warning", "url": "/city/*/", "code": "template-change",
         "message": "title изменился"},
        {"level": "info", "url": "/city/*/", "code": "pages-added", "message": "новых страниц: 1"},
    ],
    "removed": [], "closed": [], "opened": [], "nosnippet": [], "shrunk": [],
    "template_changes": [], "added": {"total": 0, "by_pattern": [], "urls": []},
    "findings": {"new": [], "fixed": [], "new_critical": 1, "new_warning": 0,
                 "fixed_critical": 2},
}


class DiffSummary(unittest.TestCase):
    """Данные `indexgap diff` получают свою сводку, а не отказ."""

    def test_counts_by_level_and_the_critical_items(self):
        text = summary.render_diff(DIFF)
        self.assertIn("### indexgap diff: 9 → 8", text)
        self.assertIn("https://example.com", text)
        self.assertIn("| 2 | 1 | 1 |", text)
        self.assertIn("`page-removed` https://example.com/city/c3/", text)
        self.assertIn("`new-finding` https://example.com/city/c5/", text)
        self.assertIn("\\| 404", text)
        # Предупреждения и сведения в список критичного не идут.
        self.assertNotIn("template-change", text)
        self.assertIn("новых критичных 1", text)
        self.assertIn("исчезло критичных 2", text)

    def test_nothing_critical_says_so(self):
        data = dict(DIFF, summary={"critical": 0, "warning": 0, "info": 0}, items=[],
                    findings=None)
        text = summary.render_diff(data)
        self.assertIn("Разницы, которая ломает индекс, нет.", text)
        self.assertNotIn("Находки check", text)

    def test_main_accepts_diff_data(self):
        root = tempfile.mkdtemp(prefix="indexgap-summary-")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "indexgap-diff.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(DIFF, fh, ensure_ascii=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(summary.main([path]), 0)
        self.assertIn("### indexgap diff", out.getvalue())

    def test_real_diff_output_is_summarised(self):
        from indexgap import cli
        root = tempfile.mkdtemp(prefix="indexgap-summary-")
        self.addCleanup(shutil.rmtree, root, True)
        for side in ("old", "new"):
            for i in range(3):
                if side == "new" and i == 1:
                    continue
                path = os.path.join(root, side, f"p{i}", "index.html")
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(f"<html lang=\"ru\"><head><title>Страница {i} сайта</title></head>"
                             f"<body><main><h1>Страница {i}</h1><p>"
                             + " ".join(f"слово{n}" for n in range(80))
                             + "</p></main></body></html>")
        data = os.path.join(root, "d.json")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["diff", os.path.join(root, "old"), os.path.join(root, "new"),
                      "--site", "https://example.com", "--out", data])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(summary.main([data]), 0)
        self.assertIn("`page-removed` https://example.com/p1/", out.getvalue())


if __name__ == "__main__":
    unittest.main()
