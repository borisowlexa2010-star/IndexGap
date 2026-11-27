# -*- coding: utf-8 -*-
"""
1.29, g10: клоны шаблона, которые сходство по шинглам прятало.

* дорвей, где город стоит через каждые пять слов, — сходство 0,1, ниже
  порога перепроверки, и ни одной находки;
* подстановки разной длины («Austin» и «St. Louis», «Ростове-на-Дону» и
  «Уфе») не выравнивались после маскировки;
* список соседних городов простым текстом с одним городом из двух слов;
* региональные версии, убранные из дублей, считались «похожими парами»;
* в режиме LSH пары клонов с тридцатью подстановками терялись целиком;
* база, снятая попарно, против прогона LSH: пропавшие дубли — не исправления.
"""

import io
import json
import os
import random
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, core

SITE = "https://example.com"


def html(title, body, head="", lang="en"):
    return (f"<!doctype html><html lang=\"{lang}\"><head><meta charset=\"utf-8\">"
            f"<title>{title}</title>{head}</head><body><main><h1>{title}</h1>{body}"
            "</main></body></html>")


class Site(unittest.TestCase):
    def build(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-g10-")
        self.addCleanup(shutil.rmtree, root, True)
        for path, text in files.items():
            full = os.path.join(root, path.strip("/"), "index.html")
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)
        return root

    def pairs(self, files):
        pages = core.load_pages(self.build(files), SITE)[0]
        words = checks.trimmed_words(pages)
        return checks.find_near_duplicates(pages, checks.CONFIG, words)["pairs"]

    def near(self, pairs):
        return {(a.url, b.url) for a, b, j in pairs if j >= checks.CONFIG["near_duplicate"]}


DOORWAY = ("<p>Need a plumber in {c}? Our {c} plumbers serve all of {c}, {st}. A typical "
           "call-out in {c} costs ${p} and an hourly rate in {st} is ${h}.</p>"
           "<p>Every {c} plumber we list is licensed in {st} and insured. Call a {c} plumber "
           "today for leaks, drains, water heaters and burst pipes in {c}.</p>"
           "<p>Emergency plumbing in {c} is available around the clock. Compare {c} quotes, "
           "read {c} reviews and book a {c} plumber online in minutes.</p>")
DOORWAY_CITIES = [("alpha", "Alphaville", "Northland", 120, 45),
                  ("beta", "Betatown", "Southland", 130, 50),
                  ("gamma", "Gammaburg", "Eastland", 140, 55),
                  ("delta", "Deltaport", "Westland", 150, 60)]


class DoorwayBelowFloor(Site):
    def test_slot_every_few_words_is_still_a_near_duplicate(self):
        files = {f"/city/{s}/": html(f"Plumbers in {c}", DOORWAY.format(c=c, st=st, p=p, h=h))
                 for s, c, st, p, h in DOORWAY_CITIES}
        self.assertEqual(len(self.near(self.pairs(files))), 6)

    def test_same_words_in_another_order_are_not(self):
        r = random.Random(7)
        base = ("copper pipes last for decades but cost more to install and need a skilled "
                "plumber with soldering tools while plastic ones are cheap").split() * 4
        files = {}
        for name in ("one", "two"):
            words = base[:]
            r.shuffle(words)
            files[f"/guide/{name}/"] = html("Pipes guide " + name, "<p>" + " ".join(words) + "</p>")
        self.assertEqual(self.near(self.pairs(files)), set())


TEMPLATE = ("<p>Looking for a reliable plumber in {c}, {st}? We list licensed and insured "
            "professionals in {c} who handle leaks, blocked drains, water heaters and burst "
            "pipes.</p><p>A typical call-out in {c} costs a fixed fee, and rates in {st} rise "
            "at night and on public holidays, so ask {c} plumbers for a written quote before "
            "the work starts.</p><p>Most plumbers in {c} answer within the hour. Before you "
            "call, find the main water valve and take a photo of the problem; it saves time on "
            "the first visit to your {c} home.</p><p>Every {c} company on this list holds a "
            "{st} licence. Read recent {c} reviews, compare at least three quotes and keep the "
            "receipt.</p>")


class SlotsOfDifferentLength(Site):
    def test_one_word_and_three_word_cities_align(self):
        cities = [("a", "Alphaville", "Northland"), ("b", "Port Beta Bay", "Southland"),
                  ("c", "Gamma", "Eastland"), ("d", "Mount Delta", "Westland")]
        files = {f"/city/{s}/": html(f"Plumbers in {c}", TEMPLATE.format(c=c, st=st))
                 for s, c, st in cities}
        pairs = self.pairs(files)
        self.assertEqual(len(self.near(pairs)), 6, [(a.url, b.url, j) for a, b, j in pairs])

    def test_shared_word_inside_a_slot_is_part_of_it(self):
        body = ("<p>Ищете сантехника в {c}? Мы собрали проверенных мастеров, которые устраняют "
                "протечки, прочищают засоры и меняют трубы в квартирах и офисах.</p><p>Вызов "
                "мастера в {c} стоит фиксированную сумму, а час работы оплачивается отдельно. "
                "Ночью цены выше, поэтому попросите письменную смету до начала работ.</p>"
                "<p>Большинство мастеров в {c} приезжают в течение часа. Перед звонком найдите "
                "главный кран и сфотографируйте проблему.</p>")
        files = {"/city/one/": html("Сантехники", body.format(c="Верхне-на-Озёрске"), lang="ru"),
                 "/city/two/": html("Сантехники", body.format(c="Лесном"), lang="ru")}
        pairs = self.pairs(files)
        self.assertEqual([j for _a, _b, j in pairs], [1.0])


