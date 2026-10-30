# -*- coding: utf-8 -*-
"""
Ссылки, хабы и разделы — то, что нашла четвёртая батарея сценариев.

* сайт под префиксом (`--site https://company.com/docs/`): ссылки в
  /pricing и /blog — другая часть домена, а не битые ссылки;
* числовой адрес (`/products/1001/`, `/archive/2019/`) — страница, а не
  пагинация;
* страница-список засчитывается хабу, только если ссылается на заметную долю
  детей, а не на пять соседей из блока «рядом»;
* хабы считаются за один проход, а не раздел × все страницы.
"""

import os
import shutil
import tempfile
import time
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core, signals

TEXT = ("Plumbers fix leaks, unclog drains and install water heaters. Most visits take "
        "under two hours, and every job comes with a written quote first. ") * 3


def html(title, body=""):
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            '<meta name="description" content="A page of the test site for the checks">'
            f'</head><body><main><h1>{title}</h1><p>{TEXT}</p>{body}</main></body></html>')


class Site(unittest.TestCase):
    def build(self, files, site):
        root = tempfile.mkdtemp(prefix="indexgap-r4-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return core.load_pages(root, site)[0]

    def issues(self, files, site="https://example.com"):
        pages = self.build(files, site)
        return checks.run_all(pages, site.rstrip("/") + "/")["issues"]


class SubPath(Site):
    SITE = "https://company.com/docs/"
    NAV = '<a href="/pricing">Pricing</a><a href="/blog/">Blog</a><a href="/other-repo/">x</a>'

    def files(self, extra=""):
        nav = self.NAV + '<a href="/docs/">Docs</a><a href="/docs/a/">A</a><a href="/docs/b/">B</a>'
        return {"index.html": html("Docs home", nav + extra),
                "a/index.html": html("Install guide", nav),
                "b/index.html": html("Config guide", nav),
                "blog/index.html": html("Docs blog", nav)}

    def test_links_outside_the_base_are_another_part_of_the_site(self):
        broken = [i for i in self.issues(self.files(), self.SITE) if i[2] == "broken-link"]
        self.assertEqual(broken, [])

    def test_a_missing_page_inside_the_base_is_broken(self):
        broken = [i for i in self.issues(self.files('<a href="/docs/c/">gone</a>'), self.SITE)
                  if i[2] == "broken-link"]
        self.assertEqual(len(broken), 1)


class Hubs(Site):
    def hub(self, kids, linked, kid_body=""):
        files = {"index.html": html("Home", '<a href="/products/">all</a>'),
                 "products/index.html": html("All products", "".join(
                     f'<a href="/products/{k}/">{k}</a>' for k in linked))}
        for k in kids:
            files[f"products/{k}/index.html"] = html(f"Product {k}",
                                                    '<a href="/products/">up</a>' + kid_body)
        return files

    def missing(self, files):
        return [i for i in self.issues(files) if i[2] == "hub-missing-links"]

    def test_numeric_slugs_are_pages_not_pagination(self):
        kids = ["1001", "1002", "1003", "1004"]
        found = self.missing(self.hub(kids, kids[:2]))
        self.assertEqual(len(found), 1)
        self.assertIn("1003", found[0][3])

    def test_a_nearby_block_does_not_stand_in_for_the_hub(self):
        kids = [f"item{i}" for i in range(20)]
        nearby = "".join(f'<a href="/products/item{i}/">n{i}</a>' for i in range(5))
        found = self.missing(self.hub(kids, kids[:2], kid_body=nearby))
        self.assertEqual(len(found), 1)

    def test_a_canonical_twin_is_not_a_missing_kid(self):
        kids = ["alpha", "beta", "gamma"]
        files = self.hub(kids, kids)
        files["products/alpha-print/index.html"] = html(
            "Product alpha print", '<a href="/products/">up</a>').replace(
            "</title>", '</title><link rel="canonical" href="https://example.com/products/alpha/">')
        self.assertEqual(self.missing(files), [])

    def test_real_pagination_still_counts(self):
        kids = ["alpha", "beta", "gamma"]
        files = self.hub(kids, kids[:2])
        files["products/page/2/index.html"] = html("Products page 2",
                                                   '<a href="/products/gamma/">gamma</a>')
        self.assertEqual(self.missing(files), [])

    def test_hubs_scale_linearly(self):
        class P:
            def __init__(self, key):
                self.key, self.url = key, "https:" + key + "/"
        pages = [P("//s.com/h%d" % h) for h in range(400)]
        pages += [P("//s.com/h%d/k%d" % (h, k)) for h in range(400) for k in range(20)]
        graph = {"inbound": {p.url: [] for p in pages}, "outbound": {}}
        started = time.perf_counter()
        found = signals.hub_links(pages, graph)
        self.assertEqual(len(found), 400)
        self.assertLess(time.perf_counter() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
