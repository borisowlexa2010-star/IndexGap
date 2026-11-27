# -*- coding: utf-8 -*-
"""
1.30, dups: большие группы клонов, полнота LSH и скелет шаблона.

* группа клонов до 200 страниц перебиралась попарно: 4 000 страниц — 99 с
  и 79 МБ JSON, 10 000 — почти 10 минут и 269 МБ, из них 202 МБ — пары;
* в JSON каждая пара группы писалась строкой, а предмет каждой находки —
  сотнями адресов;
* одна страница сверх 400 включала LSH и теряла пары клонов с тридцатью
  заменами из трёхсот слов;
* скелет шаблона пропадал, стоило адресам стать `/<город>-rent/` или
  `/<город>/` вместо `/rent-<город>/`.
"""

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
from indexgap import checks, cli, content, core

SITE = "https://demo.example"
VOCAB = ("river market station quarter harbour bridge tram museum park school hospital "
         "bakery office landlord deposit contract heating balcony kitchen garden street "
         "viewing folder payslip registration passport neighbour courtyard elevator garage "
         "bicycle library theatre square festival winter summer autumn spring").split()


def prose(seed, n, vocab=VOCAB):
    rnd = random.Random(seed)
    return [rnd.choice(vocab) for _ in range(n)]


def page(url, words):
    return core.Page(path=url, url=SITE + url, text=" ".join(words))


def clone(base, city, seed):
    """Текст шаблона: город через каждые двадцать слов и своё число."""
    rnd = random.Random(seed)
    out = []
    for i, w in enumerate(base):
        out.append(w)
        if i % 20 == 0:
            out.append(city)
        if i % 50 == 25:
            out.append(str(rnd.randint(100, 99999)))
    return out


def doc(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title} for the demo site</title>'
            f'<meta name="description" content="{title}: a page of the demo site '
            'written to test how templates are found on a larger site.">'
            f'</head><body><main><h1>{title}</h1>{body}</main></body></html>')


def write(root, path, html):
    target = os.path.join(root, path.strip("/"), "index.html") if path.strip("/") \
        else os.path.join(root, "index.html")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(html)


