# -*- coding: utf-8 -*-
"""
1.27: сборки генераторов, на которых check ошибался.

* Имя страницы ошибки (`404`, `500`) в глубине сборки — не всегда страница
  ошибки: `status/404/` бывает статьёй, на которую сайт ссылается.
* `200.html` Nuxt и SvelteKit, оболочка gatsby-plugin-offline и
  `_global-error.html` Next.js — служебные файлы, а не страницы.
* `/* /index.html 200` в `_redirects` — запасной вход SPA, а не редирект.
* Заглушка-редирект в sitemap называется вслух, а не только в JSON.
* Заглушка Next.js не считается пустым JS-каркасом.
* x-default на корень-редиректор по языкам — не находка.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core

SITE = "https://demo.example"
WORDS = " ".join("слово%d" % i for i in range(200))


def doc(title, links=(), head="", lang="ru", text=WORDS):
    nav = " ".join('<a href="%s">ссылка %s</a>' % (l, l) for l in links)
    return ('<!doctype html><html lang="%s"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width">'
            '<title>%s</title><meta name="description" content="Описание страницы %s '
            'для проверки, достаточно длинное, чтобы не быть коротким.">%s</head>'
            '<body><nav>%s</nav><main><h1>%s</h1><p>%s</p></main></body></html>'
            % (lang, title, title, head, nav, title, text))


def write(folder, rel, html):
    path = os.path.join(folder, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


def run_check(folder, *extra):
    out = os.path.join(os.path.dirname(folder), "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        cli.main(["check", folder, "--site", SITE, "--out", out, *extra])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh), printed.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="indexgap-127-"), "site")
        os.makedirs(self.dir)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir), True)

    def urls(self):
        pages, _ = core.load_pages(self.dir, SITE)
        return {p.url for p in pages}


class ErrorPageNames(Base):
    def test_linked_status_pages_in_depth_are_pages(self):
        codes = ["200", "404", "500", "503"]
        write(self.dir, "index.html", doc("Главная", ["/status/%s/" % c for c in codes]))
        for c in codes:
            write(self.dir, "status/%s/index.html" % c, doc("Код %s" % c, ["/"]))
        write(self.dir, "404.html", doc("Не найдено", ["/"]))
        urls = self.urls()
        for c in codes:
            self.assertIn(SITE + "/status/%s/" % c, urls)
        self.assertNotIn(SITE + "/404.html", urls)
        self.assertEqual(len(urls), 5)

    def test_unlinked_error_page_of_a_sub_build_is_skipped(self):
        write(self.dir, "index.html", doc("Главная", ["/blog/"]))
        write(self.dir, "blog/index.html", doc("Блог", ["/"]))
        write(self.dir, "blog/404.html", doc("Не найдено", ["/"]))
        write(self.dir, "en/404.html", doc("Not found", ["/"]))
        self.assertEqual(self.urls(), {SITE + "/", SITE + "/blog/"})

    def test_framework_fallbacks_are_not_pages(self):
        write(self.dir, "index.html", doc("Главная", ["/a/"]))
        write(self.dir, "a/index.html", doc("Раздел", ["/"]))
        shell = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>App</title>'
                 '</head><body><div id="app"></div><script src="/e.js"></script></body></html>')
        write(self.dir, "200.html", shell)
        write(self.dir, "offline-plugin-app-shell-fallback/index.html", shell)
        write(self.dir, "_global-error.html",
              '<!DOCTYPE html><html><head><title>500: Internal Server Error.</title>'
              '</head><body><div>500</div></body></html>')
        self.assertEqual(self.urls(), {SITE + "/", SITE + "/a/"})
        out = os.path.join(os.path.dirname(self.dir), "sm")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["sitemap", self.dir, "--site", SITE, "--out-dir", out])
        with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
            self.assertNotIn("200.html", fh.read())


class SpaFallback(Base):
    def build(self, redirects):
        write(self.dir, "index.html", doc("Главная", ["/about/"]))
        write(self.dir, "about.html", doc("О нас", ["/", "/about/"]))
        if redirects:
            write(self.dir, "_redirects", redirects)
        data, _ = run_check(self.dir)
        return [i for i in data["issues"] if i["code"] == "wrong-link-form"]

    def test_spa_fallback_keeps_wrong_link_form(self):
        self.assertTrue(self.build(""))
        self.assertTrue(self.build("/*    /index.html   200\n"))

    def test_a_real_redirect_still_covers_the_form(self):
        self.assertFalse(self.build("/about/  /about  301\n"))
        self.assertFalse(self.build("/*  /index.html  301\n"))


class StubsInSitemap(Base):
    def test_a_listed_redirect_stub_is_named(self):
        write(self.dir, "index.html", doc("Главная", ["/a/"]))
        write(self.dir, "a/index.html", doc("Раздел", ["/"]))
        write(self.dir, "old/index.html",
              '<!doctype html><title>Redirecting</title>'
              '<meta http-equiv="refresh" content="0;url=/a/">'
              '<meta name="robots" content="noindex"><body><a href="/a/">a</a></body>')
        write(self.dir, "sitemap.xml",
              '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + "".join("<url><loc>%s%s</loc></url>" % (SITE, u) for u in ("/", "/a/", "/old/"))
              + "</urlset>")
        data, printed = run_check(self.dir, "--sitemap", os.path.join(self.dir, "sitemap.xml"))
        self.assertTrue(any("заглушки-редиректы" in n and SITE + "/old/" in n
                            for n in data["notes"]))
        self.assertIn(SITE + "/old/", printed)

    def test_no_note_without_listed_stubs(self):
        write(self.dir, "index.html", doc("Главная", ["/a/"]))
        write(self.dir, "a/index.html", doc("Раздел", ["/"]))
        write(self.dir, "sitemap.xml",
              '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              "<url><loc>%s/</loc></url></urlset>" % SITE)
        data, _ = run_check(self.dir, "--sitemap", os.path.join(self.dir, "sitemap.xml"))
        self.assertFalse(any("заглушки-редиректы" in n for n in data["notes"]))


class NextRedirectIsNotShell(Base):
    def test_stub_is_not_counted_as_js_shell(self):
        write(self.dir, "index.html", doc("Главная", ["/a", "/b"]))
        write(self.dir, "a.html", doc("А", ["/", "/b"]))
        write(self.dir, "b.html", doc("Б", ["/", "/a"]))
        write(self.dir, "old.html",
              '<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Shop</title></head>'
              '<body><script>self.__next_f.push([1,"NEXT_REDIRECT;replace;/a;307;"])'
              '</script></body></html>')
        write(self.dir, "shell.html",
              '<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Shop</title></head>'
              '<body><div id="root"></div><script src="/app.js"></script></body></html>')
        data, _ = run_check(self.dir)
        shells = [i["url"] for i in data["issues"] if i["code"] == "js-shell"]
        self.assertEqual(shells, [SITE + "/shell.html"])
        note = [n for n in data["notes"] if "JS-каркасов" in n]
        self.assertTrue(note and note[0].startswith("пустых JS-каркасов: 1 "))


class XDefaultRedirector(Base):
    def build(self, xdefault):
        write(self.dir, "index.html",
              '<!DOCTYPE html><html lang="en"><head><title>%s/en/</title>'
              '<link rel="canonical" href="%s/en/"><meta name="robots" content="noindex">'
              '<meta charset="utf-8"><meta http-equiv="refresh" content="0; url=%s/en/">'
              '</head></html>' % (SITE, SITE, SITE))
        write(self.dir, "closed/index.html",
              doc("Closed", ["/en/"], head='<meta name="robots" content="noindex">', lang="en"))
        for lang in ("en", "de"):
            alt = "".join('<link rel="alternate" hreflang="%s" href="%s/%s/">' % (l, SITE, l)
                          for l in ("en", "de"))
            alt += '<link rel="alternate" hreflang="x-default" href="%s%s">' % (SITE, xdefault)
            write(self.dir, "%s/index.html" % lang,
                  doc("Home " + lang, ["/en/", "/de/"], lang=lang,
                      head='<link rel="canonical" href="%s/%s/">' % (SITE, lang) + alt))
        data, _ = run_check(self.dir)
        return [i for i in data["issues"] if i["code"] == "hreflang-target-blocked"]

    def test_x_default_to_the_language_redirector_is_fine(self):
        self.assertEqual(self.build("/"), [])

    def test_x_default_to_a_closed_page_is_still_reported(self):
        self.assertTrue(self.build("/closed/"))


if __name__ == "__main__":
    unittest.main()
