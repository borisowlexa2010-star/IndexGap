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
from indexgap import checks, content, core, signals

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

    def test_links_to_the_site_under_another_host_are_named(self):
        # ryan-han.com: CNAME, а все ссылки — на integerous.github.io.
        files = {"index.html": html("Home", "".join(
            f'<a href="http://old.github.io/p{i}/">p{i}</a>' for i in range(8)))}
        for i in range(8):
            files[f"p{i}/index.html"] = html(f"Post number {i}",
                                             '<a href="http://old.github.io/">home</a>')
        pages = self.build(files)
        notes = checks.run_all(pages, SITE + "/")["notes"]
        self.assertTrue(any("old.github.io" in n for n in notes), notes)

    def test_pages_closed_by_the_generator_are_not_an_alarm(self):
        closed = ('<!doctype html><html><head><title>{0}</title>'
                  '<meta name="robots" content="noindex"></head><body><p>x</p></body></html>')
        pages = self.build({"print.html": closed.format("Print"),
                            "search/index.html": closed.format("Search"),
                            "guide/index.html": closed.format("Guide")})
        levels = {i[1]: i[0] for i in checks.technical_issues(pages) if i[2] == "noindex"}
        self.assertEqual(levels[SITE + "/guide/"], "critical")
        self.assertEqual(levels[SITE + "/search/"], "info")
        self.assertEqual({lvl for url, lvl in levels.items() if "print" in url}, {"info"})


class Years(unittest.TestCase):
    def test_a_version_in_a_product_name_is_not_a_date(self):
        for title in ("ES2017 async functions", "SQL Server 2019 setup",
                      "Office 2016 shortcuts", "ECMAScript 2015 modules"):
            with self.subTest(title=title):
                self.assertEqual(signals._past_years(title, 2026), set())
        self.assertEqual(signals._past_years("Best plumbers 2019", 2026), {2019})


if __name__ == "__main__":
    unittest.main()
