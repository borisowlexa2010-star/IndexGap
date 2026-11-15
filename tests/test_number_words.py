# -*- coding: utf-8 -*-
"""
Числа прописью в сверке фактов.

На тестовом каталоге услуг по городам страница обещала «гарантия на работу —
двенадцать месяцев» при `6 месяцев` в строке датасета, и сверка прошла молча:
числа читались только цифрами. Та же страница с «12 месяцев» давала критичную
находку. Сроки и количества модель пишет словами охотнее, чем цены, — то есть
мимо проверки шла ровно та выдумка, ради которой она существует.

Читается только однозначное: числительное от 2 до 99 сразу перед единицей
проекта, по-русски и по-английски. Всё остальное — речь, и проверка молчит.

Уровень — «просмотри глазами»: прописью пишут и общие слова о предмете. На
демо-сайте «usually within three to six months» стоит в обычном абзаце при
`3 months` в строке, и критичная находка там была бы ложной.
"""

import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from types import SimpleNamespace

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, content

SITE = "https://example.com"


def page(text, lang="ru"):
    return SimpleNamespace(url=SITE + "/a/", text=text, lang=lang)


def checked(text, row, units, lang="ru"):
    """Находки о числах одной страницы: (критичные, «просмотри глазами»)."""
    p = page(text, lang)
    issues = content.check_facts([p], {p.url: row}, [row], fact_units=units)
    return ([i[3] for i in issues if i[2] == "unsupported-number"],
            [i[3] for i in issues if i[2] == "check-by-eye"])


def by_eye(text, row, units, lang="ru"):
    return checked(text, row, units, lang)[1]


