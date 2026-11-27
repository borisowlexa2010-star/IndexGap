# -*- coding: utf-8 -*-
"""
1.29 (g17): `check --baseline` и воронка `doctor`.

* распавшаяся группа noindex делала оставшиеся закрытыми страницы новыми
  критичными и «исчезнувшими» одновременно;
* у unfilled-slot, wrong-link-form и hub-missing-links не было полного
  предмета: четвёртое поле шаблона не было новым, а исправленное первое —
  было;
* находки выключенных --no-aeo / --no-content проверок считались «исчезло»;
* совет «передай тот же --dataset» при переданном датасете;
* испорченная база падала трассировкой с кодом 1;
* doctor: удалённые и закрытые страницы «вернулись в индекс», смена
  источника индекса и прогон без логов закрывали разрывы, robots.txt не
  считался закрытием, строки «Citations: 0» были цитатами, а две выгрузки
  цитирований затирали друг друга.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, doctor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_127_closed  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"
SHOP = "https://shop.example"


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, out.getvalue()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-129-g17-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)

    def demo(self, name):
        folder = self.p(name)
        shutil.copytree(DEMO, folder)
        return folder

    def edit(self, folder, rel, old, new):
        path = os.path.join(folder, *rel.split("/"))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new, 1))

    def check(self, folder, name, *extra):
        out = self.p(name, "r.json")
        code, text = run_cli("check", folder, "--site", SITE, "--out", out, *extra)
        with open(out, encoding="utf-8") as fh:
            return code, json.load(fh), text


class GroupDissolved(Tmp):
    def test_reopening_part_of_a_group_is_not_new_critical(self):
        s1, s2 = self.p("s1"), self.p("s2")
        test_127_closed.catalogue(s1, closed=3, per=7)
        test_127_closed.catalogue(s2, closed=3, per=7)
        for q in ("q00", "q01"):
            self.edit(s2, f"visa/c02/{q}/index.html",
                      '<meta name="robots" content="noindex">', "")
        self.check(s1, "o1")
        code, data, _ = self.check(s2, "o2", "--strict",
                                   "--baseline", self.p("o1", "r.json"))
        base = data["baseline"]
        self.assertFalse([i for i in base["new"] if i["level"] == "critical"])
        gone_noindex = [i for i in base["fixed"] if i["code"] == "noindex"]
        self.assertEqual(len(gone_noindex), 2)
        self.assertEqual(code, 0)


SLOTS3 = "<p>Rent {{rent}}, deposit {{deposit}}, commute {{commute}}.</p>"
SLOTS4 = "<p>Rent {{rent}}, deposit {{deposit}}, commute {{commute}}, city {{city}}.</p>"
HEAD = "<h2>How the search works</h2>"


class FullSubjects(Tmp):
    def test_fourth_unfilled_slot_is_new_and_fixing_one_is_not(self):
        u1, u2 = self.demo("u1"), self.demo("u2")
        self.edit(u1, "rent/berlin/index.html", HEAD, SLOTS3 + HEAD)
        self.edit(u2, "rent/berlin/index.html", HEAD, SLOTS4 + HEAD)
        self.check(u1, "uo1", "--dataset", os.path.join(u1, "cities.csv"))
        code, data, _ = self.check(u2, "uo2", "--strict", "--dataset",
                                   os.path.join(u2, "cities.csv"),
                                   "--baseline", self.p("uo1", "r.json"))
        self.assertEqual([i["code"] for i in data["baseline"]["new"]], ["unfilled-slot"])
        self.assertEqual(code, 1)
        slot = [i for i in data["issues"] if i["code"] == "unfilled-slot"][0]
        self.assertIn("«{{city}}»", slot["subject"])
        self.edit(u2, "rent/berlin/index.html", "Rent {{rent}}, ", "Rent $1,450, ")
        code, data, _ = self.check(u2, "uo3", "--strict", "--dataset",
                                   os.path.join(u2, "cities.csv"),
                                   "--baseline", self.p("uo2", "r.json"))
        self.assertEqual(data["baseline"]["new"], [])
        self.assertEqual(code, 0)

    def test_fourth_wrong_case_link_is_new_and_fixing_one_is_not(self):
        links = '<p><a href="/">All city guides</a></p>'
        three = ('<p><a href="/">All city guides</a> <a href="/About/">a</a> '
                 '<a href="/rent/Munich/">m</a> <a href="/rent/Hamburg/">h</a></p>')
        four = three.replace("</p>", ' <a href="/rent/Stuttgart/">s</a></p>')
        w1, w2 = self.demo("w1"), self.demo("w2")
        self.edit(w1, "rent/berlin/index.html", links, three)
        self.edit(w2, "rent/berlin/index.html", links, four)
        self.check(w1, "wo1")
        _, data, _ = self.check(w2, "wo2", "--baseline", self.p("wo1", "r.json"))
        self.assertEqual([i["code"] for i in data["baseline"]["new"]], ["wrong-link-form"])
        self.edit(w2, "rent/berlin/index.html", '<a href="/About/">a</a> ', "")
        _, data, _ = self.check(w2, "wo3", "--baseline", self.p("wo2", "r.json"))
        self.assertEqual(data["baseline"]["new"], [])

    def test_old_baseline_without_slot_subject_is_compared_by_text(self):
        u1 = self.demo("u1")
        self.edit(u1, "rent/berlin/index.html", HEAD, SLOTS4 + HEAD)
        self.check(u1, "b")
        path = self.p("b", "r.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for item in data["issues"]:
            if item["code"] == "unfilled-slot":
                item.pop("subject")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        _, data, _ = self.check(u1, "c", "--baseline", path)
        self.assertEqual(data["baseline"]["new"], [])


class SwitchedOffChecks(Tmp):
    def test_no_aeo_and_no_content_findings_are_unchecked_not_gone(self):
        d = self.demo("d")
        self.edit(d, "rent/berlin/index.html", HEAD, SLOTS3 + HEAD)
        dataset = os.path.join(d, "cities.csv")
        self.check(d, "d1", "--dataset", dataset)
        base = self.p("d1", "r.json")
        _, data, text = self.check(d, "na", "--dataset", dataset, "--no-aeo",
                                   "--baseline", base)
        self.assertEqual(data["baseline"]["fixed"], [])
        self.assertTrue(data["baseline"]["unchecked"])
        self.assertFalse(data["coverage"]["aeo"])
        self.assertIn("в этом прогоне", text)
        _, data, text = self.check(d, "nc", "--dataset", dataset, "--no-content",
                                   "--baseline", base)
        self.assertEqual(data["baseline"]["fixed"], [])
        codes = {i["code"] for i in data["baseline"]["unchecked"]}
        self.assertIn("unfilled-slot", codes)
        self.assertIn("--no-content", text)
        self.assertNotIn("Передай тот же --dataset", text)

    def test_profile_without_facts_names_the_profile(self):
        d = self.demo("d")
        dataset = os.path.join(d, "cities.csv")
        self.check(d, "d1", "--dataset", dataset)
        _, data, text = self.check(d, "pu", "--dataset", dataset, "--profile", "ugc",
                                   "--baseline", self.p("d1", "r.json"))
        self.assertTrue(data["baseline"]["facts_off"])
        self.assertIn("«ugc»", text)
        self.assertNotIn("Передай тот же --dataset", text)


class BrokenBaseline(Tmp):
    def test_malformed_entries_are_an_input_error(self):
        d = self.demo("d")
        self.check(d, "d1")
        with open(self.p("d1", "r.json"), encoding="utf-8") as fh:
            good = json.load(fh)
        for bad in ({"level": "critical", "url": SITE + "/", "code": ["orphan"], "message": "x"},
                    {"level": "critical", "url": 5, "code": "orphan", "message": "x"},
                    {"level": "critical", "url": SITE + "/", "code": "near-duplicate",
                     "message": 5},
                    {"level": "critical", "url": SITE + "/", "code": "near-duplicate",
                     "message": "x", "subject": ["a", ["b"]]}):
            data = dict(good, issues=[bad])
            path = self.p("bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            code, _ = run_cli("check", d, "--site", SITE, "--out", self.p("x", "r.json"),
                              "--baseline", path)
            self.assertEqual(code, 2, bad)


def shop(folder, noindex=(), drop=(), robots=""):
    """/rent/item0-9 и /buy/item0-9; `drop` — каких страниц нет в сборке."""
    paths = [f"/{s}/item{i}/" for s in ("rent", "buy") for i in range(10)]

    def page(path, title, links, shut=False):
        d = os.path.join(folder, path.strip("/"))
        os.makedirs(d, exist_ok=True)
        body = " ".join(f"Word{i} about {title} with facts and detail." for i in range(60))
        meta = '<meta name="robots" content="noindex">' if shut else ""
        a = "".join(f'<a href="{x}">{x}</a> ' for x in links)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(f'<!doctype html><html lang="en"><head><title>{title} page</title>'
                     f'<meta name="description" content="Description for {title}.">'
                     f'<link rel="canonical" href="{SHOP}{path}">{meta}</head><body>'
                     f'<h1>{title}</h1><p>{body}</p>{a}</body></html>')
    page("/", "Home", paths + ["/rent/", "/buy/"])
    for s in ("rent", "buy"):
        page(f"/{s}/", s, [p for p in paths if p.startswith(f"/{s}/")] + ["/"])
    for p in paths:
        if p not in drop:
            page(p, p.strip("/").replace("/", " "), ["/"], shut=p in noindex)
    if robots:
        with open(os.path.join(folder, "robots.txt"), "w", encoding="utf-8") as fh:
            fh.write(robots)
    return ["/", "/rent/", "/buy/"] + paths


class Funnel(Tmp):
    def files(self, all_paths):
        sm = self.p("sm.xml")
        with open(sm, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/'
                     'schemas/sitemap/0.9">' + "".join(
                         f"<url><loc>{SHOP}{p}</loc></url>" for p in all_paths) + "</urlset>")
        idx = self.p("idx.csv")
        with open(idx, "w", encoding="utf-8") as fh:
            fh.write("URL\n" + "".join(f"{SHOP}{p}\n" for p in all_paths
                                       if not p.startswith("/buy/item")))
        return sm, idx

    def doctor(self, folder, name, *extra):
        out = self.p(name + ".html")
        code, text = run_cli("doctor", folder, "--site", SHOP, "--out", out, *extra)
        with open(self.p(name + ".json"), encoding="utf-8") as fh:
            return json.load(fh), text

    def test_deleted_and_closed_pages_are_not_back_in_the_index(self):
        all_paths = shop(self.p("a"))
        sm, idx = self.files(all_paths)
        self.doctor(self.p("a"), "r1", "--sitemap", sm, "--indexed", "google=" + idx)
        gone = [f"/buy/item{i}/" for i in range(5)]
        shop(self.p("b"), drop=gone)
        shop(self.p("c"), noindex=gone)
        for folder in ("b", "c"):
            data, _ = self.doctor(self.p(folder), folder, "--sitemap", sm,
                                  "--indexed", "google=" + idx,
                                  "--baseline", self.p("r1.json"))
            self.assertEqual(data["baseline"]["recovered"], [], folder)

    def test_a_real_return_to_the_index_is_still_reported(self):
        all_paths = shop(self.p("a"))
        sm, idx = self.files(all_paths)
        self.doctor(self.p("a"), "r1", "--sitemap", sm, "--indexed", "google=" + idx)
        with open(idx, "a", encoding="utf-8") as fh:
            fh.write(f"{SHOP}/buy/item0/\n")
        data, _ = self.doctor(self.p("a"), "r2", "--sitemap", sm, "--indexed",
                              "google=" + idx, "--baseline", self.p("r1.json"))
        self.assertEqual(data["baseline"]["recovered"], [f"{SHOP}/buy/item0/"])

    def test_other_index_source_is_not_compared(self):
        all_paths = shop(self.p("a"))
        sm, idx = self.files(all_paths)
        self.doctor(self.p("a"), "r1", "--sitemap", sm, "--indexed", "google=" + idx)
        full = self.p("bing.csv")
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("URL\n" + "".join(f"{SHOP}{p}\n" for p in all_paths))
        data, text = self.doctor(self.p("a"), "r2", "--sitemap", sm, "--indexed",
                                 "bing=" + full, "--baseline", self.p("r1.json"))
        trend = data["baseline"]
        self.assertEqual(trend["recovered"], [])
        self.assertEqual(trend["segments"]["closed_gaps"], [])
        self.assertFalse([s for s in trend["steps"] if s["id"] == "indexed"])
        self.assertTrue(trend["index_sources"])
        self.assertIn("разных источников", text)

    def test_ai_gaps_are_not_closed_by_a_run_without_logs(self):
        trend = doctor.compare_runs(
            {"funnel": {}, "ai_segments": None},
            {"funnel": {}, "ai_segments": {"rows": [], "highlighted": [{"segment": "/buy/"}]}})
        self.assertEqual(trend["ai_segments"]["closed_gaps"], [])

    def test_robots_disallow_is_not_indexable(self):
        all_paths = shop(self.p("a"), robots="User-agent: *\nDisallow: /buy/\n")
        sm, idx = self.files(all_paths)
        data, _ = self.doctor(self.p("a"), "r1", "--sitemap", sm, "--indexed", "google=" + idx)
        funnel = data["funnel"]
        self.assertFalse([u for u in funnel["not_indexed"] if "/buy/" in u])
        self.assertEqual(len(funnel["robots_blocked"]), 11)
        self.assertFalse([c for c in data["causes"] if c["id"] == "unexplained"])
        listed = [p for p in all_paths if not p.startswith("/buy/")]
        sm2 = self.p("sm2.xml")
        with open(sm2, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/'
                     'schemas/sitemap/0.9">' + "".join(
                         f"<url><loc>{SHOP}{p}</loc></url>" for p in listed) + "</urlset>")
        data, _ = self.doctor(self.p("a"), "r2", "--sitemap", sm2, "--indexed", "google=" + idx)
        self.assertEqual(data["funnel"]["missing_from_sitemap"], [])
        self.assertFalse(data["segments"]["highlighted"])

    def test_zero_citations_are_not_citations_and_exports_add_up(self):
        all_paths = shop(self.p("a"))
        sm, idx = self.files(all_paths)
        jan, feb = self.p("jan.csv"), self.p("feb.csv")
        with open(jan, "w", encoding="utf-8") as fh:
            fh.write('"Page","Citations"\r\n'
                     f'"{SHOP}/rent/item0/","5"\r\n"{SHOP}/rent/item1/","0"\r\n'
                     f'"{SHOP}/buy/item1/","0"\r\n')
        with open(feb, "w", encoding="utf-8") as fh:
            fh.write(f'"Page","Citations"\r\n"{SHOP}/rent/item0/","3"\r\n')
        data, text = self.doctor(self.p("a"), "r1", "--sitemap", sm, "--indexed",
                                 "google=" + idx, "--indexed", jan, "--indexed", feb)
        cited = [s for s in data["funnel"]["steps"] if s["id"] == "cited"]
        self.assertEqual([s["count"] for s in cited], [1])
        self.assertEqual(data["funnel"]["cited_top"], [[f"{SHOP}/rent/item0/", 8]])
        self.assertIn("сложены", text)


if __name__ == "__main__":
    unittest.main()
