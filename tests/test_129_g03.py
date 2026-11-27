# -*- coding: utf-8 -*-
"""
1.29 (g03): постоянные сайта, единицы в названиях колонок, расчёты из строки
и сверка фактов на китайских, японских и корейских страницах.
"""

import csv
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401
from indexgap import content, settings

SITE = "https://demo.example"
UNITS = ["minutes", "months"]


class P:
    def __init__(self, text, lang="en"):
        self.url, self.lang, self.title, self.description, self.text = (
            SITE + "/p/a/", lang, "", "", text)


def facts(text, row, others=(), units=UNITS, lang="en"):
    page = P(text, lang)
    out = {}
    for level, _, code, said in content.check_facts([page], {page.url: row}, [row] + list(others),
                                                    fact_units=units):
        out.setdefault(level, {})[code] = set(said.subject)
    return out


def critical(out):
    return out.get("critical", {}).get("unsupported-number", set())


def by_eye(out):
    return out.get("info", {}).get("check-by-eye", set())


class TestSiteConstants(unittest.TestCase):
    def test_many_unique_exceptions_are_row_data(self):
        rows = [{"deposit": v} for v in ["3 months"] * 4 + ["1 month", "2 months", "4 months",
                                                            "5 months"]]
        self.assertEqual(content._site_constants(rows), set())

    def test_a_rare_exception_still_keeps_the_constant(self):
        rows = [{"fee": "500"}] * 9 + [{"fee": "700"}]
        self.assertEqual(content._site_constants(rows), {"500"})

    def test_the_exception_row_is_not_forgiven_the_constant(self):
        rows = [{"keyword": f"k{i}", "rent": "$1,000", "fee": "$500"} for i in range(9)]
        odd = {"keyword": "odd", "rent": "$1,900", "fee": "$700"}
        self.assertEqual(critical(facts("Rent $1,900 a month, agency fee $500.", odd, rows)), {"500"})
        self.assertEqual(facts("Rent $1,900 a month, agency fee $700.", odd, rows), {})
        self.assertEqual(facts("Rent $1,000 a month, agency fee $500.", rows[0], rows[1:] + [odd]), {})

    def test_a_constant_keeps_its_measure(self):
        rows = [{"keyword": f"k{i}", "rent": f"${1000 + i * 100:,}", "deposit": "3 months",
                 "commute": f"{20 + i} minutes", "fee": "$250"} for i in range(8)]
        row = rows[0]
        self.assertEqual(critical(facts("Rent $1,000. The fee is $3.", row, rows[1:])), {"3"})
        self.assertEqual(critical(facts("Rent $1,000. Deposit 250 months.", row, rows[1:])), {"250"})
        self.assertEqual(facts("Rent $1,000, deposit 3 months, fee $250, commute 20 minutes.",
                               row, rows[1:]), {})

    def test_a_constant_also_counts_with_the_rows_own_measure(self):
        rows = [{"keyword": f"k{i}", "warranty": "12 months", "commute": f"{10 + i} minutes"}
                for i in range(6)]
        row = rows[2]  # commute 12 minutes
        self.assertEqual(facts("12 months of warranty and a 12 minutes walk.", row, rows), {})

    def test_a_bare_constant_fits_any_measure(self):
        rows = [{"keyword": f"k{i}", "rent": f"${1000 + i * 100:,}", "fee": "250"} for i in range(6)]
        self.assertEqual(facts("Rent $1,000 and a $250 fee.", rows[0], rows[1:]), {})


