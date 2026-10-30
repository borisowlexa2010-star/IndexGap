# -*- coding: utf-8 -*-
"""
Параллельный разбор даёт то же, что однопроцессный — на любой системе.

Он включается с 2 000 страниц, и до этого теста ни один тест его не
проходил: Windows и macOS запускают процессы через spawn, и ошибка там
видна только на настоящем большом сайте.
"""

import os
import pickle
import shutil
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import core

SITE = "https://example.com"


class Parallel(unittest.TestCase):
    def test_parallel_and_sequential_parse_alike(self):
        root = tempfile.mkdtemp(prefix="indexgap-par-")
        self.addCleanup(shutil.rmtree, root, True)
        for n in range(40):
            path = os.path.join(root, f"p{n}", "index.html")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"<!doctype html><html lang=\"ru\"><head><title>Страница {n}</title>"
                         f"</head><body><main><h1>Страница {n}</h1><p>{'текст ' * (20 + n)}"
                         f"</p><p>Смена <a href=\"/p{n}/\">экскаватора</a>, цена <b>{n}</b>.</p>"
                         f"<a href=\"/p{(n + 1) % 40}/\">дальше</a></main></body></html>")
        # Markdown рядом со сборкой HTML — не страница, поэтому отдельный сайт.
        md_root = tempfile.mkdtemp(prefix="indexgap-par-md-")
        self.addCleanup(shutil.rmtree, md_root, True)
        for n in range(40):
            with open(os.path.join(md_root, f"p{n}.md"), "w", encoding="utf-8") as fh:
                fh.write(f"# Заметка {n}\n\nСмена [экскаватора](p{(n + 1) % 40}.md), "
                         f"цена **{n}**.\n\n- пункт {n}\n")

        def snapshot(pages):
            return [(p.url, p.title, p.text, tuple(p.links), p.paragraphs, p.blocks)
                    for p in pages]

        for site, glued in ((root, "Смена экскаватора , цена 3 ."),
                            (md_root, "Смена экскаватора, цена 3.")):
            one = snapshot(core.load_pages(site, SITE, jobs=1)[0])
            with mock.patch.object(core, "PARALLEL_FROM", 0):
                many = snapshot(core.load_pages(site, SITE, jobs=2)[0])
            self.assertEqual(len(one), 40)
            self.assertTrue(any(glued in page[4] for page in one))
            self.assertEqual(one, many)


class PackedParagraphs(unittest.TestCase):
    """Абзацы хранятся кусками основного текста — и читаются как раньше."""

    HTML = ("<!doctype html><html><head><title>t</title></head><body><nav>меню</nav>"
            "<main><h1>Аренда</h1><p>Смена <a href=\"/a/\">экскаватора</a>, цена "
            "<b>12 000</b>.</p><p>Доставка включена в цену.</p></main></body></html>")
    WANT = ["Смена экскаватора , цена 12 000 .", "Доставка включена в цену."]

    def page(self, name="index.html", body=None):
        root = tempfile.mkdtemp(prefix="indexgap-para-")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body or self.HTML)
        return core.load_page(path, root, SITE)

    def test_glued_markup_reads_as_before(self):
        page = self.page()
        self.assertEqual(page.paragraphs, self.WANT)
        self.assertNotIn(self.WANT[0], page.text)
        # Ни один абзац не лежит строкой: все собираются из кусков текста.
        self.assertEqual(page.__dict__["_para"][2], [])

    def test_pickle_keeps_one_text(self):
        page = pickle.loads(pickle.dumps(self.page()))
        self.assertEqual(page.paragraphs, self.WANT)
        self.assertIs(page.__dict__["_para"][0], page.text)

    def test_text_replaced_after_paragraphs(self):
        page = self.page()
        page.text = "совсем другой текст"
        self.assertEqual(page.paragraphs, self.WANT)

    def test_paragraph_missing_from_text_is_kept(self):
        page = core.Page(path="a", url=SITE + "/", text="один два")
        page.paragraphs = ["три четыре", "один два", ""]
        self.assertEqual(page.paragraphs, ["три четыре", "один два", ""])
        page.paragraphs = []
        self.assertEqual(page.paragraphs, [])
        self.assertEqual(core.Page(path="b", url=SITE + "/b").paragraphs, [])

    def test_markdown(self):
        page = self.page("notes.md", "---\ntitle: t\n---\n\nСмена [экскаватора](a/), "
                                     "цена **12**.\n\n- пункт списка\n")
        self.assertEqual(page.paragraphs, ["Смена экскаватора, цена 12.", "пункт списка"])
        self.assertEqual(page.__dict__["_para"][2], [])


if __name__ == "__main__":
    unittest.main()
