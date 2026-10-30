# -*- coding: utf-8 -*-
"""
Ссылки и хабы — то, что осталось после четвёртой батареи.

* страница-список раздела находится обходом от хаба: буква указателя с двумя
  детьми, последний лист пагинации, `/plumbing-2/` рядом с `/plumbing/`;
  а блок «рядом» на странице-ребёнке хаб не заменяет;
* ссылка в форме, которую хостинг не отдаёт: `/about.html` при
  `about/index.html`, `/faq/` при `faq.html`;
* ссылка, совпавшая со страницей только без учёта регистра;
* слаг с точкой (`/v1.2/`) — страница, а не файл;
* ссылки со страниц, закрытых в robots.txt, поисковик не читает.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

TEXT = ("Plumbers fix leaks, unclog drains and install water heaters. Most visits take "
        "under two hours, and every job comes with a written quote first. ") * 3


def html(title, body="", head=""):
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            '<meta name="description" content="A page of the test site for the checks">'
            f'{head}</head><body><main><h1>{title}</h1><p>{TEXT}</p>{body}</main></body></html>')


def links(*urls):
    return "".join(f'<a href="{u}">link {n}</a> ' for n, u in enumerate(urls))


class Site(unittest.TestCase):
    def write(self, files, parent=None):
        top = tempfile.mkdtemp(prefix="indexgap-r5-")
        self.addCleanup(shutil.rmtree, top, True)
        root = os.path.join(top, "site")
        os.makedirs(root)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        for name, text in (parent or {}).items():
            with open(os.path.join(top, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        return root

    def run_checks(self, files, site="https://example.com", parent=None, **kw):
        root = self.write(files, parent)
        pages = core.load_pages(root, site)[0]
        return pages, checks.run_all(pages, site.rstrip("/") + "/", **kw)

    def issues(self, files, site="https://example.com", **kw):
        return self.run_checks(files, site, **kw)[1]["issues"]

    def of(self, files, code, **kw):
        return [i for i in self.issues(files, **kw) if i[2] == code]


class Listings(Site):
    def missing(self, files):
        return self.of(files, "hub-missing-links")

    def kids(self, files, names, hub="plumbing"):
        for k in names:
            files[f"{hub}/{k}/index.html"] = html(f"Plumbers in {k}", links(f"/{hub}/"))
        return files

    def test_sparse_letters_of_an_index_are_listings(self):
        letters = {"a": ["albany", "austin"], "b": ["boston", "boise", "buffalo"],
                   "x": ["xenia"], "z": ["zion", "zanesville"]}
        for form in ("letter-{0}", "{0}"):
            with self.subTest(form=form):
                files = {"index.html": html("Home", links("/plumbing/")),
                         "plumbing/index.html": html("Plumbing", links(*(
                             f"/plumbing/{form.format(l)}/" for l in letters)))}
                for l, names in letters.items():
                    files[f"plumbing/{form.format(l)}/index.html"] = html(
                        f"Letter {l}", links("/plumbing/", *(f"/plumbing/{n}/" for n in names)))
                    self.kids(files, names)
                self.assertEqual(self.missing(files), [])

    def test_letters_one_level_deeper_are_listings(self):
        letters = {"a": ["albany", "austin"], "b": ["boston"], "z": ["zion", "zanesville"]}
        files = {"index.html": html("Home", links("/plumbing/")),
                 "plumbing/index.html": html("Plumbing", links(*(
                     f"/plumbing/az/{l}/" for l in letters)))}
        for l, names in letters.items():
            # Навигация по буквам — на каждой букве: это не делает её ссылки чужими.
            files[f"plumbing/az/{l}/index.html"] = html(f"Letter {l}", links(
                *(f"/plumbing/az/{x}/" for x in letters), *(f"/plumbing/{n}/" for n in names)))
            self.kids(files, names)
        self.assertEqual(self.missing(files), [])

    def states(self, extra_links=()):
        states = {"texas": ["austin", "dallas"], "ohio": ["dayton"], "utah": ["provo", "ogden"]}
        files = {"index.html": html("Home", links("/plumbing/")),
                 "plumbing/index.html": html("Plumbing", links(*(
                     f"/plumbing/by-state/{s}/" for s in states)))}
        for s, names in states.items():
            files[f"plumbing/by-state/{s}/index.html"] = html(f"Plumbing in {s}", links(
                *(f"/plumbing/by-state/{x}/" for x in states), *extra_links,
                *(f"/plumbing/{n}/" for n in names)))
            self.kids(files, names)
        return files

    def test_a_deeper_list_page_counts_whatever_its_size(self):
        self.assertEqual(self.missing(self.states()), [])

    def test_a_deeper_page_that_mostly_links_elsewhere_is_not_a_list(self):
        files = self.states(extra_links=[f"/plumbing/austin/{x}/" for x in "abcdefg"])
        for x in "abcdefg":
            files[f"plumbing/austin/{x}/index.html"] = html(f"Austin {x}", links("/plumbing/"))
        self.assertEqual(len(self.missing(files)), 1)

    def pages_of(self, pager, per=10, total=53):
        names = [f"city{i}" for i in range(total)]
        files = {"index.html": html("Home", links("/plumbing/")),
                 "plumbing/index.html": html("Plumbing", links(
                     *(f"/plumbing/{k}/" for k in names[:per]), pager(2)))}
        count = (total + per - 1) // per
        for n in range(2, count + 1):
            nxt = [pager(n + 1)] if n < count else []
            files[pager(n).strip("/") + "/index.html"] = html(f"Plumbing, page {n}", links(
                *(f"/plumbing/{k}/" for k in names[(n - 1) * per:n * per]), *nxt))
        return self.kids(files, names)

    def test_pagination_pages_at_any_size(self):
        for pager in (lambda n: f"/plumbing/page-{n}/", lambda n: f"/plumbing/strona/{n}/",
                      lambda n: f"/plumbing/p{n}/", lambda n: f"/plumbing/page/{n}/",
                      lambda n: f"/plumbing/{n}/"):
            with self.subTest(pager=pager(2)):
                self.assertEqual(self.missing(self.pages_of(pager)), [])

    def test_sibling_pagination_belongs_to_the_hub(self):
        files = self.pages_of(lambda n: f"/plumbing-{n}/")
        self.assertEqual(self.missing(files), [])

    def test_sibling_pagination_is_not_a_missing_page_of_the_parent(self):
        files = {"index.html": html("Home", links("/services/")),
                 "services/index.html": html("Services", links("/services/plumbing/",
                                                                "/services/roofing/")),
                 "services/roofing/index.html": html("Roofing", links("/services/")),
                 "services/plumbing/index.html": html("Plumbing", links(
                     "/services/plumbing/a/", "/services/plumbing-2/")),
                 "services/plumbing-2/index.html": html("Plumbing, page 2", links(
                     "/services/plumbing/b/")),
                 "services/plumbing/a/index.html": html("Plumbing a", links("/services/")),
                 "services/plumbing/b/index.html": html("Plumbing b", links("/services/"))}
        self.assertEqual(self.missing(files), [])

    def test_a_rotating_nearby_block_does_not_hide_the_gap(self):
        names = [f"city{i}" for i in range(20)]
        files = {"index.html": html("Home", links("/plumbing/")),
                 "plumbing/index.html": html("Plumbing", links("/plumbing/city0/",
                                                               "/plumbing/city1/"))}
        for i, k in enumerate(names):
            nearby = [f"/plumbing/{names[(i + j) % 20]}/" for j in range(1, 6)]
            files[f"plumbing/{k}/index.html"] = html(f"Plumbers in {k}",
                                                     links("/plumbing/", *nearby))
        found = self.missing(files)
        self.assertEqual(len(found), 1)
        self.assertIn("18", found[0][3])

    def test_a_post_slug_like_p7_is_a_page_not_pagination(self):
        posts = [f"p{i}" for i in range(8)]
        files = {"index.html": html("Home", links("/posts/")),
                 "posts/index.html": html("Posts", links(*(f"/posts/{p}/" for p in posts[:3])))}
        self.kids(files, posts, hub="posts")
        found = self.missing(files)
        self.assertEqual(len(found), 1)
        self.assertIn("5", found[0][3])


if __name__ == "__main__":
    unittest.main()
