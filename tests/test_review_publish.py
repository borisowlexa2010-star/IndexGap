# -*- coding: utf-8 -*-
"""
Публикация: находки ревью десяти агентов перед публичным запуском.

В sitemap и в очередь IndexNow попадало то, что страницей не является:
`404.html`, заглушка-редирект, черновик Hugo с `draft: true`, запись Jekyll
с `published: false`. Поисковику отправлялся адрес, по которому либо ничего
нет, либо лежит недописанное.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core, publish

SITE = "https://example.com"
TEXT = "<p>" + "слово " * 150 + "</p>"


def html(title, links=("/",)):
    anchors = "".join(f'<a href="{h}">ссылка</a>' for h in links)
    return (f"<html><head><title>{title} — страница сайта</title></head><body><main>"
            f"<h1>{title}</h1>{TEXT}{anchors}</main></body></html>")


def md(title, extra=""):
    return f"---\ntitle: {title}\n{extra}---\n\n# {title}\n\n" + "слово " * 150 + "\n"


class Fixture(unittest.TestCase):
    def pages(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-pub-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.root = root
        return core.load_pages(root, SITE)[0]

    def sitemap(self, pages):
        out = tempfile.mkdtemp(prefix="indexgap-out-")
        self.addCleanup(shutil.rmtree, out, True)
        publish.build_sitemap(pages, out, SITE, today="2026-10-01")
        text = open(os.path.join(out, "sitemap.xml"), encoding="utf-8").read()
        return sorted(u.replace(SITE, "") for u in
                      __import__("re").findall(r"<loc>([^<]+)</loc>", text))


class TestNotPages(Fixture):
    def test_error_page_404_html_is_not_a_page(self):
        pages = self.pages({
            "index.html": html("Главная", ["/a/"]),
            "a/index.html": html("Страница"),
            "404.html": html("Не найдено"),
            "500.html": html("Ошибка"),
            "_not-found.html": html("Не найдено"),
            "404/index.html": html("Не найдено"),
        })
        self.assertEqual(sorted(p.url.replace(SITE, "") for p in pages), ["/", "/a/"])
        result = checks.run_all(pages, SITE + "/")
        self.assertEqual([i for i in result["issues"] if i[2] == "orphan"], [])

    def test_a_page_about_error_404_is_still_a_page(self):
        pages = self.pages({"index.html": html("Главная", ["/blog/404-errors/"]),
                            "blog/404-errors/index.html": html("Про ошибку 404")})
        self.assertEqual(len(pages), 2)

    def test_sitemap_excludes_stubs_and_ssg_drafts(self):
        stub = ('<html><head><title>/a/</title><meta http-equiv="refresh" '
                'content="0; url=/a/"></head></html>')
        pages = self.pages({
            "index.md": md("Главная"),
            "a.md": md("Готовая"),
            "hugo-draft.md": md("Черновик Hugo", "draft: true\n"),
            "jekyll-off.md": md("Снято в Jekyll", "published: false\n"),
            "later.md": md("Отложенная", "publishDate: 2099-01-01\n"),
            "status-draft.md": md("Черновик по статусу", "status: draft\n"),
            "event.md": md("Будущее событие", "date: 2099-01-01\n"),
        })
        self.assertEqual(self.sitemap(pages), ["/", "/a/", "/event/"])
        queue = publish.diff_changed(pages, {})
        self.assertEqual(sorted(u.replace(SITE, "") for u in queue["new"]), ["/", "/a/", "/event/"])

        stubbed = self.pages({"index.html": html("Главная", ["/a/"]),
                              "a/index.html": html("Страница"), "old/index.html": stub})
        self.assertEqual(self.sitemap(stubbed), ["/", "/a/"])


if __name__ == "__main__":
    unittest.main()
