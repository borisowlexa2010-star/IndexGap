# -*- coding: utf-8 -*-
"""
Что прогон по eventiq.io увидел вместе с таблицами и оставил на потом.

* `no-question-headings` считал заголовки шаблона вместе с заголовками
  статьи: колонки подвала («Platform», «Blog») стоят на 86 страницах из 87,
  призыв к действию — на 83, «Keep reading» — на 82. У медианной страницы
  40% подзаголовков приходили из шаблона, и доля вопросов занижалась везде.
* `vague-anchor` мерил «ROI» и «FAQ» длиной: меньше четырёх знаков —
  «неинформативно». Аббревиатура заглавными — обычная подпись пункта меню.
* `<h5>`, `<h6>`, `<figcaption>`, `<blockquote>` и `<br><br>` не заканчивали
  абзац: подпись к рисунку склеивалась с текстом вокруг.
* В Markdown текст сразу под заголовком, без пустой строки, в абзацы не
  попадал, а нумерованный список не считался списком.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, content, core

SITE = "https://example.com"
PROSE = ("Смена экскаватора стоит 18000 рублей за восемь часов работы на объекте, "
         "включая доставку техники в пределах города и работу машиниста.")


def doc(main, after=""):
    return ("<!doctype html><html lang=\"en\"><head><title>Event reports</title></head>"
            f"<body><header><a href=\"/\">EventIQ</a></header>"
            f"<main><article><h1>Event reports</h1>{main}</article></main>{after}"
            "</body></html>")


class Fixture(unittest.TestCase):
    def page(self, text, name="index.html"):
        root = tempfile.mkdtemp(prefix="indexgap-template-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
            fh.write(text)
        return core.load_pages(root, SITE)[0][0]

    def codes(self, page):
        return [i[2] for i in aeo.check_extractable(page)]


class TemplateHeadings(Fixture):
    """Устройство страницы eventiq.io: вставки в <aside>, колонки в <footer>."""

    ARTICLE = (f"<h2>Who reads event reports?</h2><p>{PROSE}</p>"
               f"<h2>How often should each report go out?</h2><p>{PROSE}</p>"
               f"<h2>Where EventIQ fits</h2><p>{PROSE}</p>"
               f"<h2>See the records behind a report</h2><p>{PROSE}</p>")
    TEMPLATE_IN_MAIN = ("<aside class=\"article-related\"><h2>Keep reading</h2>"
                        "<a href=\"/a\">Event budgets explained</a></aside>"
                        "<aside class=\"article-cta\"><h2>See events, spend, and deals "
                        "in one view</h2></aside>")
    FOOTER = ("<footer><h3 class=\"footer-heading\">Platform</h3>"
              "<h3 class=\"footer-heading\">Blog</h3>"
              "<h3 class=\"footer-heading\">Company</h3></footer>")

    def test_aside_and_footer_headings_are_not_the_article(self):
        page = self.page(doc(self.ARTICLE + self.TEMPLATE_IN_MAIN, self.FOOTER))
        # Две из четырёх — вопросы. С шаблоном было бы две из девяти.
        self.assertNotIn("no-question-headings", self.codes(page))

    def test_headings_of_the_page_are_all_still_collected(self):
        page = self.page(doc(self.ARTICLE + self.TEMPLATE_IN_MAIN, self.FOOTER))
        # `no-h1`, `many-h1` и повторяющийся скелет читают полный список.
        self.assertIn((3, "Platform"), page.headings)
        self.assertIn((2, "Keep reading"), page.headings)

    def test_an_article_without_questions_is_still_reported(self):
        article = "".join(f"<h2>Section {n}</h2><p>{PROSE}</p>" for n in range(4))
        page = self.page(doc(article + self.TEMPLATE_IN_MAIN, self.FOOTER))
        self.assertIn("no-question-headings", self.codes(page))

    def test_template_alone_does_not_make_the_page_judged(self):
        # Подзаголовков у статьи один, остальное — шаблон: судить не о чем.
        page = self.page(doc(f"<h2>Overview</h2><p>{PROSE}</p>" + self.TEMPLATE_IN_MAIN,
                             self.FOOTER))
        self.assertNotIn("no-question-headings", self.codes(page))

    def test_aside_written_in_the_article_body_is_still_template(self):
        # <aside> посреди статьи — врезка, а не раздел статьи.
        page = self.page(doc(self.ARTICLE[:120] + "<aside><h2>Related</h2></aside>"
                             + self.ARTICLE[120:]))
        self.assertNotIn((2, "Related"), page.outline)


class Abbreviations(unittest.TestCase):
    def vague(self, *anchors):
        page = core.Page(path="index.html", url=SITE + "/", anchors=list(anchors))
        issues = [i for i in content.check_brief([page]) if i[2] == "vague-anchor"]
        return issues[0][3] if issues else ""

    def test_capital_abbreviations_are_labels(self):
        self.assertEqual(self.vague("FAQ", "ROI", "API", "CRM", "ЖКХ"), "")

    def test_short_lowercase_words_still_count(self):
        self.assertIn("«тут»", self.vague("тут", "FAQ"))

    def test_one_capital_letter_is_not_an_abbreviation(self):
        self.assertIn("«A»", self.vague("A"))


class ParagraphEnds(Fixture):
    def paragraphs(self, body):
        return self.page(doc(body)).paragraphs

    def test_h5_and_h6_end_a_paragraph_and_are_headings(self):
        page = self.page(doc(f"<div>{PROSE}<h5>Small heading</h5>{PROSE}"
                             f"<h6>Smaller</h6>{PROSE}</div>"))
        self.assertEqual(page.paragraphs, [PROSE] * 3)
        self.assertIn((5, "Small heading"), page.headings)
        self.assertIn((6, "Smaller"), page.headings)

    def test_figcaption_is_its_own_block(self):
        got = self.paragraphs(f"<div>{PROSE}<figure><img src=\"a.png\" alt=\"a\">"
                              f"<figcaption>Рисунок 1. Экскаватор</figcaption></figure>"
                              f"{PROSE}</div>")
        self.assertEqual(got, [PROSE, "Рисунок 1. Экскаватор", PROSE])

    def test_blockquote_is_its_own_block(self):
        got = self.paragraphs(f"<div>{PROSE}<blockquote>Цитата клиента</blockquote>"
                              f"{PROSE}</div>")
        self.assertEqual(got, [PROSE, "Цитата клиента", PROSE])

    def test_double_br_ends_a_paragraph_single_does_not(self):
        got = self.paragraphs(f"<div>{PROSE}<br><br>{PROSE}<br>{PROSE}</div>")
        self.assertEqual(got, [PROSE, PROSE + " " + PROSE])

    def test_br_with_whitespace_between_still_ends_it(self):
        got = self.paragraphs(f"<div>{PROSE}<br>\n  <br/>{PROSE}</div>")
        self.assertEqual(got, [PROSE, PROSE])


class MarkdownBlocks(Fixture):
    def md(self, body):
        return self.page("---\ntitle: Аренда\n---\n" + body, name="page.md")

    def test_text_right_under_a_heading_is_a_paragraph(self):
        page = self.md(f"# Аренда\n\n## Цены\n{PROSE}\n")
        self.assertEqual(page.paragraphs, [PROSE])

    def test_numbered_list_is_a_list(self):
        words = " ".join(["слово"] * 420)
        page = self.md(f"{words}\n\n1. Первый шаг\n2. Второй шаг\n3. Третий шаг\n")
        self.assertEqual(page.blocks["li"], 3)
        self.assertNotIn("no-structure", self.codes(page))

    def test_table_inside_a_blockquote_is_not_a_paragraph(self):
        rows = "\n".join(f"> | Тариф {i} | {i * 1000} рублей за смену |" for i in range(40))
        page = self.md(f"{PROSE}\n\n> | Тариф | Цена |\n> |---|---|\n{rows}\n")
        self.assertEqual(page.paragraphs, [PROSE])
        self.assertEqual(page.blocks["table"], 1)


if __name__ == "__main__":
    unittest.main()
