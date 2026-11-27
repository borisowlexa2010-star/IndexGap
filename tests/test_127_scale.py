# -*- coding: utf-8 -*-
"""
1.27: поведение на больших сайтах.

* LSH: переполненная корзина сравнивалась только с первым по алфавиту адресом.
  Близнец каждой страницы зависел от выборки — удалили одну страницу, и
  --baseline называл новой каждую находку группы. Корзина, переполненная
  общим словарём, теряла настоящие пары клонов и при этом печатала заметку
  «группы оказались похожи» на сайте без единой похожей пары.
* Шаблонность по разделу не работала для плоских адресов `/rent-alpha/`.
* Проверка одинакового начала текста была квадратичной.
"""

import io
import json
import os
import random
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, content, core

SITE = "https://demo.example"

VOCABULARY = ("river market station quarter harbour bridge tram museum park school "
              "hospital bakery office landlord deposit contract heating balcony "
              "kitchen garden street viewing folder payslip registration passport "
              "neighbour courtyard elevator garage bicycle library theatre square "
              "festival winter summer autumn spring rain wind snow sunshine cafe "
              "restaurant gallery").split()


def prose(seed, n):
    rnd = random.Random(seed)
    return [rnd.choice(VOCABULARY) for _ in range(n)]


def page(url, words):
    return core.Page(path=url, url=SITE + url, text=" ".join(words))


