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
from urllib.parse import urlsplit

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


class Broken(Site):
    def site(self, *extra, **files):
        base = {"index.html": html("Home", links("/plumbing/", "/plumbing/boston/", *extra)),
                "plumbing/index.html": html("Plumbing", links("/plumbing/boston/")),
                "plumbing/boston/index.html": html("Boston", links("/plumbing/")),
                "guides/index.html": html("Guides", links("/"))}
        base.update({k.replace("__", "/"): v for k, v in files.items()})
        return base

    def broken(self, files):
        return " ".join(i[3] for i in self.of(files, "broken-link"))

    def test_a_dotted_slug_is_a_page_not_a_file(self):
        for slug in ("/plumbing/v1.2/", "/guides/gost-12.4.011/", "/guides/node.js/",
                     "/guides/asp.net"):
            with self.subTest(slug=slug):
                self.assertIn(slug.rstrip("/"), self.broken(self.site(slug)))

    def test_files_are_still_not_pages(self):
        found = self.broken(self.site("/files/price.pdf", "/img/a.webp", "/guides/app.js",
                                      "/fonts/a.woff2", "/feed.atom", "/data.csv"))
        self.assertEqual(found, "")

    def test_a_file_of_the_build_is_not_broken_whatever_its_extension(self):
        found = self.broken(self.site("/download/setup.exe", "/guides/v1.2.tar.xz",
                                      **{"download__setup.exe": "MZ",
                                         "guides__v1.2.tar.xz": "x"}))
        self.assertEqual(found, "")

    def test_a_folder_with_only_files_is_not_a_page(self):
        found = self.broken(self.site("/downloads/", **{"downloads__x.pdf": "%PDF"}))
        self.assertIn("/downloads", found)

    def test_a_folder_with_a_server_route_is_a_page(self):
        found = self.broken(self.site("/start", **{"start__page.js": "module.exports = {}"}))
        self.assertEqual(found, "")

    def test_a_link_in_the_wrong_case(self):
        files = self.site("/Plumbing/Boston/")
        self.assertEqual(self.of(files, "broken-link"), [])
        found = self.of(files, "wrong-link-form")
        self.assertEqual(len(found), 1)
        self.assertIn("/Plumbing/Boston", found[0][3])
        self.assertIn("/plumbing/boston", found[0][3])

    def test_case_of_the_host_and_of_percent_codes_does_not_matter(self):
        files = self.site("https://EXAMPLE.com/plumbing/boston/", "/%d0%b1%d0%bb%d0%be%d0%b3/",
                          **{"блог/index.html": html("Блог", links("/"))})
        self.assertEqual(self.broken(files), "")
        self.assertEqual(self.of(files, "wrong-link-form"), [])


class HostForms(Site):
    def site(self, *hrefs, site="https://example.com", parent=None, **files):
        prefix = urlsplit(site).path.rstrip("/")
        base = {"index.html": html("Home", links(*(prefix + h for h in hrefs))),
                "about/index.html": html("About us", links(prefix + "/")),
                "faq.html": html("Questions", links(prefix + "/"))}
        base.update({k.replace("__", "/"): v for k, v in files.items()})
        return self.run_checks(base, site, parent=parent)

    def found(self, *hrefs, **kw):
        pages, result = self.site(*hrefs, **kw)
        self.assertEqual([i for i in result["issues"] if i[2] == "broken-link"], [])
        return [i[3] for i in result["issues"] if i[2] == "wrong-link-form"]

    def test_html_link_to_a_folder_page(self):
        found = self.found("/about.html")
        self.assertEqual(len(found), 1)
        self.assertIn("/about.html", found[0])
        self.assertIn("/about/", found[0])

    def test_slash_link_to_a_flat_page(self):
        found = self.found("/faq/")
        self.assertEqual(len(found), 1)
        self.assertIn("/faq/", found[0])
        self.assertIn("/faq.html", found[0])

    def test_the_slash_form_never_becomes_the_address_of_a_flat_page(self):
        pages, _ = self.site("/faq/", "/faq/")
        urls = sorted(p.url for p in pages)
        self.assertIn("https://example.com/faq.html", urls)
        self.assertNotIn("https://example.com/faq/", urls)

    def test_forms_every_static_host_serves(self):
        self.assertEqual(self.found("/about/", "/about", "/about/index.html",
                                    "/faq.html", "/faq"), [])

    def test_a_flat_file_next_to_a_folder_of_the_same_name(self):
        # Какую из двух форм отдаст хостинг, не понять — и судить не о чем.
        pages, result = self.site("/faq/", "/faq.html", **{"faq__index.html": html("FAQ index")})
        self.assertNotIn("broken-link", [i[2] for i in result["issues"]])
        self.assertNotIn("wrong-link-form", [i[2] for i in result["issues"]])

    def test_a_sub_path_site(self):
        found = self.found("/faq/", site="https://user.github.io/repo/")
        self.assertEqual(len(found), 1)

    def test_a_redirect_rule_covers_the_link(self):
        cases = [{"_redirects": "/faq/  /faq  301\n/about.html /about/ 301\n"},
                 {"_redirects": "/*  /index.html  200\n"}]
        for files in cases:
            with self.subTest(files=files):
                self.assertEqual(self.found("/faq/", "/about.html", **files), [])
        toml = ('[[redirects]]\n  from = "/faq/"\n  to = "/faq"\n'
                '[[redirects]]\n  from = "/about.html"\n  to = "/about/"\n')
        self.assertEqual(self.found("/faq/", "/about.html", parent={"netlify.toml": toml}), [])
        vercel = '{"redirects": [{"source": "/faq/", "destination": "/faq"}]}'
        self.assertEqual(len(self.found("/faq/", "/about.html",
                                        parent={"vercel.json": vercel})), 1)
        self.assertEqual(self.found("/faq/", "/about.html",
                                    parent={"vercel.json": '{"cleanUrls": true}'}), [])


