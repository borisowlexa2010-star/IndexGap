# -*- coding: utf-8 -*-
"""
Пятнадцать чужих сайтов, которых пакет раньше не видел: ложные тревоги.

* перевод с тем же title — не дубль: `/de/` и `/fr/` не соперничают;
* `TODO:` в атрибуте `data-code` кнопки «копировать» — не текст страницы;
* `opt_*()` и `if ()` в заголовках справочника — не пустое место шаблона.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, content, core

SITE = "https://example.com"
TEXT = ("Plumbers fix leaks, unclog drains and install water heaters. Most visits take "
        "under two hours, and every job comes with a written quote first. ") * 3


def html(title, body="", lang="en", h2=""):
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title>'
            '<meta name="description" content="Same description in every language here">'
            f'</head><body><main><h1>{title}</h1>{h2}<p>{TEXT}</p>{body}</main></body></html>')


class Corpus(unittest.TestCase):
    def build(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-corpus4-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return core.load_pages(root, SITE)[0]

    def test_translations_share_a_title_without_competing(self):
        pages = self.build({"de/index.html": html("Congo", lang="de"),
                            "fr/index.html": html("Congo", lang="fr"),
                            "en/a/index.html": html("Same title", lang="en"),
                            "en/b/index.html": html("Same title", lang="en")})
        found = {(i[1], i[2]) for i in checks.technical_issues(pages)}
        self.assertNotIn((SITE + "/de/", "duplicate-title"), found)
        self.assertIn((SITE + "/en/a/", "duplicate-title"), found)
        self.assertNotIn((SITE + "/de/", "duplicate-description"), found)

    def test_a_todo_inside_an_attribute_is_not_text(self):
        body = ('<div class="copy"><button data-code="// TODO: handle errors\\nfetch()">'
                'Copy</button></div>')
        pages = self.build({"index.html": html("Fetch guide", body)})
        self.assertEqual([i for i in content.check_brief(pages) if i[2] == "brief-left"], [])
        pages = self.build({"index.html": html("Fetch guide", "<p>TODO: write this</p>")})
        self.assertTrue([i for i in content.check_brief(pages) if i[2] == "brief-left"])

    def test_reference_headings_are_not_empty_slots(self):
        for h2 in ("<h2>opt_*()</h2>", "<h2>if ()</h2>", "<h2>| - bitwise OR</h2>"):
            with self.subTest(h2=h2):
                pages = self.build({"index.html": html("Reference", "<pre>x | y</pre>", h2=h2)})
                self.assertEqual(content.check_slots(pages), [])


if __name__ == "__main__":
    unittest.main()
