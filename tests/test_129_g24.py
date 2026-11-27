# -*- coding: utf-8 -*-
"""
1.29 (g24): раскладка файлов и скорость на больших сайтах.

* `index.html` и старый `index.htm` в одном каталоге: проверялась копия,
  а не файл, который отдаёт хост.
* `about.html` рядом с `about/index.html`: при ссылках только на `/about/`
  проверяется `about/index.html`.
* Битый симлинк и каталог с одним `index.xml` считались маршрутом и прятали
  битую ссылку; каталог-симлинк и `venv/` в готовом сайте — наоборот, 404.
* Каталог `c.html/`, NFD-имя файла, каталоги, различающиеся регистром.
* match_rows, rows_without_page, misdirected, _column_scale — без квадрата.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unicodedata
import unittest
from types import SimpleNamespace
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, content

SITE = "https://demo.example"
FILL = " ".join(["Rent deposit and commute figures differ between districts, and the "
                 "guide explains how newcomers search for viewings and contracts."] * 3)


def html(title, links="", head=""):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width">'
            f'<title>{title} guide page</title><meta name="description" '
            f'content="A guide about {title} with rent and deposit details for newcomers.">'
            f'{head}</head><body><main><h1>{title}</h1><p>{title}: {FILL}</p>{links}'
            f'</main></body></html>')


NOINDEX = '<meta name="robots" content="noindex">'


def a(*hrefs):
    return " ".join(f'<a href="{h}">{h}</a>' for h in hrefs)


class Site(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-129-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = os.path.join(self.tmp, "site")
        os.makedirs(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self):
        out = os.path.join(self.tmp, "r.json")
        with mock.patch.object(sys, "stdout", io.StringIO()), \
                mock.patch.object(sys, "stderr", io.StringIO()):
            cli.main(["check", self.dir, "--site", SITE, "--no-content", "--no-aeo",
                      "--out", out])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def issues(self, data, code):
        return [i for i in data["issues"] if i["code"] == code]

    def urls(self, data, code):
        return sorted(i["url"] for i in self.issues(data, code))

    def broken(self, data):
        return " ".join(i["message"] for i in self.issues(data, "broken-link"))


class ServedTwin(Site):
    def test_index_html_wins_over_a_stale_index_htm(self):
        self.write("index.html", html("Home", a("/a/")))
        self.write("a/index.html", html("Alpha", a("/"), head=NOINDEX))
        self.write("a/index.htm", html("Alpha old", a("/", "/zz/")))
        self.write("zz/index.html", html("Zeta", a("/")))
        data = self.check()
        self.assertIn(SITE + "/a/", self.urls(data, "noindex"))
        self.assertIn(SITE + "/zz/", data["orphans"])

    def test_the_folder_page_is_checked_when_links_use_the_folder_form(self):
        self.write("index.html", html("Home", a("/about/")))
        self.write("about.html", html("About flat", a("/", "/x/", "/y/")))
        self.write("about/index.html", html("About", a("/"), head=NOINDEX))
        self.write("x/index.html", html("Xray", a("/")))
        self.write("y/index.html", html("Yankee", a("/")))
        data = self.check()
        self.assertIn(SITE + "/about/", self.urls(data, "noindex"))

    def test_the_flat_page_is_checked_when_links_use_the_file_form(self):
        self.write("index.html", html("Home", a("/about.html")))
        self.write("about.html", html("About flat", a("/"), head=NOINDEX))
        self.write("about/index.html", html("About", a("/", "/x/")))
        self.write("x/index.html", html("Xray", a("/")))
        data = self.check()
        self.assertIn(SITE + "/about.html", self.urls(data, "noindex"))


class Routes(Site):
    def test_dangling_symlinks_are_not_routes(self):
        self.write("index.html", html("Home", a("/guide/", "/pricing/", "/faq/")))
        self.write("guide/index.html", html("Guide", a("/")))
        try:
            os.symlink(os.path.join(self.tmp, "nowhere", "pricing"),
                       os.path.join(self.dir, "pricing"))
            os.symlink("missing-faq.html", os.path.join(self.dir, "faq.html"))
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        message = self.broken(self.check())
        self.assertIn("/pricing", message)
        self.assertIn("/faq", message)

    def test_a_folder_with_only_a_feed_or_an_asset_is_not_a_route(self):
        self.write("index.html", html("Home", a("/guide/", "/pricing/", "/news/")))
        self.write("guide/index.html", html("Guide", a("/")))
        self.write("pricing/index.xml", "<rss></rss>")
        self.write("news/page.png", "png")
        message = self.broken(self.check())
        self.assertIn("/pricing", message)
        self.assertIn("/news", message)

    def test_route_files_still_make_a_route(self):
        routes, _ = checks.build_routes(self._layout())
        self.assertIn("/start", routes)
        self.assertIn("/app", routes)
        self.assertNotIn("/feed", routes)

    def _layout(self):
        self.write("start/page.js", "export default 1")
        self.write("app/index.html", html("App"))
        self.write("feed/index.json", "{}")
        return self.dir

    def test_a_symlinked_folder_is_not_a_404(self):
        self.write("index.html", html("Home", a("/rent/berlin/", "/latest/")))
        self.write("rent/berlin/index.html", html("Berlin", a("/")))
        try:
            os.symlink(os.path.join("rent", "berlin"), os.path.join(self.dir, "latest"),
                       target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.assertNotIn("/latest", self.broken(self.check()))

    def test_a_service_folder_in_a_built_site_is_named_and_not_a_404(self):
        self.write("index.html", html("Home", a("/venv/", "/.guides/a/")))
        self.write("venv/index.html", html("Venv", a("/")))
        self.write(".guides/a/index.html", html("Hidden", a("/")))
        data = self.check()
        self.assertNotIn("/venv", self.broken(data))
        note = [n for n in data["notes"] if "venv/" in n]
        self.assertEqual(len(note), 1, data["notes"])
        self.assertIn(".guides/", note[0])

    def test_a_source_repo_says_nothing_about_node_modules(self):
        self.write("package.json", "{}")
        self.write("index.html", html("Home"))
        self.write("node_modules/pkg/index.html", html("Pkg"))
        self.assertFalse([n for n in self.check()["notes"] if "node_modules" in n])


class Names(Site):
    def test_a_folder_named_like_a_file(self):
        self.write("index.html", html("Home", a("/c.html")))
        self.write("c.html/index.html", html("Charlie", a("/")))
        data = self.check()
        self.assertNotIn("/c", self.broken(data))
        self.assertEqual(data["orphans"], [])

    def test_an_nfd_file_name_linked_in_nfc(self):
        name = unicodedata.normalize("NFD", "café.html")
        self.write("index.html", html("Home", a("/caf%C3%A9.html")))
        self.write(name, html("Cafe", a("/")))
        data = self.check()
        self.assertEqual(self.issues(data, "wrong-link-form"), [])

    def test_folders_that_differ_only_in_case_get_a_note(self):
        self.write("index.html", html("Home", a("/Guide/", "/guide/")))
        self.write("Guide/index.html", html("Guide upper", a("/")))
        self.write("guide/index.html", html("Guide lower", a("/")))
        if len(os.listdir(self.dir)) < 3:
            self.skipTest("case-insensitive file system")
        notes = [n for n in self.check()["notes"] if "регистром" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("Guide/index.html", notes[0])


def page(url, title, words=None, canonical=None):
    return SimpleNamespace(url=url, title=title, headings=[], meta={}, path="/x" + url,
                           words=words or [], canonical=canonical)


class Scale(unittest.TestCase):
    def brute(self, pages, rows, min_score=0.8):
        """Прежний перебор: для каждой страницы — все ключи."""
        out, ambiguous = {}, []
        keys = sorted(r["keyword"].lower() for r in rows)
        for p in pages:
            hay = content._stems(p.title.lower())
            scored = sorted(((len(content._stems(k) & hay) / len(content._stems(k)),
                              len(content._stems(k)), k) for k in keys if content._stems(k)),
                            key=lambda t: (-t[0], -t[1], t[2]))
            if scored and scored[0][0] >= min_score:
                if len(scored) > 1 and scored[1][:2] == scored[0][:2]:
                    ambiguous.append(p.url)
                else:
                    out[p.url] = scored[0][2]
        return out, sorted(ambiguous)

    def test_title_matching_agrees_with_the_full_scan(self):
        rows = [{"keyword": k} for k in (
            "renting in alpha", "renting in beta", "renting", "deposit beta",
            "renting alpha cheap", "gamma", "delta flats", "flats in delta")]
        pages = [page(f"/p{i}/", t) for i, t in enumerate((
            "Renting in Alpha today", "Beta deposit guide", "Renting tips",
            "Gamma", "Delta flats", "Nothing here", "Renting alpha cheap rooms"))]
        got = content.match_rows(pages, rows, "keyword", "/x")
        want, ambiguous = self.brute(pages, rows)
        self.assertEqual({u: r["keyword"].lower() for u, r in got["matched"].items()}, want)
        self.assertEqual(got["ambiguous"], ambiguous)
        self.assertIn("/p4/", ambiguous)

    def test_column_scale_is_cached_and_unchanged(self):
        self.assertEqual(content._column_scale("price_k"), 1000)
        self.assertEqual(content._column_scale("price_k"), 1000)
        self.assertEqual(content._column_scale("keyword"), 1)
        self.assertGreater(content._column_scale.cache_info().hits, 0)

    def test_text_overlap_is_jaccard_for_each_target(self):
        k = checks.CONFIG["shingle_size"]
        one = page("/a/", "A", words="w1 w2 w3 w4 w5 w6 w7 w8".split())
        hub = page("/", "H", words="w1 w2 w3 w4 w5 w6 x1 x2".split())
        other = page("/b/", "B", words="w1 w2 w3 w4 w5 w6 w7 w8".split())
        for target in (hub, other, hub):
            sa = checks._shingles(one.words, k)
            sb = checks._shingles(target.words, k)
            self.assertAlmostEqual(checks._text_overlap(one, target),
                                   len(sa & sb) / len(sa | sb))


if __name__ == "__main__":
    unittest.main()
