# -*- coding: utf-8 -*-
"""
1.27: граф ссылок.

* Блок «рядом» со всеми соседями на каждой странице раздела с шести детей
  прятал хаб, который не ссылается ни на одного.
* `X-Robots-Tag: nofollow` (и `none`) из `_headers` не останавливал обход.
* `/b/index.md`, `/c.htm` при `c.html`, `/d/INDEX.HTML` молча сводились к
  странице, а ссылка на `alpha/index.html` в виде `alpha.md` печаталась как
  `alpha.html`.
* meta refresh без кавычек (`content=0;url=/en/`) не узнавался.
* Ссылки `rel="nofollow"` выбрасывались при разборе: битая не находилась, а
  страница только с такими входящими называлась сиротой.
* Ссылки в раздел, которого в сборке нет вовсе, молчали.
* Заглушка-редирект посреди пути считалась кликом.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli

SITE = "https://demo.example"
FILL = " ".join(["Rent deposit and commute figures differ between districts, and the "
                 "guide explains how newcomers search for viewings and contracts."] * 3)


def html(title, links="", head="", body=""):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width">'
            f'<title>{title} guide page</title><meta name="description" '
            f'content="A guide about {title} with rent and deposit details for newcomers.">'
            f'{head}</head><body><main><h1>{title}</h1><p>{title}: {FILL}</p>{body}{links}'
            f'</main></body></html>')


class Site(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="indexgap-127-"), "site")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir), True)
        os.makedirs(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self):
        out = os.path.join(os.path.dirname(self.dir), "r.json")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", self.dir, "--site", SITE, "--no-content", "--no-aeo",
                      "--out", out])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def issues(self, data, code):
        return [i for i in data["issues"] if i["code"] == code]

    def urls(self, data, code):
        return sorted(i["url"] for i in self.issues(data, code))


class NearbyBlockAndHub(Site):
    def build(self, n, toc=False):
        cities = [f"city{i}" for i in range(n)]
        near = "".join(f'<a href="/rent/{c}/">{c}</a> ' for c in cities)
        self.write("index.html", html("Home", '<a href="/rent/">rent</a> '
                                              '<a href="/rent/city0/">featured</a>'))
        hub_links = '<a href="/rent/contents/">contents</a>' if toc else ""
        self.write("rent/index.html", html("Rent hub", hub_links))
        for c in cities:
            self.write(f"rent/{c}/index.html",
                       html("City " + c, '<a href="/rent/">hub</a> ' + ("" if toc else near)))
        if toc:
            self.write("rent/contents/index.html", html("Contents", near))

    def test_a_nearby_block_on_every_kid_does_not_hide_the_hub(self):
        for n in (5, 6, 20):
            with self.subTest(n=n):
                shutil.rmtree(self.dir)
                os.makedirs(self.dir)
                self.build(n)
                found = self.issues(self.check(), "hub-missing-links")
                self.assertEqual([i["url"] for i in found], [SITE + "/rent/"])
                self.assertIn(f"{n} из {n}", found[0]["message"])

    def test_a_single_contents_page_in_the_section_still_counts(self):
        self.build(6, toc=True)
        self.assertEqual(self.issues(self.check(), "hub-missing-links"), [])


class HeaderNofollow(Site):
    def build(self, header):
        self.write("index.html", html("Home", '<a href="/rent/">rent</a>'))
        self.write("rent/index.html", html("Rent hub", '<a href="/rent/alpha/">a</a> '
                                                       '<a href="/rent/beta/">b</a>'))
        self.write("rent/alpha/index.html", html("Alpha city", '<a href="/">home</a>'))
        self.write("rent/beta/index.html", html("Beta city", '<a href="/">home</a>'))
        self.write("_headers", f"/rent/\n  X-Robots-Tag: {header}\n")

    def test_a_nofollow_header_stops_the_crawl(self):
        for header in ("nofollow", "none", "googlebot: nofollow"):
            with self.subTest(header=header):
                self.build(header)
                self.assertEqual(self.urls(self.check(), "unreachable"),
                                 [SITE + "/rent/alpha/", SITE + "/rent/beta/"])

    def test_another_bot_or_a_noindex_header_keeps_the_links(self):
        for header in ("bingbot: nofollow", "noindex"):
            with self.subTest(header=header):
                self.build(header)
                self.assertEqual(self.urls(self.check(), "unreachable"), [])


class ExactFileNames(Site):
    def test_forms_the_host_does_not_serve_are_flagged_as_written(self):
        self.write("index.html", html("Home", (
            '<a href="/rent/alpha.md">a</a> <a href="/rent/beta/index.md">b</a> '
            '<a href="/rent/gamma.htm">c</a> <a href="/rent/delta/INDEX.HTML">d</a> '
            '<a href="/rent/zeta/index.html">z</a> <a href="/rent/eta.html">e</a>')))
        self.write("rent/alpha/index.html", html("Alpha city", '<a href="/">home</a>'))
        self.write("rent/beta/index.html", html("Beta city", '<a href="/">home</a>'))
        self.write("rent/gamma.html", html("Gamma city", '<a href="/">home</a>'))
        self.write("rent/delta/index.html", html("Delta city", '<a href="/">home</a>'))
        self.write("rent/zeta/index.html", html("Zeta city", '<a href="/">home</a>'))
        self.write("rent/eta.html", html("Eta city", '<a href="/">home</a>'))
        found = self.issues(self.check(), "wrong-link-form")
        self.assertEqual(len(found), 1)
        message = found[0]["message"]
        for written in ("/rent/alpha.md вместо", "/rent/beta/index.md вместо",
                        "/rent/delta/INDEX.HTML вместо"):
            self.assertIn(written, message)
        self.assertIn("и ещё 1", message)          # gamma.htm — четвёртая
        self.assertNotIn("alpha.html", message)
        self.assertNotIn("zeta", message)
        self.assertNotIn("eta.html вместо", message)

    def test_wrong_forms_are_listed_for_the_page(self):
        self.write("index.html", html("Home", '<a href="/rent/gamma.htm">c</a>'))
        self.write("rent/gamma.html", html("Gamma city", '<a href="/">home</a>'))
        found = self.issues(self.check(), "wrong-link-form")
        self.assertEqual(len(found), 1)
        self.assertIn("/rent/gamma.htm вместо /rent/gamma.html", found[0]["message"])


class UnquotedRefresh(Site):
    def test_a_minified_refresh_is_a_redirect(self):
        for tag in ('<meta http-equiv=refresh content=0;url=/en/>',
                    '<meta content=0;url=/en/ http-equiv=refresh>'):
            with self.subTest(tag=tag):
                stub = SimpleNamespace(url=SITE + "/", path="index.html",
                                       raw=f"<html><head>{tag}</head></html>", text="")
                self.assertEqual(checks.redirect_target(stub), SITE + "/en/")

    def test_another_attribute_named_like_content_is_not_read(self):
        stub = SimpleNamespace(url=SITE + "/", path="index.html", text="",
                               raw='<meta http-equiv=refresh data-content=0;url=/en/>')
        self.assertEqual(checks.redirect_target(stub), "")

    def test_the_site_behind_a_minified_home_stub_is_reachable(self):
        self.write("index.html", '<!doctype html><html><head><meta http-equiv=refresh '
                                 'content=0;url=/en/><title>Choose</title></head><body></body></html>')
        self.write("en/index.html", html("English home", '<a href="/en/rent/a/">a</a> '
                                                         '<a href="/en/rent/b/">b</a>'))
        self.write("en/rent/a/index.html", html("Alpha city", '<a href="/en/">home</a>'))
        self.write("en/rent/b/index.html", html("Beta city", '<a href="/en/">home</a>'))
        data = self.check()
        self.assertEqual(self.issues(data, "unreachable"), [])
        self.assertTrue(any("заглушка-редирект" in n for n in data["notes"]))


class RelNofollow(Site):
    def build(self):
        self.write("index.html", html("Home", (
            '<a href="/rent/a/">a</a> <a href="/rent/b/">b</a> '
            '<a rel="NoFollow" href="/rent/d/">d</a> <a rel="nofollow" href="/login/">in</a>')))
        self.write("rent/a/index.html", html("Alpha", '<a href="/">h</a>'))
        self.write("rent/b/index.html", html(
            "Beta", '<a href="/">h</a> <a rel="nofollow" href="/rent/missing/">x</a>'))
        self.write("rent/d/index.html", html("Delta", '<a href="/">h</a>'))

    def test_a_broken_nofollow_link_in_a_section_is_reported(self):
        self.build()
        found = self.issues(self.check(), "broken-link")
        self.assertEqual([i["url"] for i in found], [SITE + "/rent/b/"])
        self.assertIn("/rent/missing", found[0]["message"])

    def test_a_page_linked_only_with_nofollow_is_unreachable_not_an_orphan(self):
        self.build()
        data = self.check()
        self.assertNotIn(SITE + "/rent/d/", self.urls(data, "orphan"))
        found = [i for i in self.issues(data, "unreachable") if i["url"] == SITE + "/rent/d/"]
        self.assertEqual(len(found), 1)
        self.assertIn('rel="nofollow"', found[0]["message"])


class MissingSection(Site):
    def build(self, n):
        links = "".join(f'<a href="/rent/city{i}/">c{i}</a> ' for i in range(n))
        self.write("index.html", html("Home", links + '<a href="/about/">about</a>'))
        self.write("about/index.html", html("About", '<a href="/">home</a>'))

    def test_many_links_into_a_missing_section_get_a_note(self):
        self.build(12)
        data = self.check()
        notes = [n for n in data["notes"] if "/rent/" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("12", notes[0])
        self.assertEqual(self.issues(data, "broken-link"), [])

    def test_a_few_links_elsewhere_stay_quiet(self):
        self.build(3)
        self.assertFalse([n for n in self.check()["notes"] if "/rent/" in n])


class StubMidPath(Site):
    def test_a_redirect_stub_is_not_a_click(self):
        self.write("index.html", html("Home", '<a href="/go/">go</a>'))
        self.write("go/index.html", '<!doctype html><html><head><meta http-equiv="refresh" '
                                    'content="0; url=/rent/"><title>Moved</title></head>'
                                    '<body></body></html>')
        self.write("rent/index.html", html("Rent hub", '<a href="/rent/a/">a</a>'))
        self.write("rent/a/index.html", html("Alpha city", '<a href="/rent/a/b/">b</a>'))
        self.write("rent/a/b/index.html", html("Beta district", '<a href="/">home</a>'))
        self.write("rent/a/b/c/index.html", html("Gamma corner", '<a href="/">home</a>'))
        self.write("rent/a/b/index.html", html("Beta district", '<a href="/rent/a/b/c/">c</a>'))
        data = self.check()
        # /go/ → /rent/ бесплатно: /rent/a/b/ — три клика, /rent/a/b/c/ — четыре.
        self.assertEqual(self.urls(data, "deep"), [SITE + "/rent/a/b/c/"])


if __name__ == "__main__":
    unittest.main()
