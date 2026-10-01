# -*- coding: utf-8 -*-
"""
Разбор HTML: находки ревью десяти агентов перед публичным запуском.

Счётчик вложенности считал открывающие теги и закрывающие, не глядя на то,
какие из них пары. HTML так не устроен: `<img>`, `<br>` и `<hr>` не закрываются
вовсе, `<p>` и `<li>` закрывать не обязательно, а самозакрывающийся `<path/>`
внутри пропускаемого `<svg>` закрывал то, что не открывал. Каждый такой тег
сдвигал глубину на единицу, и основной блок кончался не там, где кончался.

Цена была не в одной проверке. Подвал попадал в текст страницы и в её хэш —
смена года в подвале меняла `lastmod` всего сайта. Логотип в шапке оставлял
страницу без абзацев. Иконка посреди текста обрезала его до первых слов.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, core

SITE = "https://example.com"
BODY = "Смена экскаватора стоит 18000 рублей за восемь часов работы на объекте."
FOOTER = "<footer><p>Подвал сайта, год и реквизиты компании.</p></footer>"


class Fixture(unittest.TestCase):
    def page(self, html, name="index.html"):
        root = tempfile.mkdtemp(prefix="indexgap-parser-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
            fh.write(html)
        return core.load_pages(root, SITE)[0][0]


class TestDepth(Fixture):
    def test_void_tag_in_main_does_not_leak_footer(self):
        for tag in ('<img src="a.png" alt="a">', "<br>", "<hr>", '<input type="text">'):
            page = self.page(f"<html><body><main><h1>Заголовок</h1><p>{BODY}</p>{tag}</main>"
                             f"{FOOTER}</body></html>")
            self.assertNotIn("Подвал", page.text, tag)
            self.assertEqual(page.paragraphs, [BODY], tag)

    def test_void_tag_in_main_does_not_leak_footer_into_hash(self):
        """Иначе смена года в подвале меняет хэш и `lastmod` каждой страницы."""
        def digest(year):
            return self.page(
                f"<html><body><main><h1>Заголовок</h1><p>Первая<br>вторая строка.</p></main>"
                f"<footer><p>© {year} Компания</p></footer></body></html>").content_hash
        self.assertEqual(digest(2026), digest(2027))

    def test_logo_in_the_header_does_not_cost_the_page_its_paragraphs(self):
        page = self.page('<html><body><nav><a href="/"><img src="l.png" alt=""></a></nav>'
                         f"<main><h1>Заголовок</h1><p>{BODY}</p></main></body></html>")
        self.assertEqual(page.paragraphs, [BODY])
        self.assertEqual(aeo.check_answer(page), [])

    def test_unclosed_paragraphs_and_list_items_are_valid_html(self):
        """Минификаторы с `removeOptionalTags` выдают именно такое."""
        page = self.page(f"<html><body><main><h1>Заголовок</h1><p>{BODY}<p>Второй абзац "
                         "тоже достаточно длинный, чтобы считаться абзацем.<ul><li>первый пункт"
                         f"<li>второй пункт</ul></main>{FOOTER}</body></html>")
        self.assertNotIn("Подвал", page.text)
        self.assertEqual(page.paragraphs[0], BODY)

    def test_self_closing_tag_inside_svg_does_not_close_main(self):
        page = self.page(f'<html><body><main><h1>Заголовок</h1><p>{BODY}</p>'
                         '<svg viewBox="0 0 1 1"><path d="M0"/><use href="#i"/></svg>'
                         "<p>Второй абзац стоит после иконки и обязан остаться в тексте "
                         f"страницы.</p></main>{FOOTER}</body></html>")
        self.assertIn("после иконки", page.text)
        self.assertEqual(len(page.paragraphs), 2)
        self.assertNotIn("Подвал", page.text)

    def test_noscript_with_an_image_inside_a_heading(self):
        page = self.page('<html><body><main><h1>Заголовок<noscript><img src="p.gif"/></noscript>'
                         f"</h1><p>{BODY}</p></main>{FOOTER}</body></html>")
        self.assertEqual(page.paragraphs, [BODY])
        self.assertNotIn("Подвал", page.text)

    def test_a_stray_closing_tag_is_ignored(self):
        page = self.page(f"<html><body><main><h1>Заголовок</h1></span><p>{BODY}</p>"
                         f"<p>Второй абзац после лишнего закрывающего тега остаётся в тексте.</p>"
                         f"</main>{FOOTER}</body></html>")
        self.assertEqual(len(page.paragraphs), 2)
        self.assertNotIn("Подвал", page.text)


class TestAsideBlocks(Fixture):
    """Служебный блок узнаётся по целому классу, а не по куску имени."""

    def test_a_wrapper_that_merely_mentions_toc_keeps_its_text(self):
        for attrs in ('body class="page has-toc"', 'article class="post with-breadcrumbs"',
                      'div class="toc-content article-body"', 'div class="byline-free"',
                      'div class="layout_toc_right"'):
            tag = attrs.split()[0]
            inner = f"<{attrs}><h1>Заголовок</h1><p>{BODY}</p></{tag}>"
            html = (f"<html>{inner}</html>" if tag == "body"
                    else f"<html><body><main>{inner}</main></body></html>")
            page = self.page(html)
            self.assertEqual(page.paragraphs, [BODY], attrs)

    def test_real_service_blocks_are_still_skipped(self):
        page = self.page('<html><body><main><nav class="breadcrumbs"><a href="/">Home</a> / Раздел</nav>'
                         '<p class="article-byline">Автор Иван Петров · 18 сентября 2026</p>'
                         '<div class="toc"><p>На этой странице есть несколько разделов</p></div>'
                         f"<h1>Заголовок</h1><p>{BODY}</p></main></body></html>")
        self.assertEqual(page.paragraphs, [BODY])

    def test_if_skipping_leaves_nothing_the_paragraphs_come_back(self):
        """Некоторые фреймворки оборачивают в <nav> весь контент. Ноль абзацев
        на полной странице — ложная тревога хуже, чем крошки первым абзацем."""
        page = self.page(f"<html><body><main><nav><h1>Заголовок</h1><p>{BODY}</p></nav></main></body></html>")
        self.assertEqual(page.paragraphs, [BODY])


if __name__ == "__main__":
    unittest.main()
