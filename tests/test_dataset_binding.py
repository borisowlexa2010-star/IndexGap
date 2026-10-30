# -*- coding: utf-8 -*-
"""
Связь страниц со строками датасета — то, на чём держится главная проверка.

Ревьюер концепции превратил CSV демо в обычный для жизни: колонка `query`
(«cheap apartments for rent in Berlin») и колонка `slug` (`berlin`). Итог —
«Сверено с датасетом: 0 из 10», выдуманная цена `$1,900` пропала из отчёта,
и ни одного слова о том, что сверка не работала. Колонка `slug` не читалась.
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

DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "examples", "demo-site")
SITE = "https://demo.example"


class Binding(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-bind-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.site = os.path.join(self.dir, "site")
        shutil.copytree(DEMO, self.site)
        os.remove(os.path.join(self.site, "cities.csv"))

    def run_check(self, csv_text):
        path = os.path.join(self.dir, "rows.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(csv_text)
        out = os.path.join(self.dir, "r.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", self.site, "--site", SITE, "--dataset", path,
                             "--no-aeo", "--out", out])
        self.assertEqual(code, 0, buf.getvalue()[-500:])
        self.console = buf.getvalue()
        return json.load(open(out, encoding="utf-8"))

    def demo_rows(self, key_column, key, slug_column=None):
        import csv
        with open(os.path.join(DEMO, "cities.csv"), encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        fields = [f for f in rows[0] if f != "keyword"]
        header = [key_column] + ([slug_column] if slug_column else []) + fields
        lines = [",".join(header)]
        for row in rows:
            city = row.get("city", "")
            cells = [key(row, city)] + ([city.lower()] if slug_column else []) + \
                    [f'"{row[f]}"' if "," in row[f] else row[f] for f in fields]
            lines.append(",".join(cells))
        return "\n".join(lines) + "\n"

    def test_a_slug_column_binds_rows_to_pages(self):
        data = self.run_check(self.demo_rows(
            "query", lambda row, city: f"cheap apartments for rent in {city}", "slug"))
        self.assertIn("unsupported-number", [i["code"] for i in data["issues"]])

    def test_a_dataset_that_binds_to_nothing_is_said_out_loud(self):
        data = self.run_check(self.demo_rows(
            "query", lambda row, city: f"cheap apartments for rent in {city}"))
        codes = [i["code"] for i in data["issues"]]
        self.assertIn("dataset-unbound", codes)
        self.assertIn("slug", " ".join(i["message"] for i in data["issues"]
                                       if i["code"] == "dataset-unbound"))

    def test_rows_without_a_page_are_listed(self):
        text = self.demo_rows("keyword", lambda row, city: row["keyword"]) \
            + "atlantis,Atlantis,\"$1,000\",3 months,20 minutes\n"
        data = self.run_check(text)
        self.assertIn("atlantis", data["rows_without_page"])


if __name__ == "__main__":
    unittest.main()
