# -*- coding: utf-8 -*-
"""
1.30 (forms): адрес в форме, которой хостинг не отдаёт.

* #82: hreflang на `/de/a` или `/de/a/index.html` при `de/a/index.html` с
  canonical `/de/a/` проходил как точный адрес версии.
* #175: страница, на которую ведут только ссылки в форме, отдающей 404
  (`/x.html`, `/x/index.markdown`), не называлась ни сиротой, ни недостижимой.
* #257: `indexgap diff` называл смену формы адреса `/x/` → `/x.html` без
  редиректа лишь info.
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
from indexgap import cli

SITE = "https://demo.example"
FILL = " ".join(["Rent deposit and commute figures differ between districts, and the "
                 "guide explains how newcomers search for viewings and contracts."] * 3)


def html(title, links="", head="", lang="en"):
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
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

    def write(self, rel, text, root=None):
        path = os.path.join(root or self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self):
        out = os.path.join(self.tmp, "r.json")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["check", self.dir, "--site", SITE, "--no-content", "--no-aeo",
                      "--out", out])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def issues(self, data, code):
        return [i for i in data["issues"] if i["code"] == code]


class HreflangForm(Site):
    """#82."""

    def build(self, form, extra=None):
        S = SITE
        for c in "abc":
            for lg in ("en", "de"):
                head = f'<link rel="canonical" href="{S}/{lg}/{c}/">' + "".join(
                    f'<link rel="alternate" hreflang="{x}" href="{S}{form.format(x=x, c=c)}">'
                    for x in ("en", "de"))
                links = a("/", f"/{'de' if lg == 'en' else 'en'}/{c}/")
                self.write(f"{lg}/{c}/index.html", html(f"{lg} {c} page", links, head, lg))
        self.write("index.html", html("Home", a(*(f"/{x}/{c}/" for x in ("en", "de")
                                                for c in "abc"))))
        for name, text in (extra or {}).items():
            self.write(name, text)
        return self.check()

    def bad(self, data):
        return [i for i in self.issues(data, "hreflang-bad-code") if "/a" in i["message"]
                or "/b" in i["message"] or "/c" in i["message"]]

    def test_no_slash_form_is_a_redirect(self):
        found = self.bad(self.build("/{x}/{c}"))
        self.assertEqual(len(found), 6)
        self.assertEqual({i["level"] for i in found}, {"warning"})
        self.assertTrue(any("/de/a (редирект на /de/a/)" in i["message"] for i in found))

    def test_index_html_form_is_a_copy(self):
        found = self.bad(self.build("/{x}/{c}/index.html"))
        self.assertEqual(len(found), 6)
        self.assertTrue(any("/en/b/index.html" in i["message"] for i in found))

    # Каждая проверка «молчит» начинается с находки: на старой версии пакета
    # она падает, а не проходит даром.
    def test_exact_form_stays_quiet(self):
        self.assertTrue(self.bad(self.build("/{x}/{c}")))
        self.assertEqual(self.bad(self.build("/{x}/{c}/")), [])

    def test_vercel_trailing_slash_keeps_it_quiet(self):
        self.assertTrue(self.bad(self.build("/{x}/{c}")))
        data = self.build("/{x}/{c}", {"vercel.json": '{"trailingSlash": false}'})
        self.assertEqual(self.bad(data), [])

    def test_redirect_rule_keeps_it_quiet(self):
        self.assertTrue(self.bad(self.build("/{x}/{c}")))
        data = self.build("/{x}/{c}", {"_redirects": "/en/* /en/:splat/ 301\n"
                                                     "/de/* /de/:splat/ 301\n"})
        self.assertEqual(self.bad(data), [])


