# -*- coding: utf-8 -*-
"""
Абзац — это проза: таблица, список определений и блок кода ею не являются.

Прогон по собранному eventiq.io дал `long-paragraph` на 43 страницах из 87.
Из 55 блоков длиннее 900 символов абзацем прозы был один. 53 — таблицы,
склеенные в строку «подпись заголовки ячейка ячейка …», ещё один — `<dl>` на
/ai-facts, все `<dt>` и `<dd>` подряд. На сайте документации самого пакета то
же давали `<pre>` с выводом `--help`.

Причина одна: абзац закрывался только на `</p>`, `</div>`, `</section>`,
`</li>` и на открытии `<p>` и заголовка. Ячейка, строка таблицы, `<dt>` и
`<pre>` буфер не закрывали, и всё между двумя такими границами становилось
одним «абзацем». Совет «разбей подзаголовками» для таблицы вреден, а первым
абзацем страницы, которая начинается с таблицы, оказывалась её подпись.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, core

SITE = "https://example.com"
# Около двухсот символов: обычный абзац, к длине которого вопросов нет.
PROSE = ("Смена экскаватора стоит 18000 рублей за восемь часов работы на объекте, "
         "включая доставку техники в пределах города и работу машиниста. Каждый "
         "следующий час оплачивается отдельно по тарифу.")
# Настоящий длинный абзац: больше тысячи символов прозы подряд.
LONG_PROSE = " ".join([PROSE] * 6)
CAPTION = "Сравнение тарифов на аренду строительной техники"


def table(rows=25, caption=CAPTION):
    body = "".join(
        f"<tr><td>Тариф номер {i}</td><td>{i * 1000} рублей за смену</td>"
        f"<td>Доставка включена в цену</td></tr>" for i in range(rows))
    return (f"<table><caption>{caption}</caption><thead><tr><th>Тариф</th><th>Цена</th>"
            f"<th>Условия</th></tr></thead><tbody>{body}</tbody></table>")


def doc(body):
    return ("<!doctype html><html lang=\"ru\"><head><title>Аренда техники</title></head>"
            f"<body><main><h1>Аренда техники</h1>{body}</main></body></html>")


class Fixture(unittest.TestCase):
    def page(self, text, name="index.html"):
        root = tempfile.mkdtemp(prefix="indexgap-prose-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
            fh.write(text)
        return core.load_pages(root, SITE)[0][0]

    def codes(self, page):
        return [i[2] for i in aeo.check_answer(page) + aeo.check_extractable(page)]


class TestTable(Fixture):
    def test_fixture_is_what_the_names_say(self):
        """Таблица на полторы тысячи символов и абзацы по двести — как в задаче."""
        page = self.page(doc(table()))
        self.assertGreater(len(page.text), 1500)
        self.assertTrue(150 < len(PROSE) < 250, len(PROSE))
        self.assertTrue(1000 < len(LONG_PROSE) < 1200, len(LONG_PROSE))

    def test_table_is_not_a_long_paragraph(self):
        page = self.page(doc(f"<p>{PROSE}</p>{table()}<p>{PROSE}</p>"))
        self.assertEqual(page.paragraphs, [PROSE, PROSE])
        self.assertNotIn("long-paragraph", self.codes(page))

    def test_long_prose_is_still_reported(self):
        page = self.page(doc(f"<p>{PROSE}</p><p>{LONG_PROSE}</p>{table()}"))
        self.assertIn("long-paragraph", self.codes(page))

    def test_table_keeps_its_place_in_the_text_and_counters(self):
        """Текст, слова, хэш и счётчик таблиц считаются не из абзацев."""
        page = self.page(doc(f"<p>{PROSE}</p>{table()}"))
        self.assertIn(CAPTION, page.text)
        self.assertIn("Тариф номер 24 24000 рублей за смену", page.text)
        self.assertEqual(page.blocks["table"], 1)
        self.assertEqual(page.blocks["p"], 1)
        bare = self.page(doc(f"<p>{PROSE}</p>"))
        self.assertGreater(page.word_count, bare.word_count + 200)
        other = self.page(doc(f"<p>{PROSE}</p>{table().replace('24000', '25000')}"))
        self.assertNotEqual(page.content_hash, other.content_hash)

    def test_first_paragraph_is_not_the_caption(self):
        """Страница начинается с таблицы — прямой ответ всё равно ищется в прозе."""
        page = self.page(doc(f"{table()}<p>{PROSE}</p>"))
        self.assertEqual(page.paragraphs[0], PROSE)
        self.assertEqual(self.codes(page), [])

    def test_text_around_the_table_does_not_stick_to_it(self):
        """`<p>` без закрывающего тега и голый текст в обёртке — отдельные блоки."""
        page = self.page(doc(f"<p>{PROSE}{table()}<div>{PROSE}{table()}{PROSE}</div>"))
        self.assertEqual(page.paragraphs, [PROSE, PROSE, PROSE])

    def test_page_that_is_only_a_table_still_has_blocks(self):
        """
        Ноль абзацев дал бы предупреждение «цитировать нечего» — про страницу,
        на которой есть таблица. Когда прозы нет, блоками служат ячейки, каждая
        отдельно; подпись среди них не появляется никогда — это заголовок.
        """
        page = self.page(doc(table()))
        self.assertIn("Доставка включена в цену", page.paragraphs)
        self.assertNotIn(CAPTION, " ".join(page.paragraphs))
        self.assertLess(max(len(p) for p in page.paragraphs), 60)
        codes = self.codes(page)
        self.assertNotIn("no-answer", codes)
        self.assertNotIn("long-paragraph", codes)

    def test_paragraph_inside_a_layout_table_is_a_paragraph(self):
        """Вёрстка таблицами: текст лежит в `<td><p>`, и это обычные абзацы."""
        page = self.page(
            "<html><head><title>Аренда техники</title></head><body><table><tr>"
            f"<td>Меню сайта</td><td><h1>Аренда</h1><p>{PROSE}</p><p>{PROSE}</p></td>"
            "</tr></table><div>Все права защищены, 2003</div></body></html>")
        self.assertEqual(page.paragraphs[:2], [PROSE, PROSE])

    def test_nested_table_is_still_a_table(self):
        inner = "<table><tr><td>Вложенная ячейка с данными о цене</td></tr></table>"
        page = self.page(doc(f"<p>{PROSE}</p><table><tr><td><p>{PROSE}</p>{inner}</td></tr></table>"))
        self.assertEqual(page.paragraphs, [PROSE, PROSE])


class TestDefinitionList(Fixture):
    def pairs(self, count=20):
        return "".join(
            f"<dt>Показатель номер {i}</dt><dd>Значение показателя номер {i} за прошлый год "
            f"составило {i * 7} процентов.</dd>" for i in range(count))

    def test_each_term_with_its_definition_is_a_block(self):
        page = self.page(doc(f"<p>{PROSE}</p><dl>{self.pairs()}</dl><p>{PROSE}</p>"))
        self.assertEqual(len(page.paragraphs), 22)
        self.assertEqual(page.paragraphs[1],
                         "Показатель номер 0 Значение показателя номер 0 за прошлый год "
                         "составило 0 процентов.")
        self.assertNotIn("long-paragraph", self.codes(page))

    def test_pairs_wrapped_in_div_and_terms_sharing_a_definition(self):
        """`<dl><div>` разрешён в HTML5; два `<dt>` подряд — один блок с их `<dd>`."""
        page = self.page(doc(
            "<dl><div><dt>Категория продукта</dt><dd>Программа для учёта аренды.</dd></div>"
            "<div><dt>Основана</dt><dt>Запущена</dt><dd>В 2019 году в Казани.</dd>"
            "<dd>Публичный запуск — в 2020 году.</dd></div></dl>"))
        self.assertEqual(page.paragraphs, [
            "Категория продукта Программа для учёта аренды.",
            "Основана Запущена В 2019 году в Казани. Публичный запуск — в 2020 году."])

    def test_text_before_the_list_does_not_stick_to_the_first_term(self):
        page = self.page(doc(f"<div>{PROSE}<dl>{self.pairs(2)}</dl>{PROSE}</div>"))
        self.assertEqual(page.paragraphs[0], PROSE)
        self.assertEqual(page.paragraphs[-1], PROSE)
        self.assertEqual(len(page.paragraphs), 4)

    def test_long_definition_is_still_reported(self):
        """Определение на тысячу символов — такой же длинный блок, как абзац."""
        page = self.page(doc(f"<p>{PROSE}</p><dl><dt>Условия</dt><dd>{LONG_PROSE}</dd></dl>"))
        self.assertIn("long-paragraph", self.codes(page))


class TestPreformatted(Fixture):
    CODE = "\n".join(f"line_{i} = compute(value_{i}, other_{i})" for i in range(40))

    def test_code_block_is_not_a_paragraph(self):
        """В Markdown блоки кода из абзацев вырезались всегда; в HTML — нет."""
        page = self.page(doc(f"<p>{PROSE}</p><pre><code>{self.CODE}</code></pre><p>{PROSE}</p>"))
        self.assertEqual(page.paragraphs, [PROSE, PROSE])
        self.assertNotIn("long-paragraph", self.codes(page))
        self.assertIn("line_39 = compute(value_39, other_39)", page.text)

    def test_code_first_does_not_become_the_answer(self):
        page = self.page(doc(f"<pre>{self.CODE}</pre><p>{PROSE}</p>"))
        self.assertEqual(page.paragraphs[0], PROSE)


class TestMarkdown(Fixture):
    ROWS = "\n".join(f"| Тариф номер {i} | {i * 1000} рублей за смену | Доставка включена в цену |"
                     for i in range(25))
    TABLE = "| Тариф | Цена | Условия |\n|---|:---:|---|\n" + ROWS

    def md(self, body):
        return self.page(f"---\ntitle: Аренда техники\n---\n\n{body}\n", "index.md")

    def test_pipe_table_is_not_a_long_paragraph(self):
        page = self.md(f"{PROSE}\n\n{self.TABLE}\n\n{PROSE}")
        self.assertEqual(page.paragraphs, [PROSE, PROSE])
        self.assertNotIn("long-paragraph", self.codes(page))
        self.assertEqual(page.blocks["table"], 1)
        self.assertIn("Тариф номер 24", page.text)

    def test_table_without_outer_pipes_and_text_right_above_it(self):
        rows = "\n".join(f"Тариф номер {i} | {i * 1000} рублей за смену" for i in range(40))
        page = self.md(f"{PROSE}\nТариф | Цена\n--- | ---\n{rows}\n\n{PROSE}")
        self.assertEqual(page.paragraphs, [PROSE, PROSE])

    def test_table_first_does_not_become_the_answer(self):
        page = self.md(f"{self.TABLE}\n\n{PROSE}")
        self.assertEqual(page.paragraphs[0], PROSE)
        self.assertEqual(self.codes(page), [])

    def test_page_that_is_only_a_table_still_has_blocks(self):
        page = self.md(self.TABLE)
        self.assertIn("Доставка включена в цену", page.paragraphs)
        self.assertNotIn("no-answer", self.codes(page))
        self.assertNotIn("long-paragraph", self.codes(page))

    def test_table_written_in_tags_is_not_a_paragraph(self):
        """Так таблицы записаны в исходниках eventiq.io: `<table>` внутри Markdown."""
        page = self.md(f"{PROSE}\n\n<div class=\"table-scroll\">\n{table()}\n</div>\n\n{PROSE}")
        self.assertEqual(page.paragraphs, [PROSE, PROSE])
        self.assertNotIn("long-paragraph", self.codes(page))
        self.assertIn("Тариф номер 24", page.text)
        only = self.md(table())
        self.assertTrue(only.paragraphs)
        self.assertNotIn("no-answer", self.codes(only))

    def test_dashes_in_prose_are_not_a_table(self):
        """Строка с чертой и тире — не разделитель таблицы."""
        text = "Цена — 18000 рублей | доставка включена\nв стоимость смены - без доплат."
        page = self.md(f"{text}\n\n{PROSE}")
        self.assertEqual(len(page.paragraphs), 2)
        self.assertIn("доставка включена", page.paragraphs[0])

    def test_list_items_are_separate_blocks(self):
        """В HTML каждый `<li>` — свой блок; список в Markdown был одним."""
        items = "\n".join(f"- Пункт списка номер {i}: доставка включена\n  в цену смены"
                          for i in range(25))
        page = self.md(f"{PROSE}\n{items}\n\n1. Первый шаг: оставить заявку\n2) Второй шаг\n\n{PROSE}")
        self.assertEqual(len(page.paragraphs), 29)
        self.assertEqual(page.paragraphs[0], PROSE)
        self.assertEqual(page.paragraphs[1], "Пункт списка номер 0: доставка включена в цену смены")
        self.assertEqual(page.paragraphs[26:28], ["Первый шаг: оставить заявку", "Второй шаг"])
        self.assertNotIn("long-paragraph", self.codes(page))

    def test_long_prose_is_still_reported(self):
        page = self.md(f"{PROSE}\n\n{LONG_PROSE}")
        self.assertIn("long-paragraph", self.codes(page))


if __name__ == "__main__":
    unittest.main()
