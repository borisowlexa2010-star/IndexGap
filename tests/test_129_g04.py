# -*- coding: utf-8 -*-
"""
1.29 (g04): цифры на арабских, персидских, ивритских, индийских, тайских
и индонезийских страницах.

* «يورو», «في المئة», «ש״ח», «฿18,000», «18,000.- บาท» — тоже цены и проценты;
* множители «ألف», «هزار», «लाख», «juta», «ล้าน» умножают число;
* арабская запятая разрядов, персидская дробь через косую черту, ZWNJ у цифры;
* перечисление со слитным «و١٤٩» и «ו-149»;
* знаки гласных не обрезают единицу: «মাস» и «মিনিট» — разные меры;
* год буддийской эры с подписью — год, а не выдумка;
* `fact-drift`: валюта вне словаря сравнивается сама с собой, `Rp` — явная.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import content, core, facts, settings

SITE = "https://demo.example"


class Page:
    def __init__(self, text, lang="en"):
        self.url = SITE + "/p/a/"
        self.lang = lang
        self.title = ""
        self.description = ""
        self.text = text


def levels(text, row, units=(), lang="en"):
    page = Page(text, lang)
    return {level for level, _, code, _ in content.check_facts(
        [page], {page.url: row}, [row], fact_units=list(units))
        if code in ("unsupported-number", "check-by-eye")}


def nums(text, units=None):
    return content._numbers_in(text, content.build_fact_pattern(units) if units else None)


def facts_of(text):
    return facts.facts_of(Page(text))


class TestRtlPrices(unittest.TestCase):
    def test_arabic_euro_and_percent(self):
        self.assertEqual(nums("رسوم ٩٩ يورو"), {"99": "يورو"})
        self.assertEqual(nums("٨٠ في المئة"), {"80": "%"})
        self.assertEqual(facts_of("٤٠٠ يورو"), {"EUR": {"400": "400 يورو"}})

    def test_gershayim_shekel(self):
        self.assertEqual(nums("כ-9,900 ש״ח לחודש"), {"9900": 'ש"ח'})
        self.assertEqual(set(facts_of("350 ש״ח")), {"ILS"})
        self.assertEqual(facts_of("ILS 530"), {"ILS": {"530": "ILS 530"}})

    def test_attached_conjunction_lists(self):
        self.assertEqual(set(nums("بين ٩٢، ٤٥ و١٬٣٠٠ دولار")), {"92", "45", "1300"})
        self.assertEqual(set(nums("92, 49 ו-149 דולר")), {"92", "49", "149"})

    def test_rtl_scale_words(self):
        self.assertEqual(nums("٣ ملايين دولار"), {"3000000": "ملايين دولار"})
        self.assertEqual(set(nums("۹۹ هزار تومان")), {"99000"})
        self.assertEqual(levels("۳۰ هزار تومان", {"keyword": "a", "rent": "30000 تومان"}),
                         set())
        self.assertEqual(levels("٩ آلاف دولار", {"keyword": "a", "rent": "$2,100"}),
                         {"critical"})

    def test_arabic_comma_thousands(self):
        self.assertEqual(nums("حوالي ١،٦٠٠ دولار"), {"1600": "دولار"})
        self.assertEqual(levels("حوالي ١،٦٠٠ دولار شهريًا", {"keyword": "a", "rent": "$1,600"}),
                         set())
        # Год без пробела после запятой — не разряды.
        self.assertNotIn("2026150", nums("٢٠٢٦،١٥٠ دولار"))

    def test_persian_slash_decimal(self):
        self.assertEqual(nums("نرخ ۳/۵ درصد"), {"3.5": "%"})
        self.assertEqual(levels("نرخ ۳/۵ درصد", {"keyword": "a", "rate": "3.5%"}), set())
        # Дата — не дробь.
        self.assertNotIn("1403.05", content._same_signs("۱۴۰۳/۰۵/۱۲"))

    def test_invisible_marks_at_digits(self):
        self.assertEqual(nums("۹۹‌٪"), {"99": "%"})
        self.assertEqual(nums("٣٥⁠دولار"), {"35": "دولار"})
        self.assertEqual(nums("١​٤٥٠ دولار"), {"1450": "دولار"})
        # ZWNJ внутри персидского слова остаётся.
        self.assertIn("‌", content._same_signs("می‌شود"))


class TestIndicThaiIndonesian(unittest.TestCase):
    def test_scale_words(self):
        self.assertEqual(set(nums("₹15 लाख")), {"1500000"})
        self.assertEqual(set(nums("Rp 8,5 juta")), {"8500000"})
        self.assertEqual(set(nums("15 ล้านบาทต่อเดือน")), {"15000000"})
        self.assertEqual(set(nums("๑.๒ หมื่นบาท")), {"12000"})
        self.assertEqual(levels("किराया ₹15 करोड़", {"keyword": "a", "rent": "₹15 लाख"}, lang="hi"),
                         {"critical"})
        self.assertEqual(levels("Sewa Rp 15 miliar", {"keyword": "a", "rent": "Rp 15 juta"},
                                lang="id"), {"critical"})
        self.assertEqual(levels("ราคา 15 ล้านบาท", {"keyword": "a", "price": "15 พันบาท"},
                                lang="th"), {"critical"})

    def test_correct_scaled_prices_are_quiet(self):
        self.assertEqual(levels("Sewa Rp 8,5 juta", {"keyword": "a", "rent": "Rp 8.500.000"},
                                units=["juta"], lang="id"), set())
        self.assertEqual(levels("किराया ₹1.5 लाख", {"keyword": "a", "rent": "₹1,50,000"},
                                units=["लाख"], lang="hi"), set())
        self.assertEqual(levels("ค่าเช่า 1.5 แสนบาทต่อปี", {"keyword": "a", "rent": "150,000 บาท"},
                                lang="th"), set())

    def test_baht_sign_before_the_number(self):
        self.assertEqual(nums("Rent ฿18,000 per month"), {"18000": "฿"})
        self.assertEqual(levels("A condo costs ฿95,000 a month", {"keyword": "a", "rent": "฿15,000"}),
                         {"critical"})

    def test_dash_after_the_price(self):
        self.assertEqual(nums("ค่าเช่า 18,000.- บาท"), {"18000": "บาท"})
        self.assertEqual(nums("शुल्क 2,50,000/- रुपये"), {"250000": "रुपये"})

    def test_units_keep_vowel_signs(self):
        rows = [{"keyword": k, "deposit": d, "commute": c}
                for k, d, c in (("a", "৩ মাস", "৩৪ মিনিট"), ("b", "২ মাস", "২৯ মিনিট"))]
        self.assertEqual(sorted(settings.units_from_dataset(rows, "keyword")), ["মাস", "মিনিট"])
        units = settings.units_from_dataset(rows, "keyword")
        self.assertEqual(levels("জামানত ৩৪ মাস, যাতায়াত ৩ মিনিট।", rows[0], units, "bn"),
                         {"critical"})
        self.assertEqual(levels("জামানত ৩ মাস, যাতায়াত ৩৪ মিনিট।", rows[0], units, "bn"), set())

    def test_counting_words_are_not_facts(self):
        self.assertEqual(levels("किराया ₹15000 है। आवेदन 3 चरण में और 2 बार में होता है। 5 तरीके हैं।",
                                {"keyword": "a", "rent": "₹15000"}, lang="hi"), set())
        self.assertEqual(levels("ভাড়া ১৫০০০ টাকা। আবেদন ৩ ধাপ এবং ২ বার। ৪ উপায়",
                                {"keyword": "a", "rent": "15000 টাকা"}, lang="bn"), set())

    def test_buddhist_era_year(self):
        row = {"keyword": "a", "commute": "15-20 นาที"}
        self.assertEqual(levels("ในปี 2569, 15 หรือ 20 นาที โดยรถไฟ", row, ["นาที"], "th"), set())
        self.assertEqual(levels("ค่าธรรมเนียม 1,450 บาท ข้อมูลปี 2569 ล่าสุด",
                                {"keyword": "a", "fee": "1,450 บาท"}, lang="th"), set())
        self.assertEqual(levels("ค่าธรรมเนียม ฿1,450 ปี ๒๕๖๙", {"keyword": "a", "fee": "฿1,450"},
                                lang="th"), set())
        # Без подписи эры 2569 — не год.
        self.assertEqual(levels("ใน 2569, 15 หรือ 20 นาที", row, ["นาที"], "th"), {"critical"})


class TestDriftCurrencies(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-129g04-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def cluster(self, slug, texts):
        for lang, body in texts.items():
            alts = "".join(f'<link rel="alternate" hreflang="{other}" href="{SITE}/{other}/{slug}/">'
                           for other in texts)
            folder = os.path.join(self.root, lang, slug)
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
                         f'<title>Fees {slug}</title><link rel="canonical" href="{SITE}/{lang}/{slug}/">'
                         f'{alts}</head><body><main><h1>Fees</h1><p>{body}</p></main></body></html>')

    def drift(self):
        pages, _ = core.load_pages(self.root, SITE)
        return sorted(i[1].replace(SITE, "") for i in facts.drift(pages))

    def test_unknown_currency_is_compared_with_itself(self):
        self.cluster("a", {"ar": "رسوم ٥٠٠ جنيه وضريبة ٢٠ ﷼", "fa": "هزینه ۸۰۰ جنيه و ۲۰ ﷼"})
        self.cluster("b", {"ar": "رسوم ٥٠٠ جنيه", "fa": "هزینه ۵۰۰ جنيه"})
        # Оригинал без x-default и английского — самая богатая фактами версия.
        self.assertEqual([p.split("/")[2] for p in self.drift()], ["a"])

    def test_scale_words_and_rupee_forms(self):
        self.cluster("lakh", {"en": "The fee is ₹15 lakh.", "hi": "शुल्क ₹15 लाख है।"})
        self.cluster("tax", {"en": "The tax is ₹1,500 per year.", "hi": "कर 1,800 रुपए प्रति वर्ष है।"})
        self.assertEqual(self.drift(), ["/hi/tax/"])

    def test_rupiah_is_not_a_conversion(self):
        self.cluster("visa", {"en": "The visa fee is Rp 150,000.", "id": "Biaya visa Rp 500.000."})
        self.cluster("ok", {"en": "The visa fee is Rp 150,000.", "id": "Biaya visa Rp 150.000."})
        self.assertEqual(self.drift(), ["/id/visa/"])

    def test_arabic_euro_and_shekel(self):
        self.cluster("eu", {"en": "The fee is €40.", "ar": "الرسوم ٤٠٠ يورو."})
        self.cluster("il", {"en": "The fee is ILS 530.", "he": "האגרה 350 ש״ח."})
        self.cluster("same", {"en": "The fee is €40 or ILS 530.", "he": "האגרה 40 יורו או 530 ש״ח."})
        self.assertEqual(self.drift(), ["/ar/eu/", "/he/il/"])


if __name__ == "__main__":
    unittest.main()
