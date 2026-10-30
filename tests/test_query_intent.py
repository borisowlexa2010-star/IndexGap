# -*- coding: utf-8 -*-
"""
Намерение запроса в `plan`: какие страницы продают, а какие объясняют.

Из списка в 232 приёма — «найди запросы с намерением купить и начни с них».
`plan` и так разбирает ключи до генерации; теперь он ещё и помечает, какие из
них коммерческие, чтобы первыми генерировать страницы, которые приводят
клиентов. Правила простые и названы прямо: это подсказка, а не вердикт.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, generate


class Intent(unittest.TestCase):
    def test_labels(self):
        cases = {
            "buy plumbing tools": "transactional",
            "plumber price austin": "transactional",
            "emergency plumber near me": "transactional",
            "купить визу в сингапур": "transactional",
            "аренда экскаватора цена": "transactional",
            "best plumbers in austin": "commercial",
            "pex vs copper pipes": "commercial",
            "лучшие сантехники москвы": "commercial",
            "отзывы о сервисе виз": "commercial",
            "how to fix a leaking tap": "informational",
            "что такое виза по прибытии": "informational",
            "plumbing austin": "",
        }
        for keyword, expected in cases.items():
            with self.subTest(keyword=keyword):
                self.assertEqual(generate.query_intent(keyword), expected)

    def test_words_inside_other_words_do_not_count(self):
        self.assertEqual(generate.query_intent("bestiary of austin"), "")
        self.assertEqual(generate.query_intent("toprak analysis"), "")

    def test_russian_word_forms(self):
        """Ключ в косвенном падеже — тот же ключ: «аренду», «цену», «лучших»."""
        cases = {
            "аренду экскаватора": "transactional",
            "узнать цену на окна": "transactional",
            "низких цен на визы": "transactional",
            "стоимости доставки": "transactional",
            "сколько стоят окна пвх": "transactional",
            "сколько будет стоить виза": "transactional",
            "дешёвые билеты в сочи": "transactional",
            "дешевые билеты в сочи": "transactional",
            "недорогие отели сочи": "transactional",
            "скидку на визу": "transactional",
            "торт на заказ": "transactional",
            "квартиры посуточно": "transactional",
            "лучших сантехников москвы": "commercial",
            "отзывов о сервисе виз": "commercial",
            "что лучше": "commercial",
            "аналоги фотошопа": "commercial",
        }
        for keyword, expected in cases.items():
            with self.subTest(keyword=keyword):
                self.assertEqual(generate.query_intent(keyword), expected)

    def test_russian_stems_do_not_overmatch(self):
        for keyword in ("сцена театра", "центр города", "ценные бумаги", "ценность бренда",
                        "стоянка у вокзала", "заказник в карелии", "заказчик проекта",
                        "аналоговый синтезатор", "отзывчивый персонал", "топ-менеджер вакансии",
                        "лучи солнца", "любой ценой"):
            with self.subTest(keyword=keyword):
                self.assertEqual(generate.query_intent(keyword), "")

    def test_wrong_labels_from_ambiguous_words(self):
        cases = {
            # «или» само по себе не сравнение.
            "чай или кофе": "",
            # «снять» — аренда только рядом с жильём; вопрос «как» сильнее слабого глагола.
            "как снять порчу": "informational",
            "снять порчу": "",
            "снять домашнее видео": "",
            "снять квартиру в сочи": "transactional",
            "как снять квартиру": "informational",
            "как оформить визу": "informational",
            # Английские слова, которые бывают не про покупку.
            "best book on python": "commercial",
            "book a hotel in paris": "transactional",
            "how to book a flight": "informational",
            "order of operations": "",
            "order pizza online": "transactional",
            "einstein quote": "",
            "get a quote for roofing": "transactional",
            "big deal": "",
            "deals on laptops": "transactional",
            "price of gold": "commercial",
            "plumber price austin": "transactional",
            "tank top": "",
            "top up phone balance": "",
            "top 10 plumbers austin": "commercial",
            "top-rated plumbers": "commercial",
            "vs code": "",
            "vs code extensions": "",
            "vs code vs sublime": "commercial",
        }
        for keyword, expected in cases.items():
            with self.subTest(keyword=keyword):
                self.assertEqual(generate.query_intent(keyword), expected)

    def test_plan_counts_and_writes_them(self):
        root = tempfile.mkdtemp(prefix="indexgap-intent-")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "k.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("keyword,city\nbuy pipes austin,Austin\nbest plumbers dallas,Dallas\n"
                     "how to fix a tap boston,Boston\nplumbing denver,Denver\n")
        out = os.path.join(root, "plan.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["plan", path, "--json", out]), 0)
        self.assertIn("покупка 1", buf.getvalue())
        data = json.load(open(out, encoding="utf-8"))
        self.assertEqual({k["keyword"]: k["intent"] for k in data["keep"]},
                         {"buy pipes austin": "transactional", "best plumbers dallas": "commercial",
                          "how to fix a tap boston": "informational", "plumbing denver": ""})


if __name__ == "__main__":
    unittest.main()
