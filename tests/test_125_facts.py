# -*- coding: utf-8 -*-
"""
1.25: сверка фактов — что читалось не так, как написано на странице.

* два значения, поровну делящие колонку, оба становились «постоянными сайта»;
* «34min», «145000円» в ячейке не давали строке её числа;
* «a 55-minute commute», «44 min», «4 month» не читались как единица проекта;
* «$ 2,900», «€ 1.900» с пробелом не читались вовсе;
* второй край диапазона и числа перечисления перед единицей проекта;
* «из строки» — квадраты одного числа и счёт, не сходящийся по единицам;
* «$1.6k», «14万5000円»;
* JSON-датасет читался как CSV и молча выключал сверку;
* выдуманная цена в <title> и meta description.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, content, generate
from indexgap.core import SourceError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"
UNITS = ["minutes", "months"]


def strong(text, units=UNITS):
    return content._numbers_in(text, content.build_fact_pattern(units))


def run_check(folder, dataset):
    out = os.path.join(folder, "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        cli.main(["check", folder, "--site", SITE, "--dataset", dataset, "--out", out])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)["issues"], printed.getvalue()


class Demo(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="indexgap-125-"), "site")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir), True)
        shutil.copytree(DEMO, self.dir)
        self.dataset = os.path.join(self.dir, "cities.csv")

    def edit(self, slug, change):
        path = os.path.join(self.dir, "rent", slug, "index.html")
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(change(html))

    def add(self, slug, sentence):
        self.edit(slug, lambda h: h.replace(" minutes.", " minutes. " + sentence, 1))

    def found(self, slug, dataset=None):
        issues, _ = run_check(self.dir, dataset or self.dataset)
        return {i["code"]: i for i in issues if i["url"].endswith(f"/rent/{slug}/")}


class TestSiteConstants(unittest.TestCase):
    def test_an_even_split_is_not_a_constant(self):
        rows = [{"deposit": "2 months"}] * 4 + [{"deposit": "3 months"}] * 4
        self.assertEqual(content._site_constants(rows), set())

    def test_a_shared_range_stays_constant(self):
        self.assertEqual(content._site_constants([{"term": "3-5 days"}] * 4), {"3", "5"})

    def test_a_clear_majority_stays_constant(self):
        # 1.27: a runner-up in a quarter of the top or more is row data, not
        # an exception (6:4 is now per-row); a rare exception keeps the constant.
        rows = [{"fee": "500"}] * 9 + [{"fee": "700"}] * 1
        self.assertEqual(content._site_constants(rows), {"500"})


class TestSwappedDeposit(Demo):
    def test_another_citys_deposit_is_reported(self):
        # В демо колонка deposit поровну делится между 2 и 3 месяцами.
        self.edit("munich", lambda h: h.replace("deposit of 3 months", "deposit of 2 months", 1))
        self.assertIn("2 months", self.found("munich")["unsupported-number"]["message"])


class TestGluedUnitsInTheRow(unittest.TestCase):
    def test_numbers_with_a_glued_unit(self):
        for cell, number in (("34min", "34"), ("1450EUR", "1450"), ("45m²", "45"),
                             ("145000円", "145000"), ("34分", "34")):
            with self.subTest(cell=cell):
                self.assertIn(number, content._row_numbers({"x": cell}))

    def test_an_article_number_is_still_not_data(self):
        for cell in ("A90", "90A-15", "A-90-15", "v2beta"):
            with self.subTest(cell=cell):
                self.assertEqual(content._row_numbers({"x": cell}), set())

    def test_a_correct_page_is_quiet(self):
        rows = [{"keyword": "nagoya", "rent": "87000円", "commute": "31分"}]
        page = type("P", (), {"url": SITE + "/rent/nagoya/", "text": "家賃は月87,000円、駅まで31分です。",
                              "title": "", "description": "", "lang": "ja"})()
        out = content.check_facts([page], {page.url: rows[0]}, rows, fact_units=["円", "分"])
        self.assertEqual([i for i in out if i[0] == "critical"], [])


class TestUnitSpellings(unittest.TestCase):
    def test_hyphenated_compounds(self):
        self.assertEqual(strong("Expect a 55-minute commute"), {"55": "minute"})
        self.assertEqual(strong("a 6-month deposit"), {"6": "month"})

    def test_singular_and_short_forms(self):
        self.assertIn("44", strong("the commute is 44 min"))
        self.assertIn("44", strong("the commute is 44 mins"))
        self.assertIn("4", strong("a deposit of 4 month"))

    def test_a_reading_time_is_not_a_fact(self):
        self.assertEqual(strong("5 min read"), {})

    def test_spelled_compound(self):
        patterns = content.build_spelled_patterns(UNITS)
        self.assertEqual(content._spelled_numbers_in("a six-month deposit", patterns, "en"),
                         {"6": ("month", "six-month")})

    def test_a_wrong_hyphenated_fact_is_critical(self):
        rows = [{"keyword": "berlin", "deposit": "3 months", "commute": "34 minutes"}]
        page = type("P", (), {"url": SITE + "/rent/berlin/", "lang": "en", "title": "",
                              "description": "",
                              "text": "Landlords ask for a 4-month deposit; a 44-minute ride."})()
        out = content.check_facts([page], {page.url: rows[0]}, rows, fact_units=UNITS)
        self.assertEqual([i[0] for i in out], ["critical"])
        self.assertIn("44", out[0][3])
        self.assertIn("4 month", out[0][3])


class TestPrices(unittest.TestCase):
    def test_space_after_the_sign(self):
        for text, number in (("ask $ 2,900 for", "2900"), ("€ 1.900 pro Monat", "1900"),
                             ("£ 1,900", "1900"), ("₹ 1,900", "1900")):
            with self.subTest(text=text):
                self.assertIn(number, content._numbers_in(text, None))

    def test_a_sign_after_a_number_is_not_the_next_price(self):
        self.assertEqual(content._numbers_in("1.900 € 12 Monate", None), {"1900": "€"})

    def test_k_suffix(self):
        self.assertEqual(content._numbers_in("$1.6k per unit", None), {"1600": "$ k"})
        self.assertEqual(content._numbers_in("$1.45K a month", None), {"1450": "$ K"})
        self.assertEqual(content._shown("1900", "$ k"), "$1.9k")
        self.assertFalse(content._supported("5000", "kg", {"5"}), "k in kg is not a thousand")
        self.assertEqual(content._numbers_in("18945 kgbp", None), {}, "k glued to a word")

    def test_cjk_compound(self):
        self.assertEqual(content._numbers_in("月14万5000円です", None), {"145000": "円"})
        self.assertEqual(content._numbers_in("9万8千円", None), {"98000": "円"})
        self.assertEqual(content._numbers_in("3万円", None), {"30000": "万円"})


class TestRangesAndLists(unittest.TestCase):
    def test_both_ends_of_a_range(self):
        self.assertEqual(set(strong("takes 12–27 minutes")), {"12", "27"})
        self.assertEqual(set(strong("4 to 6 months")), {"4", "6"})
        self.assertEqual(set(strong("10–15%")), {"10", "15"})
        self.assertEqual(set(strong("$1,600–2,400 per month")), {"1600", "2400"})
        self.assertEqual(set(strong("$950 to 1,900")), {"950", "1900"})
        self.assertEqual(set(strong("$1.5–2 million")), {"1500000", "2000000"})

    def test_lists_before_a_project_unit(self):
        self.assertEqual(set(strong("50 or 70 minutes")), {"50", "70"})
        self.assertEqual(set(strong("3, 4 or 5 months")), {"3", "4", "5"})

    def test_what_is_not_a_range(self):
        self.assertEqual(strong("From $1,450 - 2 bedrooms"), {"1450": "$"})
        self.assertEqual(strong("Route 66-5 minutes"), {"5": "minutes"})
        self.assertEqual(strong("COVID-19 5 minutes"), {"5": "minutes"})
        self.assertEqual(strong("$1,500 – 2026 prices"), {"1500": "$"})


class TestComputedFromTheRow(unittest.TestCase):
    ROW = {"rent": "$2,100", "deposit": "3 months", "commute": "34 minutes"}

    def how(self, number, unit):
        return content._derivation(number, content._row_numbers(self.ROW),
                                   content._row_kinds(self.ROW), content._kind(unit))

    def test_a_real_computation_is_still_for_the_eye(self):
        self.assertEqual(self.how("6300", "$"), "3 × 2100")

    def test_what_does_not_add_up(self):
        self.assertEqual(content._derivation("961", {"31", "1450"}), "", "a square")
        self.assertEqual(self.how("2037", "$"), "", "3 months are not a percent")
        self.assertEqual(self.how("102", "minutes"), "", "minutes × months")
        self.assertEqual(self.how("1156", "$"), "", "34 × 34")

    def test_a_real_percent(self):
        row = {"rent": "$1,450", "discount": "10%"}
        self.assertEqual(content._derivation("1305", content._row_numbers(row),
                                             content._row_kinds(row), "money"), "1450 − 10%")


class TestHead(Demo):
    def test_a_wrong_price_in_the_title(self):
        self.edit("berlin", lambda h: h.replace("<title>", "<title>From $1,900: ", 1))
        self.assertIn("$1900", self.found("berlin")["unsupported-number"]["message"])

    def test_a_wrong_price_in_the_description(self):
        tag = '<meta name="description" content="A flat costs $1,900 here.">'
        self.edit("berlin", lambda h: h.replace("</head>", tag + "</head>", 1))
        self.assertIn("$1900", self.found("berlin")["unsupported-number"]["message"])

    def test_correct_head_is_quiet(self):
        self.edit("berlin", lambda h: h.replace("<title>", "<title>From $1,450: ", 1))
        self.assertNotIn("unsupported-number", self.found("berlin"))


class TestDatasetFormats(Demo):
    def json_dataset(self, body, name="cities.json"):
        path = os.path.join(os.path.dirname(self.dir), name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_json_rows_are_read(self):
        data = generate.read_dataset(self.dataset)
        path = self.json_dataset(json.dumps(data["rows"]))
        self.assertEqual(generate.read_dataset(path)["rows"], data["rows"])
        found = self.found("hamburg", path)
        self.assertIn("$1900", found["unsupported-number"]["message"])

    def test_json_lines_and_a_wrapped_array(self):
        rows = [{"keyword": "a", "price": 5}, {"keyword": "b", "price": None}]
        lines = self.json_dataset("\n".join(json.dumps(r) for r in rows), "x.jsonl")
        self.assertEqual(generate.read_dataset(lines)["rows"],
                         [{"keyword": "a", "price": "5"}, {"keyword": "b", "price": ""}])
        wrapped = self.json_dataset(json.dumps({"rows": rows}), "y.json")
        self.assertEqual(len(generate.read_dataset(wrapped)["rows"]), 2)

    def test_other_json_is_refused(self):
        with self.assertRaises(SourceError):
            generate.read_dataset(self.json_dataset('{"a": 1}', "z.json"))

    def test_an_empty_dataset_is_said_out_loud(self):
        path = self.json_dataset("keyword,rent\n", "empty.csv")
        _, printed = run_check(self.dir, path)
        self.assertIn("нет ни одной строки", printed)


if __name__ == "__main__":
    unittest.main()
