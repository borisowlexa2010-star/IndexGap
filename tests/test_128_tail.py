# -*- coding: utf-8 -*-
"""
1.28: общий хвост шаблона — не подвал сайта.

Когда один шаблон занимал 90% страниц без `<main>`, `trimmed_words` считал
его неизменный текст подвалом и отрезал. Пятьдесят клонов с общим телом
выходили «похожими» и «шаблон близок к дублю», а стоило положить рядом пять
постов блога — «дублями». Теперь общее считается обвязкой, только если оно
стоит и вне каталога шаблона, размечено `<header>`/`<footer>`/`<nav>`/`<aside>`
или состоит из текстов ссылок. Подвал сайта по-прежнему отрезается.
"""

import os
import random
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

SITE = "https://demo.example"


def token(prefix, i):
    s, n = "", i
    for _ in range(4):
        s += "bcdfghjklmnprstvz"[n % 17] + "aeiou"[(n // 17) % 5]
        n //= 85
    return prefix + s


SHARED = [token("sa", i) for i in range(300)]
FOOTER_LINKS = ["About us", "Contact the team", "Privacy policy", "Terms of use",
                "Careers at the company", "Press and media", "Help centre",
                "Partner programme", "Accessibility statement", "Site map"]


class Builder:
    def __init__(self, case):
        self.root = tempfile.mkdtemp(prefix="indexgap-128-")
        case.addCleanup(shutil.rmtree, self.root, True)

    def page(self, path, title, words, before="", after=""):
        folder = os.path.join(self.root, path.strip("/"))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                     f'<title>{title}</title><link rel="canonical" href="{SITE}{path}">'
                     f'</head><body>{before}<h1>{title}</h1><p>{" ".join(words)}</p>'
                     f'{after}</body></html>')

    def run(self):
        pages, _ = core.load_pages(self.root, SITE)
        return pages, checks.run_all(pages, SITE + "/")


def codes(result):
    return {(i[0], i[2]) for i in result["issues"]}


def clones(b, count, unique=20, before="", after="", body=None):
    body = SHARED if body is None else body
    for c in range(count):
        own = [token(f"u{c}x", i) for i in range(unique)]
        b.page(f"/rent/city{c}/", f"Renting an apartment in city{c} today",
               body[:len(body) // 2] + own + body[len(body) // 2:], before, after)


def blog(b, count):
    r = random.Random(7)
    for f in range(count):
        b.page(f"/blog/post{f}/", f"Blog post number {f} about things",
               [token("f", r.randrange(10 ** 6)) for _ in range(320)])


def home(b, words=None, before="", after=""):
    b.page("/", "Home page of the example",
           words or [token("h", i) for i in range(300)], before, after)


def footer_div(extra=""):
    links = "".join(f'<a href="/{i}/">{t}</a> ' for i, t in enumerate(FOOTER_LINKS))
    return f'<div class="bottom">{links}{extra}</div>'


class TestTemplateTailIsText(unittest.TestCase):
    def verdict(self, extra_posts):
        b = Builder(self)
        clones(b, 50)
        blog(b, extra_posts)
        home(b)
        return codes(b.run()[1])

    def test_clones_are_duplicates_without_unrelated_pages(self):
        found = self.verdict(0)
        self.assertIn(("critical", "near-duplicate"), found)
        self.assertNotIn(("warning", "duplicate-risk"), found)

    def test_unrelated_pages_do_not_change_the_verdict(self):
        self.assertEqual({c for c in self.verdict(0) if c[1] in ("near-duplicate", "similar",
                                                                "duplicate-risk")},
                         {c for c in self.verdict(5) if c[1] in ("near-duplicate", "similar",
                                                                "duplicate-risk")})

    def test_ten_clones_and_one_extra_page(self):
        for extra in (0, 1):
            b = Builder(self)
            clones(b, 10)
            blog(b, extra)
            home(b)
            self.assertIn(("critical", "near-duplicate"), codes(b.run()[1]), extra)

    def test_body_tail_is_kept_in_trimmed_words(self):
        b = Builder(self)
        clones(b, 50)
        home(b)
        pages, _ = b.run()
        words = checks.trimmed_words(pages)
        page = next(p for p in pages if p.url.endswith("/rent/city1/"))
        self.assertEqual(len(words[page.url]), len(page.words))


class TestSiteChromeIsStillCut(unittest.TestCase):
    """Подвал сайта у шаблона из 90% страниц по-прежнему не сравнивается."""

    def distinct(self, b, count=50, before="", after=""):
        # Разные страницы одного каталога: свой текст у каждой, общий — только
        # обвязка. Дублем тут быть нечему.
        for c in range(count):
            own = [token(f"u{c}x", i) for i in range(60)]
            b.page(f"/rent/city{c}/", f"Renting an apartment in city{c} today",
                   own, before, after)

    def assert_quiet(self, result):
        found = codes(result)
        for code in ("near-duplicate", "duplicate-risk", "similar", "low-uniqueness"):
            self.assertFalse({c for c in found if c[1] == code}, (code, found))

    def long_footer(self):
        return " ".join(SHARED[:40])

    def test_footer_on_home_too_is_cut(self):
        b = Builder(self)
        after = f"<div>{self.long_footer()}</div>"
        self.distinct(b, after=after)
        home(b, after=after)
        pages, result = b.run()
        words = checks.trimmed_words(pages)
        page = next(p for p in pages if p.url.endswith("/rent/city1/"))
        self.assertNotIn(SHARED[0], words[page.url])
        self.assert_quiet(result)

    def test_footer_element_is_cut_when_home_has_its_own_layout(self):
        b = Builder(self)
        self.distinct(b, after=f"<footer>{self.long_footer()}</footer>")
        home(b)
        self.assert_quiet(b.run()[1])

    def test_role_contentinfo_is_cut(self):
        b = Builder(self)
        self.distinct(b, after=f'<div role="contentinfo">{self.long_footer()}</div>')
        home(b)
        self.assert_quiet(b.run()[1])

    def test_link_footer_in_plain_div_is_cut(self):
        b = Builder(self)
        self.distinct(b, after=footer_div() * 2)
        home(b)
        pages, result = b.run()
        words = checks.trimmed_words(pages)
        page = next(p for p in pages if p.url.endswith("/rent/city1/"))
        self.assertNotIn("privacy", words[page.url])
        self.assert_quiet(result)

    def test_header_without_nav_is_cut(self):
        b = Builder(self)
        menu = "<div>" + "".join(f'<a href="/{i}/">{t}</a> '
                                 for i, t in enumerate(FOOTER_LINKS * 2)) + "</div>"
        self.distinct(b, before=menu)
        home(b)
        self.assert_quiet(b.run()[1])

    def test_footer_on_a_page_with_main_counts(self):
        b = Builder(self)
        after = f"<div>{self.long_footer()}</div>"
        self.distinct(b, after=after)
        folder = os.path.join(b.root, "about")
        os.makedirs(folder)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(f'<!doctype html><html lang="en"><head><title>About the example</title>'
                     f'</head><body><main><h1>About</h1><p>{" ".join(token("a", i) for i in range(80))}'
                     f'</p></main>{after}</body></html>')
        home(b)
        self.assert_quiet(b.run()[1])

    def test_footer_after_template_tail_cuts_only_the_footer(self):
        # Общий хвост шаблона, а за ним подвал, который есть и на главной:
        # отрезается подвал, хвост шаблона остаётся текстом.
        b = Builder(self)
        foot = [token("ft", i) for i in range(40)]
        tail = [token("tt", i) for i in range(30)]
        for c in range(30):
            own = [token(f"u{c}x", i) for i in range(60)]
            b.page(f"/rent/city{c}/", f"Renting in city{c}", own + tail,
                   after=f"<div>{' '.join(foot)}</div>")
        home(b, after=f"<div>{' '.join(foot)}</div>")
        pages, _ = b.run()
        words = checks.trimmed_words(pages)
        page = next(p for p in pages if p.url.endswith("/rent/city1/"))
        self.assertEqual(words[page.url][-30:], tail)
        self.assertNotIn(foot[0], words[page.url])

    def test_no_page_outside_the_template_keeps_the_old_trim(self):
        b = Builder(self)
        clones(b, 30)
        pages, _ = b.run()
        words = checks.trimmed_words(pages)
        page = next(p for p in pages if p.url.endswith("/rent/city1/"))
        self.assertLess(len(words[page.url]), len(page.words))


class TestFramedText(unittest.TestCase):
    def load(self, body):
        root = tempfile.mkdtemp(prefix="indexgap-128-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(f"<html><head><title>T</title></head><body>{body}</body></html>")
        return core.load_pages(root, SITE)[0][0]

    def test_header_footer_nav_aside_are_framed(self):
        page = self.load("<header>Top bar</header><nav>Menu</nav><p>Body text</p>"
                         "<aside>Side</aside><footer>Bottom line</footer>")
        self.assertEqual(page.framed, "Top bar Menu Side Bottom line")
        self.assertIn("Body text", page.text)

    def test_page_with_main_has_nothing_framed(self):
        page = self.load("<header>Top</header><main><p>Body text here</p></main>"
                         "<footer>Bottom</footer>")
        self.assertEqual(page.framed, "")


if __name__ == "__main__":
    unittest.main()
