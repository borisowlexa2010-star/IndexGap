# -*- coding: utf-8 -*-
"""
1.28: canonical на саму страницу в форме, которой раскладка файлов не отдаёт.

`about.html` с canonical `/about/` и `a/index.html` с canonical `/a.html` —
это 404 на GitHub Pages, S3 и nginx, `a/index.html` с canonical `/a` —
редирект на `/a/`. Свой адрес страница по-прежнему берёт из canonical (он
уходит в sitemap, ссылки в той же форме не отмечаются), но теперь об этом
говорит находка `canonical-form`. Хостинг, который форму сводит сам
(vercel.json, правило перенаправления, firebase.json, сервер Next.js), её
глушит.
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


def doc(title, links=(), canonical=None, head=""):
    nav = " ".join('<a href="%s">ссылка %s</a>' % (l, l) for l in links)
    if canonical is not None:
        head += '<link rel="canonical" href="%s">' % canonical
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width">'
            '<title>%s</title><meta name="description" content="Описание страницы %s '
            'для проверки, достаточно длинное, чтобы не быть коротким.">%s</head>'
            '<body><nav>%s</nav><main><h1>%s</h1><p>%s</p></main></body></html>'
            % (title, title, head, nav, title, WORDS))


def write(folder, rel, text):
    path = os.path.join(folder, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Base(unittest.TestCase):
    site = SITE

    def setUp(self):
        self.top = tempfile.mkdtemp(prefix="indexgap-128-")
        self.dir = os.path.join(self.top, "site")
        os.makedirs(self.dir)
        self.addCleanup(shutil.rmtree, self.top, True)

    def check(self, folder=None):
        folder = folder or self.dir
        out = os.path.join(self.top, "r.json")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", folder, "--site", self.site, "--out", out])
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        return data["issues"]

    def found(self, folder=None):
        return sorted(i["url"] for i in self.check(folder) if i["code"] == "canonical-form")

    def codes(self, folder=None):
        return {i["code"] for i in self.check(folder)}

    def flat(self, form, folder=None):
        """about.html и pricing.html с canonical и ссылками в форме `form`."""
        folder = folder or self.dir
        links = ["/about" + form, "/pricing" + form]
        write(folder, "index.html", doc("Главная", links, SITE + "/"))
        for name in ("about", "pricing"):
            write(folder, name + ".html",
                  doc(name, ["/"] + links, SITE + "/" + name + form))

    def folder(self, form, folder=None):
        """a/index.html и b/index.html с canonical и ссылками в форме `form`."""
        folder = folder or self.dir
        links = ["/a" + form, "/b" + form]
        write(folder, "index.html", doc("Главная", links, SITE + "/"))
        for name in ("a", "b"):
            write(folder, name + "/index.html",
                  doc(name, ["/"] + links, SITE + "/" + name + form))


class Reported(Base):
    def test_flat_file_with_slash_canonical(self):
        self.flat("/")
        issues = self.check()
        found = [i for i in issues if i["code"] == "canonical-form"]
        self.assertEqual(sorted(i["url"] for i in found),
                         [SITE + "/about/", SITE + "/pricing/"])
        self.assertIn("/about.html", found[0]["message"] + found[1]["message"])
        self.assertIn("404", found[0]["message"])
        # Ссылки в той же форме, что и canonical, — одна находка, а не две.
        self.assertNotIn("wrong-link-form", {i["code"] for i in issues})

    def test_adoption_is_kept(self):
        # Адрес страницы — по-прежнему её canonical: sitemap и hreflang
        # с ним согласны.
        self.flat("/")
        pages, _ = core.load_pages(self.dir, SITE)
        self.assertIn(SITE + "/about/", {p.url for p in pages})

    def test_flat_file_with_index_canonical(self):
        write(self.dir, "index.html", doc("Главная", ["/about.html"], SITE + "/"))
        write(self.dir, "about.html", doc("about", ["/"], SITE + "/about/index.html"))
        self.assertEqual(self.found(), [SITE + "/about/index.html"])

    def test_folder_page_with_bare_canonical_is_a_redirect(self):
        self.folder("")
        issues = [i for i in self.check() if i["code"] == "canonical-form"]
        self.assertEqual(sorted(i["url"] for i in issues), [SITE + "/a", SITE + "/b"])
        self.assertIn("/a/", issues[0]["message"])
        self.assertIn("редирект", issues[0]["message"])

    def test_folder_page_with_file_canonical(self):
        write(self.dir, "index.html", doc("Главная", ["/a/"], SITE + "/"))
        write(self.dir, "a/index.html", doc("a", ["/"], SITE + "/a.html"))
        self.assertEqual(self.found(), [SITE + "/a.html"])

    def test_empty_vercel_json_keeps_the_flat_case(self):
        # Vercel без настроек отдаёт `a/index.html` и по /a, но `about.html`
        # по /about/ — нет.
        self.flat("/")
        write(self.dir, "vercel.json", "{}")
        self.assertEqual(len(self.found()), 2)


class Quiet(Base):
    def test_flat_file_in_its_own_forms(self):
        for form in (".html", ""):
            with self.subTest(form=form):
                shutil.rmtree(self.dir)
                self.flat(form)
                self.assertEqual(self.found(), [])

    def test_folder_page_with_slash_or_index_canonical(self):
        self.folder("/")
        self.assertEqual(self.found(), [])
        write(self.dir, "c/index.html", doc("c", ["/"], SITE + "/c/index.html"))
        self.assertEqual(self.found(), [])

    def test_home_page(self):
        write(self.dir, "index.html", doc("Главная", ["/about/"], SITE))
        write(self.dir, "about/index.html", doc("about", ["/"], SITE + "/about/"))
        self.assertEqual(self.found(), [])

    def test_vercel_rewrites_forms(self):
        for config in ('{"trailingSlash": true}', '{"cleanUrls": true}'):
            with self.subTest(config=config):
                shutil.rmtree(self.dir)
                self.flat("/")
                write(self.dir, "vercel.json", config)
                self.assertEqual(self.found(), [])

    def test_vercel_or_azure_serve_folder_without_slash(self):
        for name in ("vercel.json", "staticwebapp.config.json"):
            with self.subTest(name=name):
                shutil.rmtree(self.dir)
                self.folder("")
                write(self.dir, name, "{}")
                self.assertEqual(self.found(), [])

    def test_vercel_json_beside_the_build(self):
        self.folder("")
        write(self.top, "vercel.json", "{}")
        self.assertEqual(self.found(), [])

    def test_redirect_rule_catches_the_address(self):
        self.flat("/")
        write(self.dir, "_redirects", "/about/ /about.html 200\n/pricing/ /pricing.html 200\n")
        self.assertEqual(self.found(), [])

    def test_netlify_toml_rule(self):
        self.folder("")
        write(self.top, "netlify.toml",
              '[[redirects]]\nfrom = "/*"\nto = "/:splat/"\nstatus = 301\n')
        self.assertEqual(self.found(), [])

    def test_firebase_clean_urls(self):
        for hosting in ('{"hosting": {"public": "site", "trailingSlash": true}}',
                        '{"hosting": [{"site": "x", "cleanUrls": true}]}'):
            with self.subTest(hosting=hosting):
                shutil.rmtree(self.dir)
                self.flat("/")
                write(self.top, "firebase.json", hosting)
                self.assertEqual(self.found(), [])

    def test_app_server_build(self):
        # `.next/server/app` отдаёт сервер Next.js по своим маршрутам:
        # `about.html` выходит по /about/ при `trailingSlash: true`.
        app = os.path.join(self.top, "proj", ".next", "server", "app")
        self.flat("/", app)
        write(app, "about.rsc", "0:[]")
        self.assertEqual(self.found(app), [])

    def test_routes_manifest_marks_app_server(self):
        app = os.path.join(self.top, "build", "server", "app")
        self.flat("/", app)
        write(os.path.join(self.top, "build"), "routes-manifest.json", "{}")
        self.assertEqual(self.found(app), [])

    def test_source_folder(self):
        # Исходники Jekyll: `about.html` с `permalink: /about/` выйдет папкой.
        self.flat("/")
        write(self.dir, "_config.yml", "permalink: pretty\n")
        self.assertEqual(self.found(), [])

    def test_noindex_page(self):
        write(self.dir, "index.html", doc("Главная", ["/about/"], SITE + "/"))
        write(self.dir, "about.html", doc("about", ["/"], SITE + "/about/",
                                          '<meta name="robots" content="noindex">'))
        self.assertEqual(self.found(), [])

    def test_canonical_to_another_page_is_not_this_finding(self):
        write(self.dir, "index.html", doc("Главная", ["/about.html", "/team.html"], SITE + "/"))
        write(self.dir, "about.html", doc("about", ["/"], SITE + "/team/"))
        write(self.dir, "team.html", doc("team", ["/"], SITE + "/team.html"))
        self.assertEqual(self.found(), [])


class BasePath(Base):
    site = SITE + "/docs"

    def test_project_site_in_folder_form(self):
        root = SITE + "/docs"
        write(self.dir, "index.html", doc("Главная", ["/docs/a/"], root + "/"))
        write(self.dir, "a/index.html", doc("a", ["/docs/"], root + "/a/"))
        self.assertEqual(self.found(), [])

    def test_project_site_with_slash_on_flat_file(self):
        root = SITE + "/docs"
        write(self.dir, "index.html", doc("Главная", ["/docs/a/"], root + "/"))
        write(self.dir, "a.html", doc("a", ["/docs/"], root + "/a/"))
        self.assertEqual(self.found(), [root + "/a/"])


class English(Base):
    def test_messages_are_translated(self):
        from indexgap import i18n
        self.addCleanup(i18n.set_lang, "ru")
        self.flat("/")
        write(self.dir, "c/index.html", doc("c", ["/"], SITE + "/c"))
        with mock.patch.dict(os.environ, {"INDEXGAP_LANG": "en"}):
            i18n.set_lang("en")
            found = [i["message"] for i in self.check() if i["code"] == "canonical-form"]
        self.assertEqual(len(found), 3)
        for message in found:
            self.assertIn("the canonical declares", message)
            self.assertNotRegex(message, "[а-яА-Я]")


if __name__ == "__main__":
    unittest.main()