class OrphanByForm(Site):
    """#175."""

    def test_page_linked_only_through_404_forms(self):
        self.write("index.html", html("Home", a("/a/", "/lonely.html", "/other/index.markdown")))
        self.write("a/index.html", html("Alpha", a("/")))
        self.write("lonely/index.html", html("Lonely", a("/", "/behind/")))
        self.write("other/index.html", html("Other", a("/")))
        self.write("behind/index.html", html("Behind", a("/")))
        data = self.check()
        orphans = {i["url"]: i["level"] for i in self.issues(data, "orphan")}
        self.assertEqual(orphans, {SITE + "/lonely/": "warning", SITE + "/other/": "warning"})
        self.assertIn(SITE + "/lonely/", data["orphans"])
        far = {i["url"]: i["level"] for i in self.issues(data, "unreachable")}
        self.assertEqual(far, {SITE + "/behind/": "warning"})
        self.assertFalse([i for i in data["issues"] if i["level"] == "critical"
                          and i["code"] in ("orphan", "unreachable")])

    def lonely(self, link):
        self.write("index.html", html("Home", a(link)))
        self.write("lonely/index.html", html("Lonely", a("/")))
        self.assertEqual([i["level"] for i in self.issues(self.check(), "orphan")],
                         ["warning"])

    def test_a_good_form_anywhere_keeps_the_page_linked(self):
        self.lonely("/lonely.html")
        self.write("index.html", html("Home", a("/lonely.html", "/lonely/")))
        self.assertEqual(self.issues(self.check(), "orphan"), [])

    def test_host_rewrites_keep_current_behaviour(self):
        self.lonely("/lonely.html")
        self.write("vercel.json", '{"cleanUrls": true}')
        self.assertEqual(self.issues(self.check(), "orphan"), [])

    def test_source_tree_keeps_current_behaviour(self):
        self.lonely("/lonely.md")
        self.write("_config.yml", "title: demo\n")
        self.assertEqual(self.issues(self.check(), "orphan"), [])


class DiffShape(unittest.TestCase):
    """#257."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-130d-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old = os.path.join(self.dir, "old")
        self.new = os.path.join(self.dir, "new")
        cities = ["berlin", "bonn", "kiel", "essen", "mainz", "trier", "ulm", "jena"]
        links = a("/", *(f"/rent/{c}/" for c in cities))
        new_links = a("/", "/rent/berlin.html", "/rent/bonn.html",
                      *(f"/rent/{c}/" for c in cities[2:]))
        for root, ls in ((self.old, links), (self.new, new_links)):
            self.write(root, "index.html", html("Home", ls))
        for c in cities:
            self.write(self.old, f"rent/{c}/index.html", html(f"Rent {c}", links))
            name = f"rent/{c}.html" if c in ("berlin", "bonn") else f"rent/{c}/index.html"
            self.write(self.new, name, html(f"Rent {c}", new_links))

    def write(self, root, rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_diff(self):
        out = os.path.join(self.dir, "d.html")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["diff", self.old, self.new, "--site", SITE, "--out", out, "--no-checks"])
        with open(os.path.join(self.dir, "d.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return [i for i in data["items"] if i["code"] == "template-change"
                and "URL" in i["message"]]

    def test_old_shape_without_redirect_is_a_warning(self):
        found = self.run_diff()
        self.assertEqual([i["level"] for i in found], ["warning"])
        self.assertIn("404", found[0]["message"])
        self.assertIn("/rent/berlin/", found[0]["message"])

    def test_redirect_rule_keeps_it_info(self):
        self.assertEqual([i["level"] for i in self.run_diff()], ["warning"])
        self.write(self.new, "_redirects", "/rent/berlin/ /rent/berlin.html 301\n"
                                           "/rent/bonn/ /rent/bonn.html 301\n")
        self.assertEqual([i["level"] for i in self.run_diff()], ["info"])

    def test_clean_urls_keep_it_info(self):
        self.assertEqual([i["level"] for i in self.run_diff()], ["warning"])
        self.write(self.new, "vercel.json", '{"cleanUrls": true}')
        self.assertEqual([i["level"] for i in self.run_diff()], ["info"])


if __name__ == "__main__":
    unittest.main()