class Russian(unittest.TestCase):
    ROW = {"keyword": "ремонт", "warranty": "6 месяцев", "arrival": "40 минут"}
    UNITS = ["месяцев", "минут"]

    def found(self, text, row=None):
        return by_eye(text, row or self.ROW, self.UNITS)

    def test_a_number_written_out_is_shown_to_the_reader(self):
        critical, found = checked("Гарантия на работу — двенадцать месяцев.",
                                  self.ROW, self.UNITS)
        self.assertEqual(len(found), 1)
        # Находка показывает число так, как оно стоит на странице.
        self.assertIn("двенадцать месяцев", found[0])
        # Список для просмотра, а не приговор: `--strict` на нём не падает.
        self.assertEqual(critical, [])

    def test_a_number_from_the_row_is_not_a_finding(self):
        self.assertEqual(self.found("Гарантия на работу — шесть месяцев."), [])
        self.assertEqual(self.found("Мастер приедет через сорок минут."), [])

    def test_the_genitive_is_read(self):
        self.assertEqual(len(self.found("Бесплатный ремонт в течение двенадцати месяцев.")), 1)
        self.assertEqual(self.found("Бесплатный ремонт в течение шести месяцев."), [])

    def test_tens_and_ones_are_one_number(self):
        found = self.found("Мастер приедет через двадцать пять минут.")
        self.assertEqual(len(found), 1)
        self.assertIn("двадцать пять минут", found[0])
        row = dict(self.ROW, arrival="25 минут")
        self.assertEqual(self.found("Мастер приедет через двадцать пять минут.", row), [])
        # Не 20 и не 5 по отдельности: строка с 20 не оправдывает «двадцать пять».
        row = dict(self.ROW, arrival="20 минут")
        self.assertEqual(len(self.found("Мастер приедет через двадцать пять минут.", row)), 1)

    def test_the_tail_of_a_bigger_number_is_not_read(self):
        # Сотни не разбираются; «сто двадцать» как 20 — неверное чтение,
        # а неверно прочитанное число хуже непрочитанного.
        row = dict(self.ROW, arrival="120 минут")
        self.assertEqual(self.found("Работа займёт сто двадцать минут.", row), [])
        self.assertEqual(self.found("Работа займёт сто двадцать минут."), [])

    def test_a_word_that_is_not_a_project_unit_is_speech(self):
        self.assertEqual(self.found("Объясним в два слова, почему три причины важны."), [])

    def test_a_unit_of_one_letter_or_a_function_word_is_not_a_unit(self):
        # «220 В» в датасете делает единицей предлог: «три в ряд» — не вольты.
        row = {"keyword": "ремонт", "power": "220 В", "term": "3 дня"}
        self.assertEqual(by_eye("Починим три в ряд.", row, ["в", "В"]), [])
        self.assertEqual(content.build_spelled_patterns(["в", "a", "in", "₽"]), {})

    def test_one_is_a_figure_of_speech(self):
        row = {"keyword": "ремонт", "term": "3 дня"}
        self.assertEqual(by_eye("Починим за один день.", row, ["день", "дня"]), [])
        # А «два дня» при трёх в строке — уже расхождение.
        self.assertEqual(len(by_eye("Починим за два дня.", row, ["день", "дня"])), 1)

    def test_the_digit_is_reported_once(self):
        critical, found = checked("Гарантия 12 месяцев. Да, целых двенадцать месяцев.",
                                  self.ROW, self.UNITS)
        self.assertEqual(len(critical), 1)
        self.assertIn("12", critical[0])
        self.assertEqual(found, [])

    def test_capitals_and_collective_numerals_are_read(self):
        self.assertEqual(len(self.found("ГАРАНТИЯ — ДВЕНАДЦАТЬ МЕСЯЦЕВ.")), 1)
        row = {"keyword": "ремонт", "term": "2 суток"}
        found = by_eye("Починим за трое суток.", row, ["суток"])
        self.assertEqual(len(found), 1)
        self.assertIn("трое суток", found[0])
        self.assertEqual(by_eye("Починим за двое суток.", row, ["суток"]), [])

    def test_a_typographic_dash_joins_tens_and_ones(self):
        # С одним ASCII-дефисом «двадцать–пять минут» читалось как «пять минут».
        row = dict(self.ROW, arrival="5 минут")
        for dash in ("-", "\u2010", "\u2011", "\u2013", "\u2014"):
            with self.subTest(dash=repr(dash)):
                found = self.found(f"Мастер приедет через двадцать{dash}пять минут.", row)
                self.assertEqual(len(found), 1)
                self.assertIn("двадцать", found[0])
        row = dict(self.ROW, arrival="25 минут")
        self.assertEqual(self.found("Мастер приедет через двадцать\u2013пять минут.", row), [])

    def test_a_dash_between_spaces_is_not_a_joiner(self):
        # Тире в пробелах разделяет части фразы: это «пять минут», а не 25.
        row = dict(self.ROW, arrival="5 минут")
        self.assertEqual(self.found("Мастеров двадцать \u2013 пять минут до вас.", row), [])

    def test_the_project_unit_is_not_hidden_behind_another_word(self):
        # То же число при случайном слове не должно прятать фразу с единицей
        # проекта — и наоборот: показываются оба написания.
        found = self.found("Нас выбрали 12 клиентов. Гарантия — двенадцать месяцев.")
        self.assertEqual(len(found), 1)
        self.assertIn("двенадцать месяцев", found[0])
        self.assertIn("12 клиентов", found[0])
        # И за «и ещё N» ей не место: в списке она первая.
        noise = " ".join(f"{1000 + i} клиентов." for i in range(9))
        found = self.found(noise + " Гарантия — двенадцать месяцев.")
        self.assertIn("двенадцать месяцев", found[0])

    def test_without_project_units_nothing_is_read(self):
        self.assertEqual(by_eye("Гарантия — двенадцать месяцев.", self.ROW, None), [])
        self.assertEqual(content.build_spelled_patterns([]), {})


