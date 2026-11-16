# -*- coding: utf-8 -*-
"""
1.25: шаблоны и структура сайта — случаи, где отчёт молчал о настоящей беде.

* заглушка-редирект на страницу, которой нет в сборке, не давала ни одной
  находки, а битая ссылка на ней удалялась вместе с заглушкой;
* шаблон раздела не находился, как только рядом появлялись два поста блога:
  порог «90% страниц» считался только по языку;
* после 400 страниц LSH терял треть клонов с подставленным городом;
* `stale-year` под префиксом (`--site https://demo.example/blog`) видел один
  раздел на весь сайт и молчал;
* страницы за хабом с `meta robots nofollow` считались достижимыми;
* скелет заголовков с городом в каждом H2 не считался повторяющимся;
* «in 2023, explained» и «for 2023.» не считались годом;
* страница, пропущенная из-за общего адреса, была только в консоли.
"""

import datetime
import io
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, content, core, signals

SITE = "https://demo.example"
THIS_YEAR = datetime.date.today().year
SYLLABLES = ["ka", "lo", "mi", "ne", "ru", "sa", "to", "vi", "be", "da", "fo", "gu",
             "ho", "ji", "pe", "qu", "ze", "wa", "xo", "ly"]


def prose(seed, n):
    rnd = random.Random(seed)
    return " ".join("".join(rnd.choice(SYLLABLES) for _ in range(rnd.randint(2, 4)))
                    for _ in range(n))


def html(title, body, head="", h1=None):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{title}</title>{head}</head><body>'
            f'<nav><a href="/">Home</a></nav><main><h1>{h1 or title}</h1>{body}</main>'
            f'</body></html>')


