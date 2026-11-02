# -*- coding: utf-8 -*-
"""
Одни и те же проверки на разных языках, письменностях и записях чисел.

Конвейер генерирует страницы на десятках языков, и проверка, выверенная на
русском и английском, ломается на остальных тихо: `₹12,34,567` читалось как
12,34, `٩٥٪` не считалось процентом, `9.900 €` и `5万元` уходили «на проверку
глазами» вместо критичной находки. Каждый случай здесь — страница и строка
данных через настоящий `check`, как у пользователя.
"""

import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, cli, content, core

# (название, lang, dir, текст страницы, значение в данных, должна ли быть
# критичная находка unsupported-number)
NUMBERS = [
    ("en 1,234.50", "en", "ltr", "The price is $1,234.50 per month for this plan.", "1234.50", False),
    ("de 1.234,50", "de", "ltr", "Der Preis beträgt 1.234,50 € pro Monat für diesen Tarif.", "1234.5", False),
    ("fr nbsp", "fr", "ltr", "Le prix est de 1 234,50 € par mois pour cette offre.", "1234.5", False),
    ("fr narrow nbsp", "fr", "ltr", "Le prix est de 1 234,50 € par mois pour cette offre.", "1234.5", False),
    ("ch apostrophe", "de", "ltr", "Der Preis beträgt CHF 1'234.50 pro Monat für diesen Tarif.", "1234.5", False),
    ("ch typographic apostrophe", "de", "ltr", "Der Preis beträgt CHF 1’234.50 pro Monat.", "1234.5", False),
    ("in lakh", "en", "ltr", "The price is ₹12,34,567 for this apartment in Pune.", "1234567", False),
    ("in lakh invented", "en", "ltr", "The price is ₹12,34,567 for this apartment in Pune.", "999000", True),
    ("in lakh word", "en", "ltr", "The flat costs ₹12 lakh in this part of Pune.", "1200000", False),
    ("ar digits", "ar", "rtl", "السعر هو ٣٥٠٠ دولار شهريا لهذه الخطة.", "3500", False),
    ("ar separators", "ar", "rtl", "السعر هو ١٬٢٣٤٫٥٠ دولار شهريا لهذه الخطة.", "1234.5", False),
    ("ar invented", "ar", "rtl", "السعر هو ٩٩٠٠ دولار شهريا لهذه الخطة.", "3500", True),
    ("ar percent", "ar", "rtl", "نسبة الموافقة على التأشيرة ٨٥٪ هذا العام.", "85", False),
    ("ar percent invented", "ar", "rtl", "نسبة الموافقة على التأشيرة ٩٥٪ هذا العام.", "85", True),
    ("fa digits", "fa", "rtl", "قیمت ۳۵۰۰ دلار در ماه برای این طرح است.", "3500", False),
    ("he invented", "he", "rtl", "המחיר הוא 9,900 ₪ לחודש עבור תוכנית זו.", "3500", True),
    ("hi digits", "hi", "ltr", "इस योजना की कीमत ३५०० रुपये प्रति माह है।", "3500", False),
    ("th digits", "th", "ltr", "ราคาของแผนนี้คือ ๓๕๐๐ บาทต่อเดือน", "3500", False),
    ("ja fullwidth", "ja", "ltr", "このプランの料金は月額３５００円です。", "3500", False),
    ("ja fullwidth percent", "ja", "ltr", "ビザの承認率は８５％です。", "85", False),
    ("ja fullwidth percent invented", "ja", "ltr", "ビザの承認率は９５％です。", "85", True),
    ("ja man", "ja", "ltr", "このプランの料金は月額3万円です。", "30000", False),
    ("zh man invented", "zh", "ltr", "这个套餐的价格是每月5万元。", "30000", True),
    ("zh oku", "zh", "ltr", "该公司去年的收入为2億元人民币。", "200000000", False),
    ("ko man", "ko", "ltr", "이 요금제의 가격은 월 3만원입니다.", "30000", False),
    ("ru 1 500 руб", "ru", "ltr", "Стоимость оформления составляет 1 500 руб. за месяц.", "1500", False),
    ("ru млн", "ru", "ltr", "Квартира стоит 12,5 млн руб. в этом районе.", "12500000", False),
    ("ru млн in data as is", "ru", "ltr", "Квартира стоит 12,5 млн руб. в этом районе.", "12.5", False),
    ("ru млн invented", "ru", "ltr", "Квартира стоит 19 млн руб. в этом районе.", "12500000", True),
    ("es invented", "es", "ltr", "El precio es de 9.900 € al mes para este plan.", "3500", True),
    ("en million", "en", "ltr", "The fund raised $2.5 million last year.", "2500000", False),
]

