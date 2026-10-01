# -*- coding: utf-8 -*-
"""
Ссылки и адреса: находки ревью десяти агентов перед публичным запуском.

Страница `about.html` получает адрес `/about/` — так её удобно сравнивать. Но
ссылки с неё разрешались от этого же красивого адреса, а не от места, где файл
лежит: `contact.html` превращался в `/about/contact.html`, которого нет. Сайт
из плоских файлов — Sphinx, mdBook, MkDocs, рукописный — получал сирот на
каждой странице, на которую вели только относительные ссылки, и «canonical на
другую страницу» там, где canonical указывал на себя.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

SITE = "https://example.com"
TEXT = "<p>" + "слово " * 150 + "</p>"


def html(title, links=(), head=""):
    anchors = "".join(f'<a href="{href}">ссылка {i}</a>' for i, href in enumerate(links))
    return (f"<html><head><title>{title} — страница сайта</title>{head}</head>"
            f"<body><main><h1>{title}</h1>{TEXT}{anchors}</main></body></html>")


class Fixture(unittest.TestCase):
    def site(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-links-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        pages = core.load_pages(root, SITE)[0]
        return pages, checks.run_all(pages, SITE + "/")

    def codes(self, result, *wanted):
        return sorted((i[1].replace(SITE, ""), i[2]) for i in result["issues"] if i[2] in wanted)


class TestRelativeLinks(Fixture):
    def test_relative_link_from_flat_file_resolves_against_its_directory(self):
        _, result = self.site({
            "index.html": html("Главная", ["about.html", "docs/a.html"]),
            "about.html": html("О нас", ["contact.html", "./team.html"]),
            "contact.html": html("Контакты", ["index.html"]),
            "team.html": html("Команда", ["index.html"]),
            "docs/a.html": html("Документ А", ["../index.html", "b.html"]),
            "docs/b.html": html("Документ Б", ["a.html"]),
        })
        self.assertEqual(self.codes(result, "orphan", "unreachable"), [])

    def test_relative_canonical_from_flat_file_is_its_own(self):
        _, result = self.site({
            "index.html": html("Главная", ["guide/intro.html"]),
            "guide/intro.html": html("Введение", ["../index.html"],
                                     head='<link rel="canonical" href="intro.html">'),
        })
        self.assertEqual(self.codes(result, "canonical-elsewhere"), [])

    def test_directory_pages_are_unchanged(self):
        pages, result = self.site({
            "index.html": html("Главная", ["guide/"]),
            "guide/index.html": html("Гид", ["setup/", "../"]),
            "guide/setup/index.html": html("Установка", ["../"]),
        })
        self.assertEqual(self.codes(result, "orphan", "unreachable"), [])

    def test_markdown_sibling_links_resolve_from_the_file(self):
        """MkDocs, Docusaurus и GitHub пишут ссылку на соседний файл: `[b](b.md)`."""
        md = "---\ntitle: {0}\n---\n\n# {0}\n\n" + "слово " * 150 + "\n\n{1}\n"
        _, result = self.site({
            "index.md": md.format("Главная", "[a](docs/a.md)"),
            "docs/a.md": md.format("Документ А", "[b](b.md) и [домой](../index.md)"),
            "docs/b.md": md.format("Документ Б", "[a](a.md)"),
        })
        self.assertEqual(self.codes(result, "orphan", "unreachable"), [])

    def test_markdown_pretty_links_resolve_from_the_rendered_address(self):
        """Hugo и Jekyll: ссылка написана от адреса, по которому страница выйдет."""
        md = "---\ntitle: {0}\n---\n\n# {0}\n\n" + "слово " * 150 + "\n\n{1}\n"
        _, result = self.site({
            "index.md": md.format("Главная", "[a](posts/a/)"),
            "posts/a.md": md.format("Пост А", "[b](../b/)"),
            "posts/b.md": md.format("Пост Б", "[a](../a/)"),
        })
        self.assertEqual(self.codes(result, "orphan", "unreachable"), [])


if __name__ == "__main__":
    unittest.main()