class VercelSources(Site):
    """`source` в vercel.json — синтаксис path-to-regexp, с группами-выражениями."""

    def matches(self, pattern, path):
        regex = core._route_regex(pattern)
        return bool(regex and regex.match(path))

    def test_groups_with_expressions(self):
        cases = [("/blog/:slug((?!draft).*)", "/blog/hello/", True),
                 ("/blog/:slug((?!draft).*)", "/blog/draft-1/", False),
                 ("/(.*)\\.pdf", "/files/a.pdf", True),
                 ("/(.*)\\.pdf", "/files/a/", False),
                 ("/((?!blog).*)", "/docs/b/", True),
                 ("/((?!blog).*)", "/blog/a/", False),
                 ("/:id(\\d+)", "/123", True),
                 ("/:id(\\d+)", "/abc", False),
                 ("/docs{/:page}?", "/docs", True),
                 ("/docs{/:page}?", "/docs/a", True),
                 ("/glossary/(.*)", "/glossary/c/", True),
                 ("/glossary/*", "/glossary/c/", True),
                 ("/blog/:path*", "/blog/a/", True),
                 ("/a.b/:x", "/aXb/1", False)]
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(self.matches(pattern, path), expected)

    def test_a_pattern_it_cannot_read_is_skipped(self):
        for pattern in ("/(unclosed", "/:x([z-a])", "/(a))"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(core._route_regex(pattern))

    def test_a_negative_lookahead_rule_closes_the_rest(self):
        vercel = ('{"headers": [{"source": "/((?!blog).*)", "headers": '
                  '[{"key": "X-Robots-Tag", "value": "noindex"}]}]}')
        files = {"index.html": html("Home", links("/blog/a/", "/docs/b/")),
                 "blog/a/index.html": html("Blog a", links("/")),
                 "docs/b/index.html": html("Docs b", links("/"))}
        root = self.write(files, {"vercel.json": vercel})
        pages = core.load_pages(root, "https://example.com")[0]
        closed = sorted(p.url for p in pages if p.noindex)
        self.assertEqual(closed, ["https://example.com/", "https://example.com/docs/b/"])

    def test_an_unreadable_rule_closes_nothing_and_says_so(self):
        vercel = ('{"headers": [{"source": "/(unclosed", "headers": '
                  '[{"key": "X-Robots-Tag", "value": "noindex"}]}]}')
        root = self.write({"index.html": html("Home")}, {"vercel.json": vercel})
        pages, problems = core.load_pages(root, "https://example.com")
        self.assertEqual([p.url for p in pages if p.noindex], [])
        self.assertTrue(any("/(unclosed" in p for p in problems), problems)


class BehindRobots(Site):
    """Страница, закрытая в robots.txt, не читается: её ссылки поисковик не видит."""

    FILES = {"index.html": html("Home", links("/plumbing/", "/private/")),
             "plumbing/index.html": html("Plumbing", links("/")),
             "private/index.html": html("Private", links("/plumbing/denver/")),
             "plumbing/denver/index.html": html("Denver", links("/plumbing/"))}

    def test_links_from_a_blocked_page_do_not_reach(self):
        _, result = self.run_checks(self.FILES, blocked={"https://example.com/private/"})
        found = [i for i in result["issues"] if i[2] == "unreachable"]
        self.assertEqual([i[1] for i in found], ["https://example.com/plumbing/denver/"])
        self.assertIn("robots.txt", found[0][3])
        # Сама закрытая страница — не «недостижимая»: о ней скажет robots-blocks-page.
        self.assertNotIn("https://example.com/private/", [i[1] for i in found])

    def test_without_robots_nothing_changes(self):
        _, result = self.run_checks(self.FILES)
        self.assertEqual([i for i in result["issues"] if i[2] == "unreachable"], [])

    def test_the_cli_reads_robots_of_the_build(self):
        import contextlib
        import io
        import json
        from indexgap import cli
        files = dict(self.FILES, **{"robots.txt": "User-agent: *\nDisallow: /private/\n"})
        root = self.write(files)
        out = os.path.join(os.path.dirname(root), "report.html")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["check", root, "--site", "https://example.com/", "--out", out])
        with open(out[:-5] + ".json", encoding="utf-8") as fh:
            issues = json.load(fh)["issues"]
        unreachable = [i["url"] for i in issues if i["code"] == "unreachable"]
        self.assertEqual(unreachable, ["https://example.com/plumbing/denver/"])

    def test_a_site_closed_whole_is_not_a_flood(self):
        from indexgap import aeo
        root = self.write(dict(self.FILES, **{"robots.txt": "User-agent: *\nDisallow: /\n"}))
        pages = core.load_pages(root, "https://example.com")[0]
        robots = aeo.read_robots(os.path.join(root, "robots.txt"))
        self.assertEqual(aeo.blocked_urls(pages, robots), set())


if __name__ == "__main__":
    unittest.main()
