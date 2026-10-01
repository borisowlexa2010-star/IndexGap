# -*- coding: utf-8 -*-
"""
Сравнение страниц между собой: находки ревью десяти агентов.

Проверки, которые видны только на множестве страниц, — то, ради чего пакет
существует. Ревью показало, что каждая из них молча выключалась на обычном
сайте. Доля шаблона считалась по всем страницам сразу, и на сайте с двумя
языками или двумя шаблонами порог «в 90% страниц» не достигался никогда.
Слова на хинди и бенгали разбивались по диакритике, китайский текст был одним
«словом» на фразу. А страница, отличающаяся от соседней только названием
города, проходила все проверки: одно подставленное слово портило пять
соседних пятисловных шинглов.
"""

import shutil
import tempfile
import os
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

SITE = "https://example.com"

TEMPLATE = (
    "Аренда квартиры в городе {city} начинается с поиска на больших площадках. "
    "Утром вы смотрите новые объявления и пишете агенту до полудня. "
    "В городе {city} приглашение на просмотр приходит на одно письмо из десяти. "
    "На просмотр берут папку с документами: справку о доходах, копию паспорта и письмо "
    "от прежнего арендодателя. Владелец выбирает жильца за несколько дней и причин не "
    "объясняет. После подписания договора в городе {city} нужно зарегистрироваться по "
    "адресу в течение двух недель. Электричество оформляют сами, потому что тариф по "
    "умолчанию самый дорогой. Коммунальные платежи считают раз в год, и доплата приходит, "
    "когда о зиме уже забыли. Большинство жильцов покупают страховку ответственности, и "
    "владельцы всё чаще просят показать её до передачи ключей в городе {city}. Залог "
    "лежит на отдельном счёте и возвращается с процентами через несколько месяцев после "
    "выезда. Соседи в городе {city} ждут тишины после десяти вечера и по воскресеньям. ")


MENU = " ".join(f"раздел{i} меню" for i in range(60))
FOOT = " ".join(f"ссылка{i} подвала" for i in range(60))


def html(title, body, lang="ru", main=True):
    inner = f"<h1>{title}</h1><p>{body}</p>"
    wrapped = f"<main>{inner}</main>" if main else f'<div id="content">{inner}</div>'
    return (f'<html lang="{lang}"><head><title>{title} — страница сайта</title></head><body>'
            f"<header>{MENU}</header>{wrapped}<footer>{FOOT}</footer></body></html>")