def run_check(folder, *extra):
    out = os.path.join(folder, "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        try:
            cli.main(["check", folder, "--site", SITE, "--out", out, *extra])
        except SystemExit:
            pass
    with open(out, encoding="utf-8") as fh:
        return json.load(fh), printed.getvalue()


def write(root, path, html):
    target = os.path.join(root, path, "index.html") if path else os.path.join(root, "index.html")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(html)


def doc(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{title} for the demo site</title>'
            f'<meta name="description" content="{title}: a page of the demo site '
            'written to test how templates are found on a larger site.">'
            f'</head><body><main><h1>{title}</h1>{body}</main></body></html>')


class SharedVocabulary(unittest.TestCase):
    """Все страницы написаны одним словарём: корзина полос по словам переполнена."""

    def pages(self, filler):
        out = []
        for k in range(12):
            base = prose(1000 + k, 300)
            for side, city in enumerate(("Alpha", "Beta")):
                words = []
                for i, w in enumerate(base):
                    words.append(w)
                    if i % 25 == 0:
                        words.append(city)
                out.append(page(f"/pair/{k:02d}-{side}/", words))
        for n in range(filler):
            out.append(page(f"/town/{n:04d}/", prose(5000 + n, 300)))
        return out

    def test_clone_pairs_are_not_lost(self):
        pages = self.pages(230)
        got = checks.find_near_duplicates(pages, {"exact_below": 50})
        self.assertEqual(got["method_id"], "lsh")
        dupes = {(a.url, b.url) for a, b, j in got["pairs"] if j >= 0.8}
        exact = checks.find_near_duplicates(pages, {"exact_below": 100000})
        self.assertEqual(dupes, {(a.url, b.url) for a, b, j in exact["pairs"] if j >= 0.8})
        self.assertEqual(len(dupes), 12)

    def test_no_alike_note_without_alike_pages(self):
        pages = [page(f"/town/{n:04d}/", prose(5000 + n, 300)) for n in range(260)]
        got = checks.find_near_duplicates(pages, {"exact_below": 50})
        self.assertEqual(got["method_id"], "lsh")
        self.assertEqual(got["pairs"], [])
        self.assertEqual(got["notes"], [])
        self.assertFalse(got["sampled_urls"])


class CloneGroupBaseline(unittest.TestCase):
    """Группа клонов больше корзины: удалили одну страницу — новых находок нет."""

    def build(self, root, skip=()):
        links = []
        for i in range(230):
            slug = f"city-{i:04d}"
            if slug in skip:
                continue
            body = (f"<p>A flat in Town{i} costs about {1000 + i} a month.</p>"
                    + "".join("<p>" + " ".join(prose(k, 60)) + ".</p>" for k in range(5))
                    + '<p><a href="/">Home</a></p>')
            write(root, f"rent/{slug}", doc(f"Renting in Town{i}", body))
            links.append(f'<a href="/rent/{slug}/">Town{i}</a>')
        write(root, "", doc("All cities", "<p>" + " ".join(prose(1, 200)) + "</p>" + " ".join(links)))
        with open(os.path.join(root, "indexgap.json"), "w") as fh:
            json.dump({"checks": {"exact_below": 50}}, fh)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-127-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_removed_clone_gives_no_new_findings(self):
        old, new = os.path.join(self.dir, "old"), os.path.join(self.dir, "new")
        self.build(old)
        self.build(new, skip={"city-0000"})
        config = os.path.join(old, "indexgap.json")
        before, printed = run_check(old, "--no-aeo", "--config", config)
        self.assertEqual(before["duplicate_method"], "lsh")
        self.assertTrue(before["duplicates_sampled"])
        self.assertIn("выборка", printed)
        after, _ = run_check(new, "--no-aeo", "--config", config,
                             "--baseline", os.path.join(old, "r.json"))
        self.assertEqual(after["baseline"]["new"], [])
        gone = [i for i in after["baseline"]["fixed"] if i["code"] == "near-duplicate"]
        self.assertEqual([i["url"] for i in gone], [SITE + "/rent/city-0000/"])

    def test_pairwise_subject_still_compared(self):
        # Попарный режим не изменился: сменившийся близнец — новая находка.
        issue = ("critical", SITE + "/a/", "near-duplicate", "x")
        old = [{"level": "critical", "url": SITE + "/a/", "code": "near-duplicate",
                "message": "x", "subject": ["//demo.example/b"]}]
        from indexgap.subject import Said
        moved = (issue[0], issue[1], issue[2], Said("x", ["//demo.example/c"]))
        self.assertEqual(len(cli.compare_baseline([moved], old)["new"]), 1)


class FlatSection(unittest.TestCase):
    """Плоские адреса `/rent-cityN/` рядом с блогом: раздел — общее начало адреса."""

    def build(self, root, layout, guides):
        heads = ["What it costs", "Where to look", "How long it takes",
                 "Who to call", "What to bring"]
        opening = ("Renting a flat here starts with the same short checklist that "
                   "every tenant should read before signing anything at all.")
        links = []
        for n in range(20):
            body = f"<p>{opening}</p>" + "".join(
                f"<h2>{h}</h2><p>Text {n} about {h.lower()} here. "
                + " ".join(f"u{n}x{h[:3]}{k}" for k in range(40)) + "</p>" for h in heads)
            path = f"rent-city{n}" if layout == "flat" else f"rent/city{n}"
            links.append(path)
            write(root, path, doc(f"Renting in city{n}", body + '<a href="/">Home</a>'))
        for n in range(guides):
            body = (f"<p>Guide number {n} opens with its own sentence about topic {n} today.</p>"
                    f"<h2>Guide {n} part one</h2><p>Own words {n} for the first part.</p>"
                    f"<h2>Guide {n} part two</h2><p>More own words {n} for this guide.</p>")
            write(root, f"blog/g{n}", doc(f"Guide {n}", body + '<a href="/">Home</a>'))
            links.append(f"blog/g{n}")
        write(root, "", doc("Home", "<p>Home page words for this small demo site.</p>"
                            + "".join(f'<a href="/{x}/">{x}</a> ' for x in links)))

    def codes(self, layout, guides):
        root = tempfile.mkdtemp(prefix="indexgap-127-")
        self.addCleanup(shutil.rmtree, root, True)
        self.build(root, layout, guides)
        pages, _ = core.load_pages(root, SITE)
        got = content.check_template_seams(pages)
        return {code for _, _, code, _ in got["issues"]}

    def test_flat_like_nested(self):
        for guides in (20, 70):
            with self.subTest(guides=guides):
                self.assertEqual(self.codes("nested", guides),
                                 {"template-skeleton", "same-opening"})
                self.assertEqual(self.codes("flat", guides),
                                 {"template-skeleton", "same-opening"})

    def test_flat_slug_section_size(self):
        pages = [core.Page(path=u, url=SITE + u) for u in
                 ("/rent-a/", "/rent-b/", "/rent-c/", "/buy-a/", "/buy-b/", "/rent/", "/blog/x/")]
        size, name = content._section_counter(pages)([SITE + "/rent-a/", SITE + "/rent-b/"])
        # Страница-хаб /rent/ входит в раздел, как /rent/ во вложенной раскладке.
        self.assertEqual((size, name), (4, "/rent-"))
        # Разные начала и концы у страниц верхнего уровня — раздела нет.
        size, _ = content._section_counter(pages)([SITE + "/rent-a/", SITE + "/buy-b/"])
        self.assertEqual(size, 0)
        # С 1.30 общий конец адреса — тоже раздел (`/alpha-rent/`).
        size, name = content._section_counter(pages)([SITE + "/rent-a/", SITE + "/buy-a/"])
        self.assertEqual((size, name), (2, "/*-a/"))


class OpeningsScale(unittest.TestCase):
    """Тысячи страниц с разным началом текста — без перебора всего сайта на каждую."""

    def test_unique_openings_are_cheap(self):
        pages = [core.Page(path=f"/rent/c{i}/", url=f"{SITE}/rent/c{i}/",
                           text=f"A flat in Town{i} costs about {i} a month and the "
                                "deposit is two months of rent paid upfront.",
                           paragraphs=[f"A flat in Town{i} costs about {i} a month and the "
                                       "deposit is two months of rent paid upfront."])
                 for i in range(6000)]
        start = time.time()
        got = content.check_template_seams(pages)
        self.assertLess(time.time() - start, 10)
        self.assertFalse([i for i in got["issues"] if i[2] == "same-opening"])


if __name__ == "__main__":
    unittest.main()
