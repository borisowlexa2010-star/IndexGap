# -*- coding: utf-8 -*-
"""
1.29 (g16): `indexgap diff` — куда на самом деле ведут редиректы удалённых
и закрытых страниц, и чьи находки уносит редирект.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import cli, diff

SITE = "https://demo.example"
CITIES = 8


def page(title, words=120, head="", section="rent"):
    body = " ".join(f"word{i} text" for i in range(words))
    links = "".join(f'<a href="/{section}/c{i}/">City {i}</a> ' for i in range(CITIES))
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            f'<meta name="description" content="Rent things in the city, prices and tips for '
            f'{title}">{head}</head><body><main><h1>{title}</h1><p>{body}</p>'
            f'<a href="/">Home</a> {links}</main></body></html>')


class Build:
    def __init__(self, root):
        self.root = root
        self.write("index.html", page("Rent home"))
        for i in range(CITIES):
            self.write(f"rent/c{i}/index.html", page(f"Rent in city {i}"))

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def remove(self, name):
        shutil.rmtree(os.path.join(self.root, name))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-129g16-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old = Build(os.path.join(self.dir, "old"))
        self.new = Build(os.path.join(self.dir, "new"))
        self.out = os.path.join(self.dir, "d.html")

    def run_diff(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["diff", self.old.root, self.new.root, "--site", SITE,
                             "--out", self.out, *extra])
        with open(os.path.join(self.dir, "d.json"), encoding="utf-8") as fh:
            return code, json.load(fh)

    def level(self, data, url, code=None):
        got = [i["level"] for i in data["items"]
               if i["url"] == url and (code is None or i["code"] == code)]
        return got[0] if got else None


class MergedIntoExisting(Base):
    """#245, #254: удалённая страница, слитая в существующую, не прячет её новые находки."""

    def test_new_no_title_on_merge_target_is_reported(self):
        self.old.write("rent/c0/index.html", page(""))
        self.new.remove("rent/c0")
        self.new.write("rent/c1/index.html", page(""))
        self.new.write("_redirects", "/rent/c0/ /rent/c1/ 301\n")
        code, data = self.run_diff("--strict")
        self.assertEqual(code, 1)
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "new-finding"), "critical")

    def test_section_move_still_carries_old_findings(self):
        old = [{"level": "critical", "url": SITE + "/rent/c0/", "code": "no-title",
                "message": "x"}]
        result = {"removed": [{"url": SITE + "/rent/c0/", "redirect_to": SITE + "/flat/c0/"}],
                  "added": {"urls": [SITE + "/flat/c0/"]}}

        class P:
            key = "//demo.example/flat/c0"
            url = SITE + "/flat/c0/"
        moved = diff.moved_findings(old, result, [P()])
        self.assertEqual(moved[0]["url"], SITE + "/flat/c0/")
        result["added"]["urls"] = []
        self.assertEqual(diff.moved_findings(old, result, [P()])[0]["url"], SITE + "/rent/c0/")


class DeadEndTargets(Base):
    """#246, #252, #256: цель — закрытая страница, заглушка в пустоту, цепочка, петля."""

    def test_redirect_to_noindex_page_is_a_warning(self):
        self.new.remove("rent/c0")
        self.new.write("rent/c1/index.html",
                       page("Rent in city 1", head='<meta name="robots" content="noindex">'))
        self.new.write("_redirects", "/rent/c0/ /rent/c1/ 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c0/", "page-redirected"), "warning")

    def test_redirect_to_stub_leading_nowhere_is_a_warning(self):
        self.new.remove("rent/c0")
        self.new.write("stub/index.html", '<html><head><meta http-equiv="refresh" '
                       'content="0; url=/nowhere/"></head><body></body></html>')
        self.new.write("_redirects", "/rent/c0/ /stub/ 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c0/", "page-redirected"), "warning")

    def test_resolvable_chain_is_info_and_loop_is_warning(self):
        self.new.remove("rent/c0")
        self.new.remove("rent/c1")
        self.new.write("_redirects", "/rent/c0/ /rent/c1/ 301\n/rent/c1/ /rent/c2/ 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c0/", "page-redirected"), "info")
        self.new.write("_redirects", "/rent/c0/ /rent/c1/ 301\n/rent/c1/ /rent/c0/ 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c0/", "page-redirected"), "warning")

    def test_redirect_to_open_page_stays_info(self):
        self.new.remove("rent/c0")
        self.new.write("_redirects", "/rent/c0/ /rent/c1/ 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c0/", "page-redirected"), "info")


