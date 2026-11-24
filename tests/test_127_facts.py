# -*- coding: utf-8 -*-
"""
1.27: сверка фактов — что проходило молча или поднималось зря.

* множитель со страницы («$3k», «$34 million») снимался с любого числа строки;
* «44分です» — за единицей CJK сразу идёт кана, и выдумка уходила в мелочи;
* «34 min» и «3 mo» в данных не давали «minutes» и «months» в тексте;
* «$1450-2000 a month» — верхний край, похожий на год, пропадал;
* дата и адрес в ячейке давали строке числа месяца и дня;
* число из чужой колонки поддерживало перестановку полей шаблона;
* постоянная сайта по простому большинству прощала чужой залог;
* обратный диапазон «50 to 34 minutes» терял первый край;
* «$1,450 – 1600 Oak Avenue» читалось как диапазон цен;
* единица в названии колонки (`rent_usd`) не участвовала в счёте «из строки».
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import content

SITE = "https://demo.example"
UNITS = ["minutes", "months"]
ROW = {"keyword": "alpha", "rent": "$1,450", "deposit": "3 months", "commute": "34 minutes"}
OTHERS = [{"keyword": "beta", "rent": "$2,100", "deposit": "2 months", "commute": "29 minutes"},
          {"keyword": "gamma", "rent": "$1,600", "deposit": "4 months", "commute": "31 minutes"}]


def page(text, lang="en"):
    return type("P", (), {"url": SITE + "/p/alpha/", "lang": lang, "title": "",
                          "description": "", "text": text})()


def facts(text, row=ROW, others=OTHERS, units=UNITS, lang="en"):
    """{уровень: множество чисел} по странице строки `row`."""
    rows = [row] + list(others)
    p = page(text, lang)
    out = {}
    for level, _, _, said in content.check_facts([p], {p.url: row}, rows, fact_units=units):
        out.setdefault(level, set()).update(said.subject if hasattr(said, "subject") else said)
    return out


def critical(text, **kw):
    return facts(text, **kw).get("critical", set())


class TestScaleSuffix(unittest.TestCase):
    def test_a_scale_does_not_turn_a_row_number_into_a_price(self):
        found = critical("Rent is $1,450, deposit 3 months, commute 34 minutes. "
                         "A bond of $3k, parking $34k a year.")
        self.assertEqual(found, {"3000", "34000"})
        self.assertEqual(critical("Rent is $1,450. Buying costs $1,450k."), {"1450000"})
        self.assertEqual(critical("Rent is $1,450. A building sells for $34 million."),
                         {"34000000"})

    def test_a_bare_number_or_a_scaled_column_still_supports(self):
        row = {"keyword": "alpha", "price": "12.5"}
        self.assertEqual(critical("It costs $12.5 million.", row=row, others=[]), set())
        row = {"keyword": "alpha", "price_k": "1.6"}
        self.assertEqual(critical("It costs $1.6k or $1,600.", row=row, others=[]), set())
        self.assertEqual(content._column_scale("k"), 1, "a column named k is a key")


class TestCjkUnitBoundary(unittest.TestCase):
    ROW = {"keyword": "alpha", "rent": "145000円", "deposit": "3ヶ月", "commute": "34分"}
    UNITS = ["ヶ月", "円", "分"]

    def test_kana_after_the_unit(self):
        for text, number in (("通勤は44分です。", "44"), ("敷金は5ヶ月分が必要。", "5")):
            with self.subTest(text=text):
                self.assertIn(number, critical(text, row=self.ROW, others=[],
                                               units=self.UNITS, lang="ja"))

    def test_the_right_numbers_still_pass(self):
        self.assertEqual(critical("家賃は145000円です。敷金は3ヶ月分、通勤は34分です。",
                                  row=self.ROW, others=[], units=self.UNITS, lang="ja"), set())


class TestShortUnitsInData(unittest.TestCase):
    def test_short_forms_give_long_ones(self):
        forms = content._unit_forms(["min", "mo"])
        for word in ("minutes", "minute", "months", "month"):
            self.assertIn(word, forms)
        row = {"keyword": "alpha", "rent": "$1450", "deposit": "3 mo", "commute": "34min"}
        self.assertEqual(critical("Deposit 5 months, commute 44 minutes.", row=row,
                                  others=[], units=["min", "mo"]), {"5", "44"})
        self.assertEqual(critical("Deposit 3 months, commute 34 minutes.", row=row,
                                  others=[], units=["min", "mo"]), set())


class TestYearLikeRangeEnd(unittest.TestCase):
    def test_a_price_range_with_a_period(self):
        self.assertIn("2000", critical("Rent is $1450-2000 a month."))
        self.assertIn("2000", critical("Rent is $1,450–2000 per month."))

    def test_a_year_after_a_price_is_still_a_year(self):
        self.assertEqual(critical("Rent from $1,450 – 2026 guide."), set())
        self.assertEqual(critical("Rent in Alpha from $1,450 – 2026"), set())

    def test_a_year_like_number_inside_a_list(self):
        self.assertIn("1950", critical("Flats cost $1,450, 1950 or 2100 dollars."))
        text = "In 2026, 15 or 20 minutes"
        self.assertEqual(content._listed_before(text, text.index("20 min")), ["15"])


class TestDatesAndUrlsInTheRow(unittest.TestCase):
    def test_a_date_column_does_not_support_facts(self):
        for value in ("2026-11-18", "18.11.2026", "2026-11-18T10:30:00Z",
                      "https://data.example/2026/11/18/alpha"):
            with self.subTest(value=value):
                row = dict(ROW, checked=value)
                others = [dict(o, checked=value) for o in OTHERS]
                self.assertEqual(critical("Rent is $1,450, deposit 11 months, commute "
                                          "18 minutes.", row=row, others=others),
                                 {"11", "18"})

    def test_a_date_on_the_page_is_still_fine(self):
        row = {"keyword": "alpha", "rent": "145000円", "checked": "2026-11-18"}
        self.assertEqual(critical("11月18日に確認。家賃は145000円。", row=row, others=[],
                                  units=["円", "日", "月"], lang="ja"), set())

    def test_other_numbers_with_hyphens_still_count(self):
        row = {"keyword": "alpha", "processing": "3-5 days"}
        self.assertEqual(critical("Processing takes 3 to 5 days.", row=row, others=[],
                                  units=["days"]), set())


class TestSwappedSlots(unittest.TestCase):
    def test_a_number_from_another_measure(self):
        self.assertEqual(critical("Rent is $1,450, deposit 34 months, commute 3 minutes."),
                         {"34", "3"})
        self.assertEqual(critical("Rent is $34 a month, deposit 1450 months."),
                         {"34", "1450"})

    def test_a_bare_or_unknown_measure_supports_anything(self):
        row = {"keyword": "alpha", "rent_usd": "1450", "deposit": "3", "commute": "34 min by car"}
        self.assertEqual(critical("Rent is $1,450, deposit 3 months, commute 34 minutes.",
                                  row=row, others=[]), set())

    def test_same_measure_in_another_language_form(self):
        row = {"keyword": "alpha", "deposit": "3 месяца", "commute": "34 мин"}
        self.assertEqual(critical("Залог 3 месяцев, дорога 34 минуты.", row=row, others=[],
                                  units=["месяца", "мин", "минуты", "месяцев"], lang="ru"),
                         set())
        self.assertEqual(content._measure("mins"), content._measure("minutes"))
        self.assertEqual(content._measure("$ k"), "money")


class TestSiteConstantsNeedNearUnanimity(unittest.TestCase):
    def test_a_frequent_runner_up_is_row_data(self):
        rows = [{"deposit": "3 months"}] * 5 + [{"deposit": "2 months"}] * 3
        self.assertEqual(content._site_constants(rows), set())

    def test_a_rare_exception_keeps_the_constant(self):
        rows = [{"fee": "500"}] * 9 + [{"fee": "700"}]
        self.assertEqual(content._site_constants(rows), {"500"})

    def test_a_swapped_deposit_on_a_minority_row(self):
        row = {"keyword": "alpha", "deposit": "2 months"}
        others = [{"keyword": f"c{i}", "deposit": "3 months"} for i in range(5)] \
            + [{"keyword": f"d{i}", "deposit": "2 months"} for i in range(2)]
        self.assertEqual(critical("A deposit of 3 months.", row=row, others=others), {"3"})


class TestDescendingRange(unittest.TestCase):
    def test_the_first_end_goes_to_the_eye(self):
        found = facts("Rent is $1,450, deposit 3 months. The commute takes 50 to 34 "
                      "minutes depending on traffic.")
        self.assertEqual(found.get("critical", set()), set())
        self.assertIn("50", found.get("info", set()))


class TestHouseNumberAfterAPrice(unittest.TestCase):
    def test_a_street_number_is_not_a_range_end(self):
        self.assertEqual(critical("Rent is $1,450 – 1600 Oak Avenue, a deposit of 3 months "
                                  "and a commute of 34 minutes."), set())
        self.assertEqual(set(content._numbers_in("$1,450 – 1600 Oak Avenue", None)), {"1450"})

    def test_a_currency_word_keeps_the_range(self):
        self.assertEqual(set(content._numbers_in("€1.450 – 2.000 Euro", None)), {"1450", "2000"})
        self.assertIn("2200", critical("Rent is $1,450 – 2200 a month."))


class TestUnitInTheColumnName(unittest.TestCase):
    def test_a_total_from_bare_cells_goes_to_the_eye(self):
        row = {"keyword": "alpha", "rent_usd": "1450", "deposit_months": "3",
               "commute_minutes": "34"}
        found = facts("Rent is $1,450 a month and the deposit is 3 months, so you pay "
                      "$4,350 before moving in.", row=row, others=[])
        self.assertEqual(found.get("critical", set()), set())
        self.assertIn("4350", found.get("info", set()))


class TestDemoStillClean(unittest.TestCase):
    def test_demo_site_findings_do_not_grow(self):
        from indexgap import cli
        import io
        import json
        import sys
        from unittest import mock
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        folder = os.path.join(tempfile.mkdtemp(prefix="indexgap-127-"), "site")
        self.addCleanup(shutil.rmtree, os.path.dirname(folder), True)
        shutil.copytree(os.path.join(root, "examples", "demo-site"), folder)
        out = os.path.join(folder, "r.json")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", folder, "--site", SITE, "--dataset",
                      os.path.join(folder, "cities.csv"), "--out", out])
        with open(out, encoding="utf-8") as fh:
            issues = json.load(fh)["issues"]
        wrong = sorted(i["url"] for i in issues if i["code"] == "unsupported-number")
        # Единственная выдумка демо — цена в Гамбурге.
        self.assertEqual(wrong, [SITE + "/rent/hamburg/"])


if __name__ == "__main__":
    unittest.main()