class English(unittest.TestCase):
    ROW = {"keyword": "berlin", "deposit": "3 months", "commute": "34 minutes"}
    UNITS = ["months", "minutes"]

    def found(self, text, lang="en"):
        return by_eye(text, self.ROW, self.UNITS, lang)

    def test_a_number_written_out_is_shown_to_the_reader(self):
        found = self.found("Landlords ask for a deposit of twelve months of rent.")
        self.assertEqual(len(found), 1)
        self.assertIn("twelve months", found[0])
        self.assertEqual(self.found("Landlords ask for a deposit of three months."), [])

    def test_general_prose_is_a_list_to_look_through_not_a_verdict(self):
        # Абзац демо-сайта: общие слова о предмете при `3 months` в строке.
        critical, found = checked("The deposit comes back with interest, usually within "
                                  "three to six months of moving out.",
                                  self.ROW, self.UNITS, "en")
        self.assertEqual(critical, [])
        self.assertEqual(len(found), 1)
        self.assertIn("six months", found[0])

    def test_tens_and_ones_with_and_without_a_hyphen(self):
        for text in ("The commute is forty-five minutes.", "The commute is forty five minutes."):
            with self.subTest(text=text):
                self.assertEqual(len(self.found(text)), 1)
        self.assertEqual(self.found("The commute is thirty-four minutes."), [])

    def test_the_tail_of_a_bigger_number_is_not_read(self):
        self.assertEqual(self.found("The lease runs one hundred and twenty months."), [])
        self.assertEqual(self.found("It took two thousand five minutes."), [])
        # И через знак: запятая или дефис числа не начинают.
        self.assertEqual(self.found("It took one thousand, twenty minutes."), [])
        self.assertEqual(self.found("The lease runs one hundred-twenty months."), [])

    def test_one_and_plain_speech_are_not_read(self):
        row = {"keyword": "berlin", "notice": "3 month"}
        self.assertEqual(by_eye("Cancel within one month.", row, ["month"], "en"), [])
        self.assertEqual(self.found("Three reasons and two ways to save."), [])

    def test_the_numeral_and_the_unit_are_whole_words(self):
        # «often months» — не «ten months», а единица `month` — не начало «months».
        self.assertEqual(self.found("Deposits are often months late."), [])
        row = {"keyword": "berlin", "notice": "3 month"}
        self.assertEqual(by_eye("A stay of six months.", row, ["month"], "en"), [])
        self.assertEqual(len(self.found("Twelve Months of rent.")), 1)

    def test_a_typographic_dash_joins_tens_and_ones(self):
        # «twenty‑six months» при 6 в строке: выдуманные 26 сходили за данные.
        row = dict(self.ROW, deposit="6 months")
        for dash in ("\u2010", "\u2011", "\u2013", "\u2014"):
            with self.subTest(dash=repr(dash)):
                found = by_eye(f"A deposit of twenty{dash}six months.", row, self.UNITS, "en")
                self.assertEqual(len(found), 1)
                self.assertIn("twenty", found[0])
        # Мягкий перенос стоит внутри слова и на странице не виден.
        found = by_eye("A deposit of twen\u00adty-six months.", row, self.UNITS, "en")
        self.assertEqual(len(found), 1)
        self.assertIn("twenty-six months", found[0])

    def test_a_dash_between_spaces_is_not_a_joiner(self):
        row = dict(self.ROW, commute="5 minutes")
        self.assertEqual(by_eye("The crew numbers twenty \u2014 five minutes after your call "
                                "they are on the road.", row, self.UNITS, "en"), [])

    def test_a_numeral_glued_to_another_word_is_not_read(self):
        # «top-six months» — не «six months»; «fourty-six» при 6 в строке не
        # должно сойти за данные, а раз слово не прочитано — проверка молчит.
        self.assertEqual(self.found("A top-six months ranking and a sub-ten minutes run."), [])
        self.assertEqual(self.found("A deposit of fourty-six months."), [])

    def test_neighbouring_blocks_are_not_one_number(self):
        # Пункты списка в тексте страницы разделены пробелом.
        row = dict(self.ROW, commute="5 minutes")
        self.assertEqual(by_eye("A crew of twenty Five minutes from the centre",
                                row, self.UNITS, "en"), [])
        self.assertEqual(len(by_eye("Twenty Five Minutes From The Centre",
                                    row, self.UNITS, "en")), 1)

    def test_a_digit_with_another_word_is_still_shown(self):
        # Раньше список называл «6 awards»; фраза прописью его не вытесняет.
        found = self.found("We won 6 awards. The deposit comes back within three to six months.")
        self.assertEqual(len(found), 1)
        self.assertIn("six months", found[0])
        self.assertIn("6 awards", found[0])

    def test_a_function_word_is_not_a_unit(self):
        row = {"keyword": "berlin", "fuse": "16 A", "width": "30 in"}
        self.assertEqual(by_eye("Take two a day or twelve a week, two in a row.",
                                row, ["a", "in"], "en"), [])

    def test_a_letter_outside_the_dictionary_is_not_read(self):
        # Без учёта регистра `i` совпадает с турецкими `İ` и `ı`, `s` — с `ſ`.
        # Поиск по словарю падал с KeyError и останавливал весь прогон.
        for text in ("WARRANTY: SİX MONTHS.", "sıx months", "ſix months",
                     "THİRTY minutes", "thırty-five minutes", "twenty-sıx minutes"):
            with self.subTest(text=text):
                self.assertEqual(self.found(text), [])

    def test_the_dictionary_is_used_only_for_its_own_language(self):
        text = "Kaution: twelve months."
        self.assertEqual(self.found(text, lang="de"), [])
        # Без `lang` язык неизвестен — читаются оба словаря.
        self.assertEqual(len(self.found(text, lang="")), 1)
        self.assertEqual(len(self.found(text, lang="en-GB")), 1)
        self.assertEqual(len(self.found(text, lang="EN")), 1)
        self.assertEqual(self.found(text, lang="DE"), [])