class Site(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dir = os.path.join(self.root, "site")
        os.makedirs(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self, site=SITE, *extra):
        out = os.path.join(self.root, "r.html")
        with mock.patch.object(sys, "stdout", io.StringIO()) as console:
            cli.main(["check", self.dir, "--site", site, "--no-aeo", "--out", out, *extra])
        with open(os.path.join(self.root, "r.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        data["_console"] = console.getvalue()
        with open(out, encoding="utf-8") as fh:
            data["_html"] = fh.read()
        return data


def codes(data, code):
    return sorted(i["url"] for i in data["issues"] if i["code"] == code)


class TestRedirectStubIntoNowhere(Site):
    def build(self, target):
        links = "".join(f'<a href="/rent/{c}/">{c}</a> ' for c in ("alpha", "bravo", "old"))
        self.write("index.html", html("Home", f'<p>{prose(1, 80)}</p><a href="/rent/">Rent</a>'))
        self.write("rent/index.html", html("Rent", f"<p>{prose(2, 80)}</p>{links}"))
        for n, c in enumerate(("alpha", "bravo")):
            self.write(f"rent/{c}/index.html", html(f"Rent in {c}", f"<p>{prose(10 + n, 120)}</p>"))
        self.write("rent/old/index.html",
                   f'<!doctype html><html><head><title>Redirecting</title>'
                   f'<meta http-equiv="refresh" content="0; url={target}">'
                   f'<link rel="canonical" href="{target}"></head><body></body></html>')

    def test_stub_to_a_missing_page_is_a_broken_link(self):
        self.build("/rent/gone/")
        data = self.check()
        self.assertEqual(codes(data, "broken-link"), [f"{SITE}/rent/old/"])
        found = [i for i in data["issues"] if i["code"] == "broken-link"][0]
        self.assertIn("заглушка-редирект ведёт на страницу, которой нет в сборке: /rent/gone",
                      found["message"])

    def test_stub_to_a_real_page_stays_quiet(self):
        self.build("/rent/alpha/")
        self.assertEqual(codes(self.check(), "broken-link"), [])

    def test_stub_to_another_host_stays_quiet(self):
        self.build("https://other.example/rent/")
        self.assertEqual(codes(self.check(), "broken-link"), [])


class TestSectionTemplate(Site):
    def build(self, posts):
        block = f"<p>{prose(99, 300)}</p>"
        items = "".join(f'<a href="/items/i{n}/">i{n}</a> ' for n in range(20))
        blog = "".join(f'<a href="/blog/p{n}/">p{n}</a> ' for n in range(posts))
        self.write("index.html", html("Home", f"<p>{prose(1, 60)}</p>{items}{blog}"))
        for n in range(20):
            self.write(f"items/i{n}/index.html",
                       html(f"Item {n}", f"<p>{prose(100 + n, 40)}</p>{block}"))
        for n in range(posts):
            self.write(f"blog/p{n}/index.html", html(f"Post {n}", f"<p>{prose(500 + n, 400)}</p>"))

    def test_two_blog_posts_do_not_hide_the_template(self):
        for posts in (0, 2, 6):
            with self.subTest(posts=posts):
                shutil.rmtree(self.dir)
                os.makedirs(self.dir)
                self.build(posts)
                data = self.check()
                low = codes(data, "low-uniqueness")
                self.assertEqual(len(low), 20)
                self.assertTrue(all("/items/" in u for u in low))


class TestLshFindsSlotClones(unittest.TestCase):
    def test_slot_clones_survive_lsh(self):
        pages = []
        for k in range(30):
            base = prose(1000 + k, 300).split()
            for side, city in enumerate(("Round Rock", "Cedar Park")):
                words = []
                for i, w in enumerate(base):
                    words.append(w)
                    if i % 25 == 0:
                        words.append(city)
                pages.append(core.Page(path=f"/s/d/pair{k}-{side}.html",
                                       url=f"{SITE}/d/pair{k}-{side}/", text=" ".join(words)))
        for n in range(40):
            pages.append(core.Page(path=f"/s/u/{n}.html", url=f"{SITE}/u/{n}/",
                                   text=prose(5000 + n, 300)))
        pairwise = checks.find_near_duplicates(pages, {"exact_below": 1000})
        lsh = checks.find_near_duplicates(pages, {"exact_below": 10})
        self.assertEqual(lsh["method_id"], "lsh")

        def found(result):
            return sorted((a.url, b.url) for a, b, j in result["pairs"] if j >= 0.8)

        self.assertEqual(len(found(pairwise)), 30)
        self.assertEqual(found(lsh), found(pairwise))


class TestStaleYearUnderPrefix(Site):
    def build(self, prefix):
        rent = "".join(f'<a href="{prefix}/rent/c{n}/">c{n}</a> ' for n in range(20))
        guides = "".join(f'<a href="{prefix}/guides/g{n}/">g{n}</a> ' for n in range(20))
        self.write("index.html", html("Home", f"<p>{prose(1, 60)}</p>{rent}{guides}"))
        for n in range(20):
            year = THIS_YEAR - 3 if n < 8 else THIS_YEAR
            self.write(f"rent/c{n}/index.html",
                       html(f"Renting in Town {n} {year}: rent and deposit",
                            f"<p>{prose(200 + n, 150)}</p>"))
            self.write(f"guides/g{n}/index.html",
                       html(f"Guide {n}", f"<p>{prose(300 + n, 150)}</p>"))

    def test_section_is_counted_from_the_site_path(self):
        self.build("/blog")
        data = self.check(SITE + "/blog")
        self.assertEqual(codes(data, "stale-year"), ["/blog/rent/"])

    def test_sections_are_told_apart(self):
        pages = [core.Page(path="", url=f"{SITE}/blog/{s}/p{n}/", title=f"Top {n} in 2023")
                 for s in ("rent", "jobs") for n in range(6)]
        found = signals.stale_years(pages, datetime.date(2026, 1, 1), base_path="/blog")
        self.assertEqual(sorted(i[1] for i in found), ["/blog/jobs/", "/blog/rent/"])

    def test_ignore_takes_a_section_path_from_the_site(self):
        issue = ("warning", "/blog/rent/", "stale-year", "x")
        kept, accepted = checks.apply_ignore([issue], {"stale-year": ["/rent/"]},
                                             SITE + "/blog")
        self.assertEqual((kept, accepted), ([], [issue]))


class TestNofollowHub(Site):
    def build(self, robots):
        kids = "".join(f'<a href="/rent/c{n}/">c{n}</a> ' for n in range(6))
        self.write("index.html", html("Home", f'<p>{prose(1, 80)}</p><a href="/rent/">Rent</a>'))
        head = f'<meta name="robots" content="{robots}">' if robots else ""
        self.write("rent/index.html", html("Rent", f"<p>{prose(2, 80)}</p>{kids}", head=head))
        for n in range(6):
            self.write(f"rent/c{n}/index.html", html(f"City {n}", f"<p>{prose(40 + n, 150)}</p>"))

    def test_children_behind_a_nofollow_hub_are_unreachable(self):
        kids = [f"{SITE}/rent/c{n}/" for n in range(6)]
        for robots in ("nofollow", "noindex, nofollow", "none"):
            with self.subTest(robots=robots):
                self.build(robots)
                data = self.check()
                self.assertEqual(codes(data, "unreachable"), kids)
                found = [i for i in data["issues"] if i["code"] == "unreachable"][0]
                self.assertIn("meta robots nofollow", found["message"])

    def test_follow_and_noindex_follow_stay_reachable(self):
        for robots in ("", "noindex, follow", "index, follow"):
            with self.subTest(robots=robots):
                self.build(robots)
                self.assertEqual(codes(self.check(), "unreachable"), [])

    def test_page_property(self):
        self.assertTrue(core.Page(path="", url=SITE, robots="NONE").nofollow)
        self.assertTrue(core.Page(path="", url=SITE, robots="noindex,nofollow").nofollow)
        self.assertFalse(core.Page(path="", url=SITE, robots="noindex, follow").nofollow)


class TestSkeletonWithSlot(unittest.TestCase):
    CITIES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]

    def pages(self, slotted):
        out = []
        for c in self.CITIES:
            tail = f" in {c}" if slotted else ""
            heads = [(1, f"Renting in {c}")] + [(2, h + tail) for h in
                                                ("What it costs", "Where to look", "What to bring")]
            out.append(core.Page(path="", url=f"{SITE}/rent/{c.lower()}/", headings=heads,
                                 text=prose(c, 60)))
        return out

    def test_city_in_every_heading_is_still_one_skeleton(self):
        for slotted in (False, True):
            with self.subTest(slotted=slotted):
                result = content.check_template_seams(self.pages(slotted))
                found = [i for i in result["issues"] if i[2] == "template-skeleton"]
                self.assertEqual(len(found), len(self.CITIES))
                self.assertEqual(len(result["repeated"]), 1)

    def test_heading_that_is_only_the_slot_does_not_match(self):
        pages = []
        for c in self.CITIES:
            pages.append(core.Page(path="", url=f"{SITE}/{c.lower()}/", text=prose(c, 60),
                                   headings=[(1, f"Guide to {c}"), (2, c), (2, f"{c} Hotel")]))
        self.assertEqual(content.check_template_seams(pages)["repeated"], [])

    def test_different_headings_stay_apart(self):
        pages = []
        for n, c in enumerate(self.CITIES):
            heads = [(1, f"Renting in {c}"), (2, f"{prose(n, 2)} in {c}"),
                     (2, f"{prose(n + 50, 2)} in {c}")]
            pages.append(core.Page(path="", url=f"{SITE}/rent/{c.lower()}/", headings=heads,
                                   text=prose(c, 60)))
        self.assertEqual(content.check_template_seams(pages)["repeated"], [])


class TestYearBeforePunctuation(unittest.TestCase):
    def test_comma_and_full_stop_end_a_phrase(self):
        p = signals._past_years
        self.assertEqual(p("Renting in Alpha in 2023, explained", 2026), {2023})
        self.assertEqual(p("The full guide for 2023.", 2026), {2023})
        self.assertEqual(p("Renting in Alpha 2023: rent", 2026), {2023})

    def test_numbers_are_still_not_years(self):
        p = signals._past_years
        self.assertEqual(p("version 2023.5 notes", 2026), set())
        self.assertEqual(p("2023,45 units sold", 2026), set())
        self.assertEqual(p("1.2023 rate", 2026), set())


class TestSkippedPageInTheReport(Site):
    def test_shared_url_is_in_json_and_html(self):
        self.write("index.html", html("Home", f'<p>{prose(1, 80)}</p><a href="/rent/">Rent</a>'))
        self.write("rent.html", html("Rent flat", f"<p>{prose(2, 80)}</p>"))
        self.write("rent/index.html", html("Rent", f"<p>{prose(3, 80)}</p>"))
        data = self.check()
        notes = [n for n in data["notes"] if "rent.html" in n]
        self.assertEqual(len(notes), 1, data["notes"])
        self.assertIn("rent.html", data["_html"])
        # В консоли — один раз, а не дважды.
        self.assertEqual(data["_console"].count(notes[0]), 1)


if __name__ == "__main__":
    unittest.main()