class TestIdentifiers(unittest.TestCase):
    def rows(self):
        return [{"keyword": f"k{i}", "rent": f"${1450 + i * 100:,}", "deposit": f"{2 + i % 3} months",
                 "phone": "+1 555 010 2000", "office": "12 Main Street, Suite 400"} for i in range(6)]

    def test_phone_and_address_do_not_forgive_invented_numbers(self):
        rows = self.rows()
        self.assertEqual(content._site_constants(rows), set())
        out = facts("About $2,000 a month. A deposit of 400 months.", rows[0], rows[1:])
        self.assertEqual(critical(out), {"2000", "400"})

    def test_a_page_that_repeats_the_contact_is_clean(self):
        rows = self.rows()
        self.assertEqual(facts("About $1,450 a month, deposit 2 months. Call +1 555 010 2000, "
                               "12 Main Street, Suite 400.", rows[0], rows[1:]), {})

    def test_shapes(self):
        self.assertTrue(content._is_identifier("phone", "555"))
        self.assertTrue(content._is_identifier("contact", "+1 555 010 2000"))
        self.assertFalse(content._is_identifier("hotel", "1 450 000"))
        self.assertFalse(content._is_identifier("checked", "2026-11-18"))
        self.assertFalse(content._is_identifier("term", "3-5 days"))

    def test_an_address_gives_no_fact_unit(self):
        rows = [{"keyword": f"k{i}", "office": "12 Main Street"} for i in range(3)]
        self.assertNotIn("main", settings.units_from_dataset(rows, "keyword"))


class TestColumnUnits(unittest.TestCase):
    def test_bare_cells_take_the_measure_of_their_column(self):
        row = {"keyword": "a", "rent_usd": "1450", "deposit_months": "3", "commute_minutes": "34"}
        out = facts("About $34 a month, a deposit of 1,450 months, the commute is 3 minutes.", row)
        self.assertEqual(critical(out), {"34", "1450", "3"})
        self.assertEqual(facts("About $1,450 a month, a deposit of 3 months, the commute is "
                               "34 minutes.", row), {})

    def test_a_price_per_period_column_is_not_a_term(self):
        for column in ("price_per_month", "rent_monthly", "rent"):
            self.assertEqual(content._column_unit(column), "")
            self.assertEqual(facts("Rent is $1,450.", {"keyword": "a", column: "1450"}), {})
        self.assertEqual(content._column_unit("deposit_months"), "months")
        self.assertEqual(content._column_unit("rent_usd"), "$")

    def test_column_terms_become_fact_units(self):
        rows = [{"keyword": f"k{i}", "deposit_months": str(i + 1)} for i in range(3)]
        self.assertIn("months", settings.units_from_dataset(rows, "keyword"))

    def test_a_product_with_a_bare_price_is_a_hint(self):
        for column in ("rent_usd", "rent_monthly", "rent"):
            row = {"keyword": "a", column: "1450", "deposit_months": "3"}
            out = facts("Rent is $1,450 a month and the deposit is 3 months, so you pay $4,350.", row)
            self.assertEqual(critical(out), set(), column)
            self.assertEqual(by_eye(out), {"4350"}, column)


class TestDerivations(unittest.TestCase):
    def test_a_cash_discount_is_not_a_percent(self):
        self.assertEqual(content._row_kinds({"price": "$1,450", "discount": "$15"}),
                         {"1450": "money", "15": "money"})
        self.assertEqual(content._row_kinds({"price": "$1,450", "discount": "15"})["15"], "%")
        out = facts("With the $15 discount you pay $1,232.50.", {"keyword": "a", "price": "$1,450",
                                                                "discount": "$15"})
        self.assertEqual(critical(out), {"1232.5"})

    def test_price_times_price_is_not_a_total(self):
        out = facts("Price $1,450 plus a $250 fee; total $362,500.",
                    {"keyword": "a", "price": "$1,450", "fee": "$250"})
        self.assertEqual(critical(out), {"362500"})

    def test_price_times_term_is_still_a_hint(self):
        out = facts("Three months up front: $4,350.", {"keyword": "a", "rent": "$1,450",
                                                       "deposit": "3 months"})
        self.assertEqual(by_eye(out), {"4350"})