class HomeAndBrokenTargets(Base):
    """#247, #248, #249."""

    def test_removed_section_to_home_is_critical(self):
        for i in range(CITIES):
            self.new.remove(f"rent/c{i}")
        self.new.write("_redirects", "/rent/* / 301\n")
        code, data = self.run_diff("--strict", "--no-checks")
        self.assertEqual(code, 1)
        self.assertEqual(self.level(data, SITE + "/rent/c3/", "page-redirected"), "critical")

    def test_unfillable_target_is_a_warning(self):
        for i in range(CITIES):
            self.new.remove(f"rent/c{i}")
        for rule in ("/rent/:city /flat/:slug 301\n", "/rent/* /flat/* 301\n"):
            self.new.write("_redirects", rule)
            _, data = self.run_diff("--no-checks")
            self.assertEqual(self.level(data, SITE + "/rent/c3/", "page-redirected"), "warning")

    def test_www_target_is_checked_against_the_build(self):
        self.new.remove("rent/c0")
        self.new.write("_redirects", "/rent/c0/ https://www.demo.example/gone/ 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c0/", "page-redirected"), "warning")
        self.new.write("_redirects", "/rent/c0/ https://www.demo.example/rent/c1/ 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c0/", "page-redirected"), "info")


class RuleFormats(Base):
    """#250, #251."""

    def test_vercel_routes_dest_is_a_rewrite_and_404_an_error(self):
        for i in range(CITIES):
            self.new.remove(f"rent/c{i}")
            self.new.write(f"flat/c{i}/index.html", page(f"Rent in city {i}"))
        self.new.write("vercel.json", json.dumps({"routes": [
            {"src": "/rent/(.*)", "dest": "/flat/$1"}]}))
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c3/", "page-redirected"), "info")
        self.new.write("vercel.json", json.dumps({"routes": [
            {"src": "/rent/(.*)", "status": 404}]}))
        _, data = self.run_diff("--no-checks")
        removed = [r for r in data["removed"] if r["url"] == SITE + "/rent/c3/"][0]
        self.assertEqual(removed["answer"], "404")

    def test_cyrillic_rule_matches_percent_encoded_url(self):
        self.old.write("аренда/москва/index.html", page("Rent in Moscow"))
        self.new.write("аренда/moskva/index.html", page("Rent in Moscow"))
        self.new.write("_redirects", "/аренда/москва/ /аренда/moskva/ 301\n")
        _, data = self.run_diff("--no-checks")
        removed = [r for r in data["removed"] if "moskva" not in r["url"]]
        self.assertEqual([r["level"] for r in removed], ["info"])


class NosnippetLevel(Base):
    """#253: новый nosnippet в diff — критичный, как в check."""

    def test_nosnippet_added_fails_strict(self):
        self.new.write("_headers", "/rent/*\n  X-Robots-Tag: nosnippet\n")
        for i in range(CITIES):
            self.new.write(f"rent/c{i}/index.html", page(
                f"Rent in city {i}", head='<meta name="robots" content="nosnippet">'))
        code, data = self.run_diff("--strict")
        self.assertEqual(code, 1)
        self.assertEqual(self.level(data, SITE + "/rent/c3/", "nosnippet-added"), "critical")

    def test_without_checks_it_stays_a_warning(self):
        self.new.write("rent/c3/index.html", page(
            "Rent in city 3", head='<meta name="robots" content="nosnippet">'))
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c3/", "nosnippet-added"), "warning")


class MovedSection(Base):
    """#255: раздел, уехавший редиректом, сравнивается парами."""

    def test_text_cut_on_moved_section_is_reported(self):
        for i in range(CITIES):
            self.new.remove(f"rent/c{i}")
            self.new.write(f"flats/c{i}/index.html",
                           page(f"Rent in city {i}", words=10, section="flats"))
        self.new.write("_redirects", "/rent/*  /flats/:splat  301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/flats/c3/", "text-shrunk"), "warning")


if __name__ == "__main__":
    unittest.main()