class PlainTextNearbyList(Site):
    def test_multi_word_town_in_a_plain_list_is_a_slot(self):
        body = ("<p>Looking for a reliable plumber in {c}? We have collected licensed and insured "
                "professionals who handle leaks, blocked drains, water heaters and burst pipes "
                "for homes and small businesses.</p><p>A typical call-out costs about ${p}, and "
                "the usual hourly rate in {st} is ${h}. Prices rise at night and on public "
                "holidays, so ask for a written quote before the work starts and check that the "
                "quote includes parts.</p><p>Most {c} plumbers answer within the hour. Before "
                "you call, find the main water valve, take a photo of the problem and note the "
                "age of your water heater; it saves time and money on the first visit.</p>"
                "<p>Every company on this list holds a {st} licence. Read recent reviews, compare "
                "at least three quotes and keep the receipt for the warranty on parts and "
                "labour.</p><p>We also cover nearby towns: {near}.</p>")
        rows = [("a", "Alphaville", "Northland", 120, 45, "Red Hill, Cedar Vale, Oakford and Elmton"),
                ("b", "Betatown", "Southland", 130, 50, "Ashby, Birchley, Corton and Dunmore"),
                ("c", "Gammaburg", "Eastland", 140, 55, "Fenwick, Galton, Harley and Ivybridge")]
        files = {f"/city/{s}/": html(f"Plumbers in {c}",
                                     body.format(c=c, st=st, p=p, h=h, near=near))
                 for s, c, st, p, h, near in rows}
        pairs = self.pairs(files)
        self.assertEqual(len(self.near(pairs)), 3, [(a.url, b.url, j) for a, b, j in pairs])


class RegionalPairsAreNotSimilarPairs(Site):
    def test_regional_versions_stay_out_of_duplicates(self):
        regions = [("us", "en-US", "$120"), ("gb", "en-GB", "£95"), ("au", "en-AU", "A$180")]
        alts = "".join(f'<link rel="alternate" hreflang="{code}" href="{SITE}/{r}/drains/">'
                       for r, code, _ in regions)
        text = ("<p>Our drain cleaning service sends a licensed plumber to your home within the "
                "hour. A standard call-out costs {p}. Prices rise at night and on public "
                "holidays, so ask for a written quote before the work starts.</p>") * 4
        files = {f"/{r}/drains/": html("Drain cleaning", text.format(p=p), alts, lang=code)
                 for r, code, p in regions}
        files["/"] = html("Home", "<p>" + " ".join(
            f'<a href="/{r}/drains/">{r}</a>' for r, _, _ in regions) + "</p>")
        pages = core.load_pages(self.build(files), SITE)[0]
        result = checks.run_all(pages, SITE + "/")
        self.assertEqual(result["duplicates"], [])
        self.assertFalse([i for i in result["issues"] if i[2] in ("near-duplicate", "similar")])


class LshRecall(unittest.TestCase):
    def test_slot_clone_pairs_are_found_like_pairwise(self):
        vocab = [f"w{i}" for i in range(5000)]
        pages = []
        for g in range(150):
            r = random.Random(100 + g)
            base = [r.choice(vocab) for _ in range(300)]
            for m in range(2):
                words = []
                for i, w in enumerate(base):
                    words.append(w)
                    if i % 10 == 0:
                        words.append(f"g{g}v{m}n{i}")
                pages.append(core.Page(path=f"/t{g:03d}/p{m}/", url=f"{SITE}/t{g:03d}/p{m}/",
                                       text=" ".join(words)))
        got = checks.find_near_duplicates(pages, {"exact_below": 10})
        self.assertEqual(got["method_id"], "lsh")
        near = [j for _a, _b, j in got["pairs"] if j >= checks.CONFIG["near_duplicate"]]
        # Попарно находятся все 150; полосы — вероятность, но не три четверти.
        self.assertGreaterEqual(len(near), 145)


class BaselineMethodChange(Site):
    def test_method_change_is_said_out_loud(self):
        root = self.build({"/": html("Home", "<p>" + "Plain words about the site. " * 40 + "</p>")})
        out = tempfile.mkdtemp(prefix="indexgap-g10-out-")
        self.addCleanup(shutil.rmtree, out, True)
        base = os.path.join(out, "base.json")
        with redirect_stdout(io.StringIO()):
            cli.main(["check", root, "--site", SITE, "--no-aeo", "--out", base])
        with open(base, encoding="utf-8") as fh:
            data = json.load(fh)
        data["duplicate_method"] = "lsh"
        data["issues"].append({"level": "critical", "url": SITE + "/gone/",
                               "code": "near-duplicate", "message": "x"})
        with open(base, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["check", root, "--site", SITE, "--no-aeo",
                      "--out", os.path.join(out, "now.json"), "--baseline", base])
        self.assertIn("база искала дубли методом «lsh»", buf.getvalue())
        self.assertIn("из исчезнувших 1", buf.getvalue())
        with open(os.path.join(out, "now.json"), encoding="utf-8") as fh:
            now = json.load(fh)
        self.assertEqual(now["baseline"]["duplicate_method_changed"][0], "lsh")


if __name__ == "__main__":
    unittest.main()
