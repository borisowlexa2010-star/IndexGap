# -*- coding: utf-8 -*-
"""
1.30 (urlid): два файла с одним ключом адреса.

* `about.html` и `about/index.html`: пропущенный файл уносил свои ссылки,
  и страница, на которую ссылался только он, становилась ложной сиротой.
* `glossary/index/index.html` — настоящий каталог `index/` — сворачивался
  в `/glossary/` и пропадал как «дубль адреса».
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
from indexgap import checks, cli, core

SITE = "https://demo.example"
FILL = " ".join(["Rent deposit and commute figures differ between districts, and the "
                 "guide explains how newcomers search for viewings and contracts."] * 3)
NOINDEX = '<meta name="robots" content="noindex">'
NOFOLLOW = '<meta name="robots" content="nofollow">'


def html(title, links="", head=""):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width">'
            f'<title>{title} guide page</title><meta name="description" '
            f'content="A guide about {title} with rent and deposit details for newcomers.">'
            f'{head}</head><body><main><h1>{title}</h1><p>{title}: {FILL}</p>{links}'
            f'</main></body></html>')


def a(*hrefs):
    return " ".join(f'<a href="{h}">{h}</a>' for h in hrefs)


class Site(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-130-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = os.path.join(self.tmp, "site")
        os.makedirs(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self, *extra):
        out = os.path.join(self.tmp, "r.json")
        with mock.patch.object(sys, "stdout", io.StringIO()), \
                mock.patch.object(sys, "stderr", io.StringIO()):
            cli.main(["check", self.dir, "--site", SITE, "--no-content", "--no-aeo",
                      "--out", out, *extra])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def urls(self, data, code):
        return sorted(i["url"] for i in data["issues"] if i["code"] == code)

    def broken(self, data):
        return " ".join(i["message"] for i in data["issues"] if i["code"] == "broken-link")


class TwinLinks(Site):
    def test_links_of_the_skipped_twin_still_reach_their_pages(self):
        self.write("index.html", html("Home", a("/about/", "/about.html", "/x/")))
        self.write("about.html", html("About flat", a("/", "/x/", "/y/")))
        self.write("about/index.html", html("About", a("/", "/team/")))
        for name in ("team", "x", "y"):
            self.write(name + "/index.html", html(name.title(), a("/")))
        data = self.check()
        self.assertNotIn(SITE + "/team/", data["orphans"])
        self.assertEqual(self.urls(data, "orphan"), [])
        self.assertEqual(self.urls(data, "unreachable"), [])
        # Сайт ссылается только на `/about/`: `about.html` по ссылкам не
        # открыть, и его ссылки сироту не прячут.
        self.write("index.html", html("Home", a("/about/", "/x/")))
        self.assertIn(SITE + "/y/", self.check()["orphans"])

    def test_links_of_a_nofollow_twin_are_inbound_but_not_followed(self):
        self.write("index.html", html("Home", a("/about/", "/about.html", "/x/")))
        self.write("about.html", html("About flat", a("/", "/x/", "/y/")))
        self.write("about/index.html", html("About", a("/", "/team/"), head=NOFOLLOW))
        for name in ("team", "x", "y"):
            self.write(name + "/index.html", html(name.title(), a("/")))
        pages, _ = core.load_pages(self.dir, SITE)
        graph = checks.link_graph(pages, SITE + "/")
        self.assertNotIn(SITE + "/team/", graph["orphans"])
        self.assertIn(SITE + "/team/", graph["behind_nofollow"])

    def test_a_redirecting_twin_leads_to_its_target(self):
        self.write("index.html", html("Home", a("/about/", "/about.html", "/x/")))
        self.write("about.html", html("About flat", a("/", "/x/", "/y/")))
        self.write("about/index.html",
                   '<!doctype html><html><head><meta http-equiv="refresh" '
                   'content="0; url=/team/"><title>Moved</title></head><body></body></html>')
        for name in ("team", "x", "y"):
            self.write(name + "/index.html", html(name.title(), a("/")))
        pages, _ = core.load_pages(self.dir, SITE)
        graph = checks.link_graph(pages, SITE + "/")
        self.assertNotIn(SITE + "/team/", graph["orphans"])
        self.assertIn(SITE + "/team/", graph["depth"])


class IndexFolder(Site):
    def test_a_folder_named_index_is_its_own_page(self):
        self.write("index.html", html("Home", a("/glossary/")))
        self.write("glossary/index.html", html("Glossary", a("/", "/glossary/index/",
                                                             "/glossary/bond/")))
        self.write("glossary/bond/index.html", html("Bond", a("/glossary/")))
        self.write("glossary/index/index.html", html("Index term", a("/glossary/"),
                                                     head=NOINDEX))
        data = self.check()
        self.assertIn(SITE + "/glossary/index/", self.urls(data, "noindex"))
        self.assertNotIn(SITE + "/glossary/index/", data["orphans"])
        self.assertNotIn(SITE + "/glossary/", self.urls(data, "noindex"))

    def test_the_bare_form_still_means_the_parent(self):
        self.write("index.html", html("Home", a("/terms/", "/terms/index")))
        self.write("terms/index.html", html("Terms", a("/", "/terms/index/")))
        self.write("terms/index/index.html", html("Index term", a("/terms/")))
        pages, problems = core.load_pages(self.dir, SITE)
        self.assertEqual(sorted(p.url for p in pages),
                         [SITE + "/", SITE + "/terms/", SITE + "/terms/index/"])
        self.assertFalse([p for p in problems if "terms" in p])
        by_key = {p.key: p.url for p in pages}
        self.assertEqual(by_key[core.url_key(SITE + "/terms/index")], SITE + "/terms/")
        self.assertEqual(by_key[core.url_key(SITE + "/terms/index/")], SITE + "/terms/index/")
        self.assertEqual(by_key[core.url_key(SITE + "/terms/index/index.html")],
                         SITE + "/terms/index/")

    def test_without_a_parent_page_the_bare_form_reaches_the_folder(self):
        self.write("index.html", html("Home", a("/words/index")))
        self.write("words/index/index.html", html("Index word", a("/")))
        data = self.check()
        self.assertNotIn("/words/index", self.broken(data))
        self.assertNotIn(SITE + "/words/index/", data["orphans"])
        # Ключ страницы — её собственный: `/words/` в сборке нет.
        pages, _ = core.load_pages(self.dir, SITE)
        word = [p for p in pages if p.url == SITE + "/words/index/"][0]
        self.assertEqual(word.key, core.url_key(SITE + "/words/index"))
        self.assertNotEqual(word.key, core.url_key(SITE + "/words/"))

    def test_parallel_parsing_sees_the_folder(self):
        self.write("index.html", html("Home", a("/notes/")))
        self.write("notes/index.html", html("Notes", a("/", "/notes/index/")))
        self.write("notes/index/index.html", html("Index note", a("/notes/")))
        with mock.patch.object(core, "PARALLEL_FROM", 1):
            pages, _ = core.load_pages(self.dir, SITE, jobs=2)
        graph = checks.link_graph(pages, SITE + "/")
        self.assertIn(SITE + "/notes/index/", graph["inbound"])
        self.assertEqual(graph["inbound"][SITE + "/notes/index/"], [SITE + "/notes/"])


if __name__ == "__main__":
    unittest.main()
