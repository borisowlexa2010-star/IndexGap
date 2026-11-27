# -*- coding: utf-8 -*-
"""
1.29 (g01): сверка цен и единиц.

* множители цены «$2.54M», «£2.6m», «₹2.5 Cr», «₹25.2 L», «R$ 2,67 mi»;
* голое число строки не прощает «$4.5M» и «$3k», если в строке есть цена;
* то же число в другой валюте — «€1,296» при `$1,296`;
* «1.540,– €» и другие цены с прочерком вместо копеек;
* знаки и коды валют, которых не было: ฿, ₦, ₵, ﷼, kr, Dhs, KSh, CZK, HUF…;
* `fact-drift` по SEK, NOK, лей, кронам, реалам, фунтам словом;
* центы верхним индексом «$19<sup>99</sup>»;
* `Free` в строке — это $0;
* CJK-ячейки «押金3个月», «徒歩5分»;
* перестановка км, м² и кг;
* формы единицы: месяца/месяцев/месяц, Monate/Monat, meses/mes, ヶ月/か月;
* «of 10 weeks» больше не пропадает из «просмотри глазами»;
* «9-day», «5-bed», «wks», «kgs», «sqm», «kilometres»;
* единица в названии колонки `deposit_months`;
* порядковые «4th» — не единица.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import content, core, facts, settings

SITE = "https://demo.example"


def page(text, lang="en"):
    return type("P", (), {"url": SITE + "/p/alpha/", "lang": lang, "title": "",
                          "description": "", "text": text})()


def found(text, row, others=(), units=None, lang="en"):
    """{уровень: множество чисел} по странице строки `row`."""
    rows = [row] + list(others)
    if units is None:
        units = settings.units_from_dataset(rows, "keyword")
    p = page(text, lang)
    out = {}
    for level, _, _, said in content.check_facts([p], {p.url: row}, rows, fact_units=units):
        out.setdefault(level, set()).update(said.subject if hasattr(said, "subject") else said)
    return out


def critical(text, row, **kw):
    return found(text, row, **kw).get("critical", set())


def by_eye(text, row, **kw):
    return found(text, row, **kw).get("info", set())


class TestPriceScales(unittest.TestCase):
    def test_scale_letters_after_a_currency(self):
        for text, price in (("Homes from $2.54M.", "2540000"), ("Homes from $2.55MM.", "2550000"),
                            ("Homes from $2.56 mn.", "2560000"), ("Homes from $2.57m.", "2570000"),
                            ("Valued at $2.58B.", "2580000000"), ("Homes from £2.6m.", "2600000"),
                            ("Flats from ₹2.5 Cr.", "25000000"), ("Flats from ₹25.2 L.", "2520000"),
                            ("Casas desde R$ 2,67 mi.", "2670000"),
                            ("Homes from 2.68M USD.", "2680000"), ("Homes from USD 2.69M.", "2690000")):
            with self.subTest(text=text):
                row = {"keyword": "alpha", "price": price}
                self.assertEqual(found(text, row, units=[]), {})
                self.assertTrue(critical(text, {"keyword": "alpha", "price": "1"}, units=[]))

    def test_the_row_side_reads_them_too(self):
        row = {"keyword": "alpha", "price": "$2.54M"}
        self.assertEqual(found("Homes sell for $2,540,000.", row, units=[]), {})
        row = {"keyword": "alpha", "price": "₹2.5 Cr"}
        self.assertEqual(found("Homes sell for ₹2,50,00,000.", row, units=[]), {})

    def test_a_scale_letter_without_a_currency_is_not_a_million(self):
        self.assertEqual(content._numbers_in("Rooms from $50 B&B a night.", None), {"50": "$"})
        self.assertEqual(content._numbers_in("Flat 4 B €950 per month.", None), {"950": "€"})
        self.assertEqual(content._column_scale("area_m"), 1)

    def test_the_message_shows_the_price_as_written(self):
        self.assertEqual(content._shown("3540000", "$ M"), "$3.54M")
        self.assertEqual(content._shown("2690000", "USD M"), "USD 2.69M")


class TestBareNumberDoesNotForgivePrices(unittest.TestCase):
    def test_rating_and_bed_count(self):
        row = {"keyword": "alpha", "price": "$1,200,000", "rating": "4.5", "beds": "3"}
        for text, number in (("Homes sell for $4.5M.", "4500000"), ("Homes sell for $3M.", "3000000"),
                             ("Homes sell for $3k.", "3000")):
            with self.subTest(text=text):
                self.assertEqual(critical(text, row, units=[]), {number})
        self.assertEqual(found("Homes sell for $1.2M.", row, units=[]), {})

    def test_a_bare_price_column_still_supports(self):
        row = {"keyword": "alpha", "price": "12.5"}
        self.assertEqual(found("It costs $12.5 million.", row, units=[]), {})


class TestCurrencyMismatch(unittest.TestCase):
    OTHERS = [{"keyword": "beta", "rent": "$2,100", "commute": "29 minutes"},
              {"keyword": "gamma", "rent": "$1,600", "commute": "31 minutes"}]

    def test_another_currency_is_critical(self):
        row = {"keyword": "alpha", "rent": "$1,296", "commute": "28 minutes"}
        self.assertEqual(critical("Rent costs €1,296 a month.", row, others=self.OTHERS), {"1296"})
        self.assertEqual(critical("Rent costs 1,296 ₽ a month.", row, others=self.OTHERS), {"1296"})

    def test_the_same_family_passes(self):
        row = {"keyword": "alpha", "rent": "$1,296", "commute": "28 minutes"}
        for text in ("Rent costs $1,296.", "Rent costs USD 1,296.", "Rent costs S$1,296.",
                     "Rent costs 1,296 dollars.", "Rent costs 1,296 pesos."):
            with self.subTest(text=text):
                self.assertEqual(found(text, row, others=self.OTHERS), {})
        row = {"keyword": "alpha", "rent": "1296 kr", "commute": "28 minutes"}
        self.assertEqual(found("Hyra 1296 SEK.", row, others=self.OTHERS), {})
        row = {"keyword": "alpha", "rent": "1296", "commute": "28 minutes"}
        self.assertEqual(found("Rent costs €1,296.", row, others=self.OTHERS), {})


class TestPriceNotations(unittest.TestCase):
    ROW = {"keyword": "alpha", "rent": "1450"}

    def test_dash_instead_of_cents(self):
        for text in ("Miete 1.540,- € im Monat.", "Miete 1.540,– € im Monat.",
                     "Miete 1540,-- € pro Monat.", "Miete 1540.-€ pro Monat.",
                     "Miete 1.540.– CHF pro Monat."):
            with self.subTest(text=text):
                self.assertEqual(critical(text, self.ROW, units=[]), {"1540"})
        self.assertEqual(found("Miete 1.450,– € im Monat.", self.ROW, units=[]), {})

    def test_more_signs_and_codes(self):
        for text in ("Rent from ฿1,540.", "Rent from ₵1,540.", "Rent from ﷼1,540.",
                     "Rent ₦1,540 per month.", "Rent kr 1540 per month.", "Rent 1540 kr. per month.",
                     "Rent Dhs 1,540 per month.", "Rent KSh 1,540 per month.",
                     "Rent EGP 1540 per month.", "Rent 1540 CZK per month.",
                     "Rent 1540 HUF per month.", "Rent 1540 RON per month.",
                     "Rent 1540 NIS per month.", "Rent 1540 лв. per month.",
                     "Rent 1540 ر.س per month.", "Miete SFr. 1540 pro Monat."):
            with self.subTest(text=text):
                self.assertEqual(critical(text, self.ROW, units=[]), {"1540"})

    def test_words_that_look_like_codes(self):
        self.assertEqual(content._numbers_in("Mix 2 ron con cola.", None), {})
        self.assertEqual(content._measure("hours"), "hour")
        self.assertEqual(content._measure("rms"), "")

    def test_free_supports_zero(self):
        row = {"keyword": "alpha", "price": "Free"}
        self.assertEqual(found("Entry is $0.", row, units=[]), {})
        self.assertEqual(critical("Entry costs $25.", row, units=[]), {"25"})


class TestSuperscriptCents(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def text(self, body):
        path = os.path.join(self.root, "index.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write("<!doctype html><html lang='en'><head><title>T</title></head>"
                    "<body><main><p>" + body + "</p></main></body></html>")
        return core.load_page(path, self.root, SITE).text

    def test_two_digits_are_cents(self):
        self.assertIn("$19.99", self.text("Only $19<sup>99</sup> a month."))
        self.assertIn("$1,407.00", self.text("Rent $1,407<sup>00</sup> a month."))

    def test_other_superscripts_are_kept(self):
        self.assertIn("45 m2", self.text("45 m<sup>2</sup>"))
        self.assertIn("1st", self.text("the 1<sup>st</sup> floor"))


class TestFactDriftCurrencies(unittest.TestCase):
    def test_kinds(self):
        for unit, kind in (("SEK", "SEK"), ("NOK", "NOK"), ("QAR", "QAR"), ("NZD", "NZD"),
                           ("reais", "BRL"), ("фунтов", "GBP"), ("lei", "RON"), ("Kč", "CZK"),
                           ('ש"ח', "ILS"), ("сум", "UZS"), ("₵", "GHS"), ("CZK", "CZK")):
            with self.subTest(unit=unit):
                self.assertEqual(facts._kind(unit), kind)


class TestCjkCells(unittest.TestCase):
    ROWS = [{"keyword": "alpha", "deposit": "押金3个月", "commute": "步行5分钟", "rent": "月租4500元"},
            {"keyword": "beta", "deposit": "押金2个月", "commute": "步行8分钟", "rent": "月租3800元"},
            {"keyword": "gamma", "deposit": "押金1个月", "commute": "步行12分钟", "rent": "月租5200元"}]

    def test_a_word_before_the_number(self):
        row = self.ROWS[0]
        self.assertEqual(found("押金3个月，步行5分钟，月租4500元。", row, others=self.ROWS[1:],
                               lang="zh"), {})
        self.assertEqual(critical("押金6个月，步行5分钟，月租4900元。", row, others=self.ROWS[1:],
                                  lang="zh"), {"6", "4900"})

    def test_a_latin_article_code_is_still_dropped(self):
        self.assertEqual(content._numbers_of("A90"), [])
        self.assertEqual(content._numbers_of("徒歩5分"), ["5"])


class TestMeasures(unittest.TestCase):
    ROWS = [{"keyword": "alpha", "distance": "12 km", "area": "45 m²", "weight": "20 kg",
             "commute": "34 minutes"},
            {"keyword": "beta", "distance": "8 km", "area": "60 m²", "weight": "25 kg",
             "commute": "22 minutes"},
            {"keyword": "gamma", "distance": "15 km", "area": "52 m²", "weight": "30 kg",
             "commute": "27 minutes"}]

    def test_swapped_columns(self):
        self.assertEqual(critical("It is 34 km away, 12 m², limit 45 kg, commute 20 minutes.",
                                  self.ROWS[0], others=self.ROWS[1:]), {"34", "12", "45", "20"})
        self.assertEqual(found("It is 12 km away, 45 m², limit 20 kg, commute 34 minutes.",
                               self.ROWS[0], others=self.ROWS[1:]), {})

    def test_long_and_short_spellings(self):
        rows = [dict(r, commute=r["commute"].replace("minutes", "min")) for r in self.ROWS]
        self.assertEqual(found("It is 12 kilometres away, 45 square metres, a 20-kg limit, "
                               "commute 34 minutes.", rows[0], others=rows[1:]), {})
        self.assertEqual(critical("It is 19 kilometres away, 61 m2, limit 26 kgs, 53 sqm.",
                                  rows[0], others=rows[1:]), {"19", "61", "26", "53"})


class TestUnitForms(unittest.TestCase):
    def check(self, rows, text, lang, expected):
        self.assertEqual(critical(text, rows[0], others=rows[1:], lang=lang), expected)

    def test_russian(self):
        rows = [{"keyword": "alpha", "deposit": "3 месяца", "commute": "34 минуты"},
                {"keyword": "beta", "deposit": "2 месяца", "commute": "22 минуты"},
                {"keyword": "gamma", "deposit": "4 месяца", "commute": "23 минуты"}]
        self.check(rows, "Залог 5 месяцев, дорога 25 минут.", "ru", {"5", "25"})
        self.check(rows, "Залог 1 месяц, дорога 21 минуту.", "ru", {"1", "21"})
        self.check(rows, "Залог 3 месяца, дорога 34 минуты.", "ru", set())

    def test_german_and_spanish(self):
        rows = [{"keyword": "alpha", "deposit": "3 Monate", "commute": "34 Minuten"},
                {"keyword": "beta", "deposit": "2 Monate", "commute": "22 Minuten"}]
        self.check(rows, "Kaution 1 Monat, Fahrt 1 Minute.", "de", {"1"})
        rows = [{"keyword": "alpha", "deposit": "3 meses", "commute": "34 minutos"},
                {"keyword": "beta", "deposit": "2 meses", "commute": "22 minutos"}]
        self.check(rows, "Depósito de 1 mes.", "es", {"1"})

    def test_japanese_month_spellings(self):
        rows = [{"keyword": "alpha", "deposit": "3ヶ月", "commute": "34分"},
                {"keyword": "beta", "deposit": "2ヶ月", "commute": "22分"}]
        self.check(rows, "敷金は5か月分、通勤は34分です。", "ja", {"5"})
        self.check(rows, "敷金は6カ月です。", "ja", {"6"})
        self.assertIn("ヶ月", content._unit_forms(["ヶ月分"]))

    def test_short_plurals_and_hyphens(self):
        rows = [{"keyword": "alpha", "wait": "3 days", "size": "2 beds"},
                {"keyword": "beta", "wait": "4 days", "size": "3 beds"}]
        self.check(rows, "Expect a 9-day wait in a 5-bed house.", "en", {"9", "5"})
        rows = [{"keyword": "alpha", "wait": "3 weeks"}, {"keyword": "beta", "wait": "4 weeks"}]
        self.check(rows, "Expect 9 wks or a 7-wk wait.", "en", {"9", "7"})

    def test_russian_spelled_numbers_in_another_case(self):
        rows = [{"keyword": "alpha", "warranty": "6 месяцев"},
                {"keyword": "beta", "warranty": "9 месяцев"}]
        self.assertEqual(by_eye("Гарантия — два месяца.", rows[0], others=rows[1:], lang="ru"),
                         {"2"})


class TestScaleTop(unittest.TestCase):
    ROWS = [{"keyword": "alpha", "commute": "34 minutes", "rent": "$1450"},
            {"keyword": "beta", "commute": "22 minutes", "rent": "$1600"}]

    def test_of_without_a_rating_keeps_the_number(self):
        self.assertEqual(by_eye("Rent $1450, commute 34 minutes, a deposit of 10 weeks.",
                                self.ROWS[0], others=self.ROWS[1:]), {"10"})

    def test_a_rating_top_is_still_dropped(self):
        for text in ("Rated 4.6 out of 5 by guests.", "Rated 4.6/5 by guests.",
                     "Rated 4,6 из 5 by guests."):
            with self.subTest(text=text):
                self.assertEqual(found(text, self.ROWS[0], others=self.ROWS[1:]), {})


class TestColumnUnits(unittest.TestCase):
    ROWS = [{"keyword": "alpha", "rent_usd": "1450", "deposit_months": "3", "commute_minutes": "34"},
            {"keyword": "beta", "rent_usd": "2100", "deposit_months": "2", "commute_minutes": "29"},
            {"keyword": "gamma", "rent_usd": "1600", "deposit_months": "4", "commute_minutes": "31"}]

    def test_units_from_column_names(self):
        self.assertEqual(set(settings.units_from_dataset(self.ROWS, "keyword")),
                         {"months", "minutes"})
        self.assertEqual(content.column_unit("price_per_month"), "")
        self.assertEqual(content.column_unit("deposit_months"), "months")

    def test_invented_and_swapped_terms(self):
        row, others = self.ROWS[0], self.ROWS[1:]
        self.assertEqual(critical("Deposit 5 months, commute 44 minutes.", row, others=others),
                         {"5", "44"})
        self.assertEqual(critical("Rent $1450, deposit 34 months, commute 3 minutes.", row,
                                  others=others), {"34", "3"})
        self.assertEqual(found("Rent $1450, deposit 3 months, commute 34 minutes.", row,
                               others=others), {})


class TestOrdinals(unittest.TestCase):
    def test_ordinals_are_not_units(self):
        rows = [{"keyword": "alpha", "floor": "4th", "rent": "$1450"},
                {"keyword": "beta", "floor": "5th", "rent": "$1600"},
                {"keyword": "gamma", "floor": "6th", "rent": "$900"}]
        self.assertNotIn("th", settings.units_from_dataset(rows, "keyword"))
        self.assertEqual(found("The 4th floor of a 19th-century building, viewings until the "
                               "20th. Rent $1450.", rows[0], others=rows[1:]), {})


if __name__ == "__main__":
    unittest.main()