# (lang, alt, ожидаемые коды)
ALTS = [
    ("ru", "фото квартиры в Москве у метро", []),
    ("ru", "image", ["img-alt-filler"]),
    ("ru", "Фото", ["img-alt-filler"]),
    ("ar", "صورة", ["img-alt-filler"]),
    ("ja", "画像1", ["img-alt-filler"]),
    ("ko", "이미지", ["img-alt-filler"]),
    ("he", "תמונה", ["img-alt-filler"]),
    ("de", "Bild 3", ["img-alt-filler"]),
    ("en", "IMG_2034.jpg", ["img-alt-filler"]),
    ("en", "DSC00123", ["img-alt-filler"]),
    ("en", "photo-1.webp", ["img-alt-filler"]),
    ("en", "Apartment in Berlin near the station", []),
    ("en", "2024 Toyota Camry hybrid front view", []),
    ("en", "iPhone 15 Pro 256GB", []),
    ("de", "Wohnung in Berlin am Bahnhof", []),
    ("zh", "北京地铁站附近的公寓", []),
    ("hi", "मुंबई में मेट्रो स्टेशन के पास अपार्टमेंट", []),
    ("ru", "Apartment in Moscow near the metro station", ["img-alt-language"]),
    ("ar", "Apartment in Dubai near the metro station", ["img-alt-language"]),
    ("ja", "Apartment in Tokyo near the station", ["img-alt-language"]),
    ("el", "Apartment in Athens near the metro station", ["img-alt-language"]),
]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class TestNumbersEverywhere(unittest.TestCase):
    def findings(self, lang, direction, text, value):
        root = tempfile.mkdtemp(prefix="indexgap-lang-")
        self.addCleanup(shutil.rmtree, root, True)
        site = os.path.join(root, "site")
        write(os.path.join(site, "a", "index.html"),
              f'<html lang="{lang}" dir="{direction}"><head><title>page title long enough</title>'
              f'<meta name="keyword" content="k"></head><body><h1>h</h1><p>{text}</p></body></html>')
        dataset = os.path.join(root, "data.csv")
        with open(dataset, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["keyword", "slug", "price"])
            writer.writerow(["k", "a", value])
        out = os.path.join(root, "r.json")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["check", site, "--site", "https://e.com", "--dataset", dataset, "--out", out])
        with open(out, encoding="utf-8") as fh:
            return [i for i in json.load(fh)["issues"] if i["code"] == "unsupported-number"]

    def test_every_case(self):
        for name, lang, direction, text, value, invented in NUMBERS:
            with self.subTest(name):
                found = self.findings(lang, direction, text, value)
                self.assertEqual(bool(found), invented, f"{name}: {found}")

    def test_the_finding_shows_the_number_as_written(self):
        """«5万元», а не «50000 万元», которое читается как пятьсот миллионов."""
        found = self.findings("zh", "ltr", "这个套餐的价格是每月5万元。", "30000")
        self.assertIn("5万元", found[0]["message"])
        self.assertNotIn("50000", found[0]["message"])


class TestNumberParts(unittest.TestCase):
    def test_grouping_styles(self):
        cases = {"12,34,567": "1234567", "1'234.50": "1234.5", "1,234.50": "1234.5",
                 "1.234,50": "1234.5", "1,5": "1.5", "1,500": "1500",
                 "١٬٢٣٤٫٥٠": "1234.5", "٣٥٠٠": "3500", "３５００": "3500"}
        for raw, expected in cases.items():
            with self.subTest(raw):
                self.assertEqual(content._norm_number(raw), expected)

    def test_scale_words_need_a_word_boundary(self):
        """`mil` в «mile» и `млн` внутри слова — не множитель."""
        self.assertEqual(content._scale_at("5 miles", 1), (1, 0))
        self.assertEqual(content._scale_at("5 mil euros", 1)[0], 1000)
        self.assertEqual(content._scale_at("3万円", 1)[0], 10**4)

    def test_data_with_a_scale_word_supports_both_forms(self):
        numbers = content._row_numbers({"price": "3万円"})
        self.assertTrue({"3", "30000"} <= numbers, numbers)


class TestImagesEverywhere(unittest.TestCase):
    def page(self, lang, body):
        root = tempfile.mkdtemp(prefix="indexgap-alt-")
        self.addCleanup(shutil.rmtree, root, True)
        write(os.path.join(root, "a", "index.html"),
              f'<html lang="{lang}"><body><main><p>текст</p>{body}</main></body></html>')
        pages, _ = core.load_pages(root, "https://e.com")
        return pages[0]

    def test_every_alt(self):
        for lang, alt, expected in ALTS:
            with self.subTest(f"{lang}: {alt}"):
                page = self.page(lang, f'<img src=a.jpg alt="{alt}"><img src=b.jpg alt="{alt}">')
                self.assertEqual(sorted({i[2] for i in aeo.check_alt_text(page)}), expected)

    def test_an_empty_alt_is_decoration_not_a_missing_alt(self):
        page = self.page("en", '<img src=a.jpg alt=""><img src=b.jpg>')
        self.assertEqual((page.blocks["img_no_alt"], page.blocks["img_empty_alt"]), (1, 1))
        codes = [i[2] for i in aeo.check_extractable(page)]
        self.assertEqual(codes.count("img-no-alt"), 1)

    def test_every_image_marked_decorative_is_suspicious(self):
        page = self.page("en", "".join(f'<img src={i}.jpg alt="">' for i in range(4)))
        messages = [i[3] for i in aeo.check_extractable(page) if i[2] == "img-no-alt"]
        self.assertEqual(len(messages), 1)
        self.assertIn('alt=""', messages[0])

    def test_markdown_alts_are_read(self):
        root = tempfile.mkdtemp(prefix="indexgap-md-")
        self.addCleanup(shutil.rmtree, root, True)
        write(os.path.join(root, "a.md"), "---\ntitle: T\nlang: ru\n---\n\nТекст.\n\n"
              "![IMG_2034.jpg](a.jpg)\n\n![](b.png)\n")
        pages, _ = core.load_pages(root, "https://e.com")
        self.assertEqual(pages[0].alts, [("IMG_2034.jpg", "a.jpg")])
        self.assertEqual(pages[0].blocks["img_empty_alt"], 1)
        self.assertEqual([i[2] for i in aeo.check_alt_text(pages[0])], ["img-alt-filler"])


if __name__ == "__main__":
    unittest.main()