class ThroughTheCommandLine(unittest.TestCase):
    """Тест защищает ровно ту строку, которая в нём записана: путь через `check`."""

    def test_check_lists_the_written_out_number(self):
        root = tempfile.mkdtemp(prefix="indexgap-words-")
        self.addCleanup(shutil.rmtree, root, True)
        site = os.path.join(root, "site")
        rows = [("kazan", "6 месяцев", "двенадцать месяцев"),
                ("samara", "9 месяцев", "девять месяцев")]
        for slug, _, written in rows:
            os.makedirs(os.path.join(site, "remont", slug))
            with open(os.path.join(site, "remont", slug, "index.html"), "w",
                      encoding="utf-8") as fh:
                fh.write('<!doctype html><html lang="ru"><head><title>Ремонт стиральных '
                         f'машин: {slug}</title></head><body><main><h1>Ремонт: {slug}</h1>'
                         f"<p>Гарантия на работу — {written}.</p></main></body></html>")
        dataset = os.path.join(root, "rows.csv")
        with open(dataset, "w", encoding="utf-8") as fh:
            fh.write("keyword,warranty\n" + "".join(f"{s},{w}\n" for s, w, _ in rows))
        out = os.path.join(root, "r.json")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", site, "--site", SITE, "--dataset", dataset,
                             "--no-aeo", "--out", out])
        self.assertEqual(code, 0)
        data = json.loads(pathlib.Path(out).read_text(encoding="utf-8"))
        found = {i["url"]: i for i in data["issues"] if i["code"] == "check-by-eye"}
        self.assertEqual(list(found), [SITE + "/remont/kazan/"])
        self.assertIn("двенадцать месяцев", found[SITE + "/remont/kazan/"]["message"])
        self.assertEqual(found[SITE + "/remont/kazan/"]["level"], "info")
        self.assertNotIn("unsupported-number", [i["code"] for i in data["issues"]])


if __name__ == "__main__":
    unittest.main()