def run_check(folder, *extra):
    out = os.path.join(folder, "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        try:
            cli.main(["check", folder, "--site", SITE, "--out", out, "--no-aeo", *extra])
        except SystemExit:
            pass
    with open(out, encoding="utf-8") as fh:
        return json.load(fh), printed.getvalue()


class LargeCloneGroups(unittest.TestCase):
    """#161, #396: группа клонов стоит линейно, а дубли — те же."""

    def site(self, n, extra=0):
        base = prose(1, 400)
        pages = [page(f"/rent/c{i:04d}/", clone(base, f"Town{i}", i)) for i in range(n)]
        # Свои страницы рядом: ни с кем не похожи, их сравнения никто не пропускает.
        pages += [page(f"/blog/p{i:03d}/", prose(1000 + i, 300)) for i in range(extra)]
        return pages

    def test_pairwise_group_is_compared_against_a_sample(self):
        pages = self.site(120, extra=10)
        got = checks.find_near_duplicates(pages)
        self.assertEqual(got["method_id"], "pairwise")
        near = {u for a, b, j in got["pairs"] if j >= 0.8 for u in (a.url, b.url)}
        # Каждая страница группы — дубль, как и при полном переборе.
        self.assertEqual(near, {p.url for p in pages if "/rent/" in p.url})
        # А пар не 7 140, а линейно от размера группы.
        self.assertLess(len(got["pairs"]), 30 * 29 // 2 + 120 + 1)
        self.assertIn("сравнивались с образцом", " ".join(got["notes"]))

    def test_lsh_group_of_two_hundred_is_linear_and_finds_the_same_pages(self):
        pages = self.site(200, extra=40)
        got = checks.find_near_duplicates(pages, {"exact_below": 50})
        exact = checks.find_near_duplicates(pages, {"exact_below": 10 ** 6})
        self.assertEqual(got["method_id"], "lsh")
        flagged = lambda r: {u for a, b, j in r["pairs"] if j >= 0.8 for u in (a.url, b.url)}
        self.assertEqual(flagged(got), flagged(exact))
        self.assertEqual(len(flagged(got)), 200)
        self.assertLess(len(got["pairs"]), 1000)        # было 19 900

    def test_findings_per_page_match_a_full_comparison(self):
        # Два шаблона и цепочка «похожих»: находки и их уровни — как у
        # полного перебора, меняются только пары внутри группы.
        base_a, base_b = prose(2, 400), prose(3, 400)
        pages = [page(f"/rent/a{i:03d}/", clone(base_a, f"Alpha{i}", i)) for i in range(45)]
        pages += [page(f"/buy/b{i:03d}/", clone(base_b, f"Beta{i}", 500 + i)) for i in range(8)]
        pages += [page(f"/blog/p{i:02d}/", prose(900 + i, 300)) for i in range(6)]
        result = checks.run_all(pages, SITE + "/")
        codes = {(i[1], i[2]) for i in result["issues"] if i[2] in ("near-duplicate", "similar")}
        expected = {(p.url, "near-duplicate") for p in pages if "/blog/" not in p.url}
        self.assertEqual(codes, expected)
        # Группа из 45 — составом, группа из 8 — попарно, как раньше.
        groups = checks.duplicate_groups(result["duplicates"])
        self.assertEqual([len(g) for g in groups], [45])
        small = [(a.url, b.url) for a, b, j in result["duplicates"] if "/buy/" in a.url]
        self.assertEqual(len(small), 8 * 7 // 2)
        self.assertLess(len(result["duplicates"]), 45 * 44 // 2)


class GroupsInJson(unittest.TestCase):
    """#161, #396: JSON держит группу составом, предмет укорочен с числом."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-130-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def build(self, root, slugs):
        base = prose(5, 300)
        links = []
        for n, slug in enumerate(slugs):
            words = clone(base, f"Town{slug}", n)
            body = "<p>" + " ".join(words) + '</p><p><a href="/">Home</a></p>'
            write(root, f"rent/{slug}", doc(f"Renting in Town{slug}", body))
            links.append(f'<a href="/rent/{slug}/">Town{slug}</a>')
        write(root, "", doc("All cities", "<p>" + " ".join(prose(9, 200)) + "</p>"
                            + " ".join(links)))
        return root

    def test_group_is_written_by_members_and_subject_is_capped(self):
        slugs = [f"c{i:03d}" for i in range(60)]
        data, printed = run_check(self.build(os.path.join(self.dir, "a"), slugs))
        groups = data["duplicate_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["size"], 60)
        self.assertEqual(groups[0]["id"], SITE + "/rent/c000/")
        self.assertEqual(len(groups[0]["members"]), 60)
        # Пары внутри группы строками не пишутся.
        inside = set(groups[0]["members"])
        self.assertFalse([d for d in data["duplicates"]
                          if d["a"] in inside and d["b"] in inside])
        self.assertGreaterEqual(data["duplicate_pairs"], 59)
        near = [i for i in data["issues"] if i["code"] == "near-duplicate"]
        self.assertEqual(len(near), 60)
        for item in near:
            self.assertEqual(len(item["subject"]), checks.SUBJECT_CAP)
            self.assertEqual(item["subject_total"], 59)
            self.assertIn("ещё 58", item["message"])

    def test_added_clone_is_the_only_new_finding(self):
        old = self.build(os.path.join(self.dir, "old"), [f"c{i:03d}" for i in range(60)])
        before, _ = run_check(old)
        # Новый клон сортируется первым: окно предмета сдвигается у всех.
        new = self.build(os.path.join(self.dir, "new"), ["a000"] + [f"c{i:03d}" for i in range(60)])
        after, _ = run_check(new, "--baseline", os.path.join(old, "r.json"))
        fresh = {i["url"] for i in after["baseline"]["new"]}
        self.assertEqual(fresh, {SITE + "/rent/a000/"})
        self.assertEqual(after["baseline"]["fixed"], [])
        # База старого формата — предмет полным списком близнецов — тоже
        # сравнима: новых находок нет.
        legacy = json.loads(json.dumps(before))
        members = sorted(core.url_key(u) for u in before["duplicate_groups"][0]["members"])
        for item in legacy["issues"]:
            if item["code"] == "near-duplicate":
                item["subject"] = [m for m in members if m != core.url_key(item["url"])]
                item.pop("subject_total", None)
        path = os.path.join(self.dir, "legacy.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh)
        again, _ = run_check(old, "--baseline", path)
        self.assertEqual(again["baseline"]["new"], [])


class SlotClonesAbove400(unittest.TestCase):
    """#411: одна страница сверх 400 не должна терять пары клонов."""

    def pages(self, total, pairs=190, swapped=28):
        r = random.Random(42)
        vocab = ["".join(r.choice("abcdefghijklmnoprstuvw") for _ in range(r.randint(4, 9)))
                 for _ in range(5000)]
        out = []
        for i in range(pairs):
            a = [r.choice(vocab) for _ in range(300)]
            b = list(a)
            for pos in r.sample(range(300), r.randint(swapped, swapped + 6)):
                b[pos] = r.choice(vocab)
            out += [page(f"/g/p{i:04d}a/", a), page(f"/g/p{i:04d}b/", b)]
        while len(out) < total:
            out.append(page(f"/g/u{len(out):04d}/", [r.choice(vocab) for _ in range(300)]))
        return out

    def test_one_more_page_keeps_every_near_duplicate(self):
        near = lambda r: sum(1 for _a, _b, j in r["pairs"] if j >= 0.8)
        exact = checks.find_near_duplicates(self.pages(400))
        lsh = checks.find_near_duplicates(self.pages(401))
        self.assertEqual((exact["method_id"], lsh["method_id"]), ("pairwise", "lsh"))
        self.assertEqual(near(lsh), near(exact))


class SkeletonBySlugShape(unittest.TestCase):
    """#412: скелет шаблона не зависит от того, где в адресе стоит город."""

    CITIES = ["berlin", "munich", "hamburg", "cologne", "frankfurt", "stuttgart"]

    def pages(self, slug, blog=20, blog_slug=lambda i: f"/post-{i}/"):
        out = []
        for i, c in enumerate(self.CITIES):
            p = page(slug(c), prose(100 + i, 300))
            p.headings = [(1, f"Renting in {c}"), (2, "How the search works"),
                          (2, "What to bring to a viewing"), (2, "When to search")]
            out.append(p)
        for i in range(blog):
            p = page(blog_slug(i), prose(500 + i, 300))
            one, two = prose(700 + i, 2), prose(800 + i, 2)
            p.headings = [(1, f"Post {i}"), (2, " and ".join(one)), (2, " or ".join(two))]
            out.append(p)
        return out

    def stamped(self, pages):
        got = content.check_template_seams(pages)["issues"]
        return sorted(url for _l, url, code, _m in got if code == "template-skeleton")

    def test_shared_suffix_is_a_section(self):
        pages = self.pages(lambda c: f"/{c}-rent/")
        self.assertEqual(self.stamped(pages), sorted(SITE + f"/{c}-rent/" for c in self.CITIES))

    def test_bare_slugs_need_a_clear_majority_of_their_level(self):
        pages = self.pages(lambda c: f"/{c}/")
        self.assertEqual(self.stamped(pages), sorted(SITE + f"/{c}/" for c in self.CITIES))
        # Обычный блог на голых адресах: шесть страниц с одним скелетом среди
        # двадцати статей со своими адресами — не раздел.
        words = "cook travel garden money health code music photo film book".split()
        blog = self.pages(lambda c: f"/{c}/",
                          blog_slug=lambda i: f"/{words[i % 10]}-{words[(i * 3 + 1) % 10]}-{i}/")
        self.assertEqual(self.stamped(blog), [])

    def test_bare_slugs_with_two_headings_are_not_a_section(self):
        # «Введение, Итоги» бывает у любых статей: голым адресам нужен
        # скелет от трёх заголовков, а не два общих.
        pages = self.pages(lambda c: f"/{c}/")
        for p in pages[:6]:
            p.headings = p.headings[:3]
        self.assertEqual(self.stamped(pages), [])
        pages = self.pages(lambda c: f"/{c}/")
        self.assertEqual(len(self.stamped(pages)), 6)


if __name__ == "__main__":
    unittest.main()
