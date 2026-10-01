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


class TestRedirectStubs(Fixture):
    """
    Заглушка-редирект не проверяется как страница — значит, признать заглушкой
    настоящую страницу нельзя: все её находки молча пропадут.
    """

    def stub_urls(self, files):
        pages, _ = self.site(files)
        return sorted(p.url.replace(SITE, "") for p in pages if checks.redirect_target(p))

    def test_noscript_or_delayed_refresh_and_quoted_digest_are_not_stubs(self):
        noscript = '<noscript><meta http-equiv="refresh" content="0; url=/nojs/"></noscript>'
        self.assertEqual(self.stub_urls({
            "index.html": html("Главная", ["a/", "b/", "c/", "d/"], head=noscript),
            "a/index.html": html("Автообновление", ["../"],
                                 head='<meta http-equiv="refresh" content="300; url=/a/">'),
            "b/index.html": html("Про Next.js", ["../"]).replace(
                "</main>", "<code>NEXT_REDIRECT;replace;/login;307;</code></main>"),
            "c/index.html": html("Закомментировано", ["../"],
                                 head='<!-- <meta http-equiv="refresh" content="0; url=/old/"> -->'),
            "d/index.html": html("Пример в тексте", ["../"]).replace(
                "</main>", '<pre>&lt;meta http-equiv="refresh" content="0; url=/x/"&gt;</pre></main>'),
        }), [])

    def test_a_markdown_page_showing_a_redirect_is_not_a_stub(self):
        md = ("---\ntitle: Как сделать редирект\n---\n\n# Редирект\n\n" + "слово " * 150
              + '\n\n```html\n<meta http-equiv="refresh" content="0; url=/new/">\n```\n')
        self.assertEqual(self.stub_urls({"index.md": md}), [])

    def test_real_stubs_are_still_stubs(self):
        next_stub = ('<!doctype html><html><head><title>x</title></head><body>'
                     '<script>self.__next_f.push([1,"NEXT_REDIRECT;replace;/en;307;"])</script>'
                     "</body></html>")
        alias = ('<!doctype html><html><head><title>/new/</title>'
                 '<link rel="canonical" href="/new/">'
                 '<meta http-equiv="refresh" content="0; url=/new/"></head></html>')
        self.assertEqual(self.stub_urls({
            "index.html": next_stub,
            "old/index.html": alias,
            "en/index.html": html("Главная", ["/new/"]),
            "new/index.html": html("Новая", ["/en/"]),
        }), ["/", "/old/"])


class TestUrlIdentity(Fixture):
    def test_query_idn_and_default_port_links_resolve(self):
        """`/a/?utm_source=nav` — ссылка на `/a/`: метка в адресе страницу не меняет."""
        _, result = self.site({
            "index.html": html("Главная", ["/a/?utm_source=nav", "/b/?ref=home#top",
                                           "https://example.com:443/c/"]),
            "a/index.html": html("А", ["/"]),
            "b/index.html": html("Б", ["/"]),
            "c/index.html": html("В", ["/"]),
        })
        self.assertEqual(self.codes(result, "orphan", "unreachable"), [])

    def test_idn_host_and_its_punycode_are_one_site(self):
        root = tempfile.mkdtemp(prefix="indexgap-idn-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in {
                "index.html": html("Главная", ["https://xn--e1afmkfd.xn--p1ai/a/"]),
                "a/index.html": html("А", ["https://пример.рф/"])}.items():
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        pages = core.load_pages(root, "https://пример.рф")[0]
        result = checks.run_all(pages, "https://пример.рф/")
        self.assertEqual([i[2] for i in result["issues"] if i[2] in ("orphan", "unreachable")], [])

    def test_links_through_redirect_stub_reach_target(self):
        """Алиасы Hugo: страница-заглушка без единой <a>, но с переадресацией."""
        def alias(to):
            return (f'<html><head><title>{to}</title><meta http-equiv="refresh" '
                    f'content="0; url={to}"></head></html>')
        _, result = self.site({
            "index.html": html("Главная", ["/old-docs/"]),
            "old-docs/index.html": alias("/docs/"),
            "docs/index.html": alias("/docs/intro/"),
            "docs/intro/index.html": html("Введение", ["/docs/more/"]),
            "docs/more/index.html": html("Дальше", ["/"]),
        })
        self.assertEqual(self.codes(result, "orphan", "unreachable"), [])


class TestOneOrphanList(Fixture):
    def test_orphan_count_is_the_same_everywhere(self):
        closed = html("Закрытая").replace("<head>", '<head><meta name="robots" content="none">')
        stub = ('<html><head><title>x</title><meta http-equiv="refresh" '
                'content="0; url=/a/"></head></html>')
        _, result = self.site({
            "index.html": html("Главная", ["/a/"]),
            "a/index.html": html("А", ["/"]),
            "closed/index.html": closed,
            "old/index.html": stub,
            "lost/index.html": html("Потерянная", ["/"]),
        })
        found = [i[1].replace(SITE, "") for i in result["issues"] if i[2] == "orphan"]
        self.assertEqual(found, ["/lost/"])
        self.assertEqual([u.replace(SITE, "") for u in result["graph"]["orphans"]], found)


if __name__ == "__main__":
    unittest.main()