class TestCJK(unittest.TestCase):
    def numbers(self, text, units=None):
        return content._numbers_in(text, content.build_fact_pattern(units) if units else None)

    def test_a_prefix_currency_glued_to_cjk(self):
        self.assertEqual(self.numbers("价格为$450。"), {"450": "$"})
        self.assertEqual(self.numbers("料金は¥9,900。"), {"9900": "¥"})
        self.assertEqual(self.numbers("价格为USD 450。"), {"450": "USD"})
        self.assertEqual(self.numbers("价格为S$450。"), {"450": "S$"})
        self.assertEqual(self.numbers("ABC$450"), {})
        self.assertEqual(critical(facts("价格为$450。", {"keyword": "k", "price": "350"}, lang="zh")),
                         {"450"})

    def test_oku_with_man_is_one_number(self):
        self.assertEqual(self.numbers("物件価格は1億2000万円です。"), {"120000000": "円"})
        self.assertEqual(self.numbers("物件価格は１億２０００万円です。"), {"120000000": "円"})
        self.assertEqual(self.numbers("아파트 가격은 3억 2천만원입니다."), {"320000000": "원"})
        row = {"keyword": "k", "price": "120000000"}
        self.assertEqual(facts("物件価格は1億2000万円です。", row, lang="ja"), {})
        self.assertEqual(critical(facts("物件価格は1億5000万円です。", row, lang="ja")), {"150000000"})

    def test_senman_is_ten_million(self):
        self.assertEqual(self.numbers("物件価格は8千万円です。"), {"80000000": "千万円"})
        row = {"keyword": "k", "price": "50000000"}
        self.assertEqual(facts("物件価格は5千万円です。", row, lang="ja"), {})
        out = facts("物件価格は8千万円です。", row, lang="ja")
        self.assertEqual(critical(out), {"80000000"})
        self.assertIn("8千万円", str(content.check_facts(
            [P("物件価格は8千万円です。", "ja")], {P("").url: row}, [row])[0][3]))

    def test_a_latin_unit_glued_to_cjk(self):
        self.assertEqual(self.numbers("駅から45kmです。", ["km"]), {"45": "km"})
        self.assertEqual(self.numbers("步行45min到达。", ["min"]), {"45": "min"})
        self.assertEqual(self.numbers("料金は99USDです。"), {"99": "USD"})
        self.assertEqual(self.numbers("45 kmh", ["km"]), {})
        self.assertEqual(critical(facts("역에서 45km입니다.", {"keyword": "k", "d": "35 km"},
                                        units=["km"], lang="ko")), {"45"})

    def test_square_metre_sign(self):
        self.assertEqual(self.numbers("部屋の広さは45㎡です。", ["㎡"]), {"45": "m²"})
        row = {"keyword": "k", "area": "35㎡"}
        self.assertEqual(critical(facts("部屋の広さは45㎡です。", row, units=["㎡"], lang="ja")),
                         {"45"})
        self.assertEqual(facts("部屋の広さは35㎡です。", row, units=["㎡"], lang="ja"), {})

    def test_full_width_currency_signs(self):
        self.assertEqual(self.numbers("料金は￥9,900です。"), {"9900": "¥"})
        self.assertEqual(self.numbers("料金は＄99です。"), {"99": "$"})
        row = {"keyword": "k", "price": "3500"}
        self.assertEqual(facts("料金は￥3,500です。", row, lang="ja"), {})
        self.assertEqual(critical(facts("料金は￥9,900です。", row, lang="ja")), {"9900"})

    def test_cjk_dates_are_not_quantities(self):
        row = {"keyword": "k", "price": "3500"}
        for text, lang in (("2026年11月18日に更新。料金は3500円です。", "ja"),
                           ("2026년 11월 18일 업데이트. 가격은 3500원입니다.", "ko"),
                           ("2026年11月18日更新。价格为3500元。", "zh")):
            self.assertEqual(facts(text, row, lang=lang), {}, text)
        self.assertEqual(content._generic_numbers_in("滞在は5日です"), {"5": "日です"})


class TestCheckEndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_a_glued_price_on_a_chinese_page(self):
        from indexgap.cli import main
        site = os.path.join(self.dir, "site", "a")
        os.makedirs(site)
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as fh:
            fh.write('<html lang="zh"><head><title>page title long enough</title></head>'
                     '<body><h1>h</h1><p>价格为$450。</p></body></html>')
        data = os.path.join(self.dir, "data.csv")
        with open(data, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["keyword", "slug", "price"])
            writer.writerow(["k", "a", "350"])
        out = os.path.join(self.dir, "r.json")
        import contextlib
        import io
        import json
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(["check", os.path.join(self.dir, "site"), "--site", "https://example.com",
                      "--dataset", data, "--out", out])
            except SystemExit:
                pass
        with open(out, encoding="utf-8") as fh:
            codes = [i["code"] for i in json.load(fh)["issues"]]
        self.assertIn("unsupported-number", codes)


if __name__ == "__main__":
    unittest.main()