class Fixture(unittest.TestCase):
    def site(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-cross-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        pages = core.load_pages(root, SITE)[0]
        return pages, checks.run_all(pages, SITE + "/")

    def codes(self, result, code):
        return [i[1].replace(SITE, "") for i in result["issues"] if i[2] == code]


CITIES = ["Берлин", "Мюнхен", "Гамбург", "Кёльн", "Лейпциг", "Дрезден", "Бремен", "Бонн",
          "Эссен", "Ганновер", "Нюрнберг", "Дортмунд"]


class TestSlotVariables(Fixture):
    def test_city_swap_pages_are_near_duplicates(self):
        _, result = self.site({f"rent/{i}/index.html": html(f"Аренда в городе {city}",
                                                            TEMPLATE.format(city=city))
                               for i, city in enumerate(CITIES)})
        self.assertEqual(len(self.codes(result, "near-duplicate")), len(CITIES))

    def test_different_pages_sharing_some_text_are_not(self):
        unique = ["уникальный текст страницы номер {n} про район {n} и его улицы дома "
                  "парки школы магазины и транспорт " * 12]
        _, result = self.site({f"p{n}/index.html": html(
            f"Страница {n}", " ".join(f"слово{n}x{i}" for i in range(220)) + TEMPLATE[:200])
            for n in range(12)})
        self.assertEqual(self.codes(result, "near-duplicate"), [])


class TestCohorts(Fixture):
    def doorway(self, lang, city, n):
        body = TEMPLATE.format(city=city) + f" Особенность района {n}."
        return html(f"Аренда {city} {lang}", body, lang=lang)

    def test_low_uniqueness_survives_a_second_language(self):
        """Два языка — два шаблона. По всем страницам сразу ни одна фраза не
        набирала 90%, и проверка молчала именно там, где шаблонов больше."""
        files = {}
        for i, city in enumerate(CITIES * 2):
            files[f"ru/c{i}/index.html"] = self.doorway("ru", city, i)
        english = TEMPLATE.translate({ord(a): b for a, b in zip(
            "абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeezzijklmnoprstufhccss_y_eua")})
        for i, city in enumerate(CITIES * 2):
            files[f"en/c{i}/index.html"] = html(
                f"Rent {city}", english.format(city=f"city{i}") + f" area {i}.", lang="en")
        _, result = self.site(files)
        self.assertEqual(len(self.codes(result, "low-uniqueness")), len(files))


class TestTokens(unittest.TestCase):
    def words(self, text):
        return core.Page(path="a.html", url=SITE + "/a/", text=text).words

    def test_words_keep_combining_marks(self):
        self.assertEqual(self.words("सिंगापुर का वीज़ा"), ["सिंगापुर", "का", "वीज़ा"])
        self.assertEqual(self.words("সিঙ্গাপুর ভিসা"), ["সিঙ্গাপুর", "ভিসা"])
        self.assertEqual(self.words("تَأْشِيرَة سنغافورة"), ["تَأْشِيرَة", "سنغافورة"])

    def test_cjk_is_counted_by_character(self):
        self.assertEqual(self.words("新加坡签证 Form 14A"), ["新", "加", "坡", "签", "证", "form", "14a"])

    def test_latin_and_cyrillic_are_unchanged(self):
        self.assertEqual(self.words("Виза в Сингапур: 30 days, e-Visa"),
                         ["виза", "в", "сингапур", "30", "days", "e", "visa"])

    def test_content_hash_does_not_move_with_the_tokenizer(self):
        """Иначе обновление пакета поменяло бы `lastmod` у каждой страницы на
        хинди и китайском и отправило бы их в IndexNow заново."""
        import hashlib, re
        for text in ("सिंगापुर का वीज़ा", "新加坡签证 Form 14A", "Виза в Сингапур"):
            page = core.Page(path="a.html", url=SITE + "/a/", text=text, title="T")
            old = "\x00".join(["T", "", " ".join(re.findall(r"\w+", text.lower(), flags=re.UNICODE))])
            self.assertEqual(page.content_hash,
                             hashlib.sha256(old.encode("utf-8")).hexdigest()[:16], text)


class TestCjkTwins(Fixture):
    def test_cjk_twins_are_near_duplicates(self):
        base = "新加坡签证申请需要护照照片和填写完整的表格申请人应当提前准备好所有材料并在网上提交" * 12
        files = {f"zh/{i}/index.html": html(f"签证指南 {i}", base + f"第{i}页", lang="zh")
                 for i in range(4)}
        _, result = self.site(files)
        self.assertEqual(len(self.codes(result, "near-duplicate")), 4)


class TestSharedChrome(Fixture):
    def test_shared_chrome_is_not_a_duplicate_without_main(self):
        """Сайт без <main>: шапка и подвал сравнивались как текст страницы."""
        files = {f"p{n}/index.html": html(
            f"Страница{n}", " ".join(f"слово{n}x{i}" for i in range(60)), main=False)
            for n in range(40)}
        # Одна страница свёрстана иначе: раньше она обнуляла общий префикс.
        files["odd/index.html"] = ("<html><head><title>Другая страница сайта</title></head>"
                                   "<body><p>" + " ".join(f"иное{i}" for i in range(80))
                                   + "</p></body></html>")
        _, result = self.site(files)
        self.assertEqual(self.codes(result, "near-duplicate"), [])
        self.assertEqual(self.codes(result, "low-uniqueness"), [])


class TestSpeed(unittest.TestCase):
    def test_words_are_computed_once(self):
        page = core.Page(path="a.html", url=SITE + "/a/", text="раз два три")
        self.assertIs(page.words, page.words)
        page.text = "четыре пять"
        self.assertEqual(page.words, ["четыре", "пять"])

    def test_minhash_estimates_jaccard(self):
        a = set(range(0, 4000))
        b = set(range(1000, 5000))
        sa, sb = checks._minhash(a, 64), checks._minhash(b, 64)
        estimate = sum(1 for x, y in zip(sa, sb) if x == y) / 64
        self.assertAlmostEqual(estimate, 3000 / 5000, delta=0.2)
        self.assertEqual(checks._minhash(a, 64), checks._minhash(set(a), 64))


if __name__ == "__main__":
    unittest.main()
