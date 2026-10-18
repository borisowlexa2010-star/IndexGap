# -*- coding: utf-8 -*-
"""Сводка прогона для страницы сборки в CI: `python -m indexgap.summary`."""

import contextlib
import io
import json
import os
import shutil
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


if __name__ == "__main__":
    unittest.main()
