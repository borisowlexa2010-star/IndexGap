# -*- coding: utf-8 -*-
"""
1.29 (g19): сравнение прогонов doctor, история и портфель.

* страница, ушедшая из воронки раньше (noindex, удалена), — не «вернулась в индекс»;
* другой набор источников индекса — не сравнивается;
* логи только в одном прогоне — шаг ИИ-поиска не сравнивается;
* битые файлы истории не роняют прогон; порядок — по времени с поясом;
* легенда trend.html помечает значение не из последнего прогона;
* портфель: колонка ключа, robots/sitemap с опечаткой, hreflang из sitemap,
  чужой файл в `out`, совпадающие имена отчётов, уровень общего шаблона,
  незнакомые поля проекта, огромный grace_days.
"""

import contextlib
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, doctor, history, portfolio, settings
from indexgap.core import SourceError

SITE = "https://example.com"


def funnel(**kw):
    f = {"steps": [], "has_index": True, "has_sitemap": True, "not_indexed": [],
         "missing_from_sitemap": [], "blocked": [], "kinds": {}, "engine_keys": {},
         "display": {}}
    f.update(kw)
    return {"funnel": f}


class TestCompareRuns(unittest.TestCase):
    def test_page_gone_earlier_in_the_funnel_is_not_recovered(self):
        old = funnel(not_indexed=[SITE + "/a/"], engine_keys={"idx": ["//example.com/b"]},
                     display={"//example.com/a": SITE + "/a/", "//example.com/b": SITE + "/b/"})
        new = funnel(not_indexed=[], engine_keys={"idx": ["//example.com/b"]},
                     display={"//example.com/a": SITE + "/a/", "//example.com/b": SITE + "/b/"},
                     blocked=[SITE + "/a/"])
        trend = doctor.compare_runs(new, old)
        self.assertEqual(trend["recovered"], [])

    def test_page_now_in_the_index_is_recovered(self):
        old = funnel(not_indexed=[SITE + "/a/"], engine_keys={"idx": []})
        new = funnel(not_indexed=[], engine_keys={"idx": ["//example.com/a"]})
        self.assertEqual(doctor.compare_runs(new, old)["recovered"], [SITE + "/a/"])

    def test_page_that_left_for_noindex_is_not_back_in_sitemap(self):
        disp = {"//example.com/a": SITE + "/a/"}
        old = funnel(missing_from_sitemap=[SITE + "/a/"], display=disp)
        new = funnel(missing_from_sitemap=[], display=disp, blocked=[SITE + "/a/"])
        self.assertEqual(doctor.compare_runs(new, old)["back_in_sitemap"], [])
        new = funnel(missing_from_sitemap=[], display=disp)
        self.assertEqual(doctor.compare_runs(new, old)["back_in_sitemap"], [SITE + "/a/"])

    def test_added_index_source_is_not_compared(self):
        steps_old = [{"id": "indexed", "name": "x", "count": 3}]
        steps_new = [{"id": "indexed", "name": "x", "count": 6}]
        old = funnel(steps=steps_old, kinds={"google": "index"}, not_indexed=[SITE + "/a/"],
                     engine_keys={"google": []})
        new = funnel(steps=steps_new, kinds={"google": "index", "bing": "index"},
                     engine_keys={"google": [], "bing": ["//example.com/a"]})
        trend = doctor.compare_runs(new, old)
        self.assertEqual(trend["sources_changed"], {"added": ["bing"], "removed": []})
        self.assertEqual(trend["recovered"], [])
        self.assertEqual(trend["steps"], [])

    def test_renamed_unlabelled_export_is_the_same_source(self):
        old = funnel(kinds={"gsc-week1": "list"})
        new = funnel(kinds={"gsc-week2": "list"})
        self.assertEqual(doctor.compare_runs(new, old)["sources_changed"], {})

    def test_logs_in_one_run_only_are_not_compared(self):
        old = dict(funnel(), ai_crawlers={"bots": [{"name": "OAI-SearchBot", "pages": 7}]})
        new = dict(funnel(), ai_crawlers=None)
        self.assertEqual(doctor.compare_runs(new, old)["not_compared"], ["logs"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_trend(doctor.compare_runs(new, old), "old.json")
        self.assertNotIn("ничего не изменилось", out.getvalue())


class TestHistoryFiles(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-129-g19-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "runs"))

    def put(self, name, data):
        with open(os.path.join(self.root, "runs", name), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_damaged_runs_are_skipped(self):
        bodies = [[1, 2], {"funnel": {"steps": 5}}, {"funnel": {"steps": [1]}},
                  {"funnel": {"steps": [{"id": "generated", "count": "10"}]}},
                  {"funnel": {"steps": []}, "segments": {"rows": [{"segment": "/rent/"}]}},
                  {"funnel": {"steps": []}, "_saved": 5}]
        for n, body in enumerate(bodies):
            self.put(f"2026-01-0{n + 1}T00-00-00.json", body)
        self.assertIsNone(history.latest(self.root))
        self.assertEqual(history.series(self.root)["dates"], [])
        history.render(self.root, SITE)

    def test_damaged_baseline_is_a_clean_error(self):
        path = os.path.join(self.root, "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"funnel": {"steps": 5}}, fh)
        with self.assertRaises(SourceError):
            doctor.load_run(path)

    def test_order_follows_saved_time_with_offset(self):
        # Токио: имя «позже», а время — раньше прогона по UTC.
        self.put("2026-11-27T03-00-00.json",
                 {"funnel": {"steps": [], "n": 1}, "_saved": "2026-11-27T03:00:00+09:00"})
        self.put("2026-11-26T19-00-00.json",
                 {"funnel": {"steps": [], "n": 2}, "_saved": "2026-11-26T19:00:00+00:00"})
        self.assertEqual(history.latest(self.root)["funnel"]["n"], 2)

    def test_saved_time_carries_an_offset(self):
        path = history.save(self.root, {"funnel": {"steps": []}},
                            now=datetime.datetime(2026, 1, 5, 10, 0, 0))
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)["_saved"]
        self.assertIsNotNone(datetime.datetime.fromisoformat(saved).tzinfo)

    def test_legend_marks_a_value_from_an_older_run(self):
        self.put("2026-01-01T00-00-00.json", {"funnel": {"steps": [
            {"id": "generated", "name": "Gen", "count": 10},
            {"id": "indexed", "name": "Idx", "count": 3}]}, "_saved": "2026-01-01T00:00:00"})
        self.put("2026-01-02T00-00-00.json", {"funnel": {"steps": [
            {"id": "generated", "name": "Gen", "count": 11}]}, "_saved": "2026-01-02T00:00:00"})
        with open(history.render(self.root, SITE), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Idx: 3 (2026-01-01)", text)
        self.assertIn("Gen: 11</li>", text)


PAGE = ('<!doctype html><html lang="en"><head><title>{t}</title>'
        '<meta name="description" content="{t} description of this page for tests">'
        '<link rel="canonical" href="{u}"></head><body><h1>{t}</h1><p>{body}</p>'
        '<a href="/">home</a><a href="/one/">one</a></body></html>')


class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-129-g19-pf-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.root = os.path.join(self.dir, "site")
        for rel, title in (("", "Home"), ("one/", "One")):
            os.makedirs(os.path.join(self.root, rel), exist_ok=True)
            with open(os.path.join(self.root, rel, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(PAGE.format(t=title, u=SITE + "/" + rel,
                                     body="Plain neutral words about a sample topic. " * 30))

    def spec(self, **kw):
        path = os.path.join(self.dir, "p.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"projects": [dict({"name": "x", "root": "site", "site": SITE}, **kw)]}, fh)
        return portfolio.read_portfolio(path)[0]

    def test_typo_in_robots_or_sitemap_fails_the_project(self):
        for key in ("robots", "sitemap"):
            result = portfolio.run_one(self.spec(**{key: "missing.txt"}))
            self.assertIn("missing.txt", result["error"])

    def test_explicit_keyword_column_must_exist(self):
        with open(os.path.join(self.dir, "d.csv"), "w", encoding="utf-8") as fh:
            fh.write("Keyword,price\none,10\n")
        result = portfolio.run_one(self.spec(dataset="d.csv", keyword="nosuch"))
        self.assertIn("nosuch", result["error"])
        result = portfolio.run_one(self.spec(dataset="d.csv"))
        self.assertEqual(result["error"], "")
        self.assertTrue(any("Keyword" in n for n in result["notes"]))

    def test_out_does_not_overwrite_a_site_page(self):
        target = os.path.join(self.root, "one", "index.html")
        result = portfolio.run_one(self.spec(out="site/one/index.html"))
        self.assertTrue(result["error"])
        with open(target, encoding="utf-8") as fh:
            self.assertNotIn(cli.REPORT_MARK, fh.read())

    def test_unwritable_out_fails_only_that_project(self):
        os.makedirs(os.path.join(self.dir, "blocker"))
        with open(os.path.join(self.dir, "blocker", "f"), "w") as fh:
            fh.write("x")
        result = portfolio.run_one(self.spec(out="blocker/f/r.html"))
        self.assertTrue(result["error"])

    def test_unknown_project_field_is_noted(self):
        result = portfolio.run_one(self.spec(datset="d.csv"))
        self.assertTrue(any("datset" in n and "dataset" in n for n in result["notes"]))

    def test_sitemap_hreflang_is_applied(self):
        sm = os.path.join(self.dir, "sm.xml")
        with open(sm, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/'
                     'sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
                     f'<url><loc>{SITE}/one/</loc><xhtml:link rel="alternate" hreflang="en-gb" '
                     f'href="{SITE}/one/"/></url><url><loc>{SITE}/</loc></url></urlset>')
        result = portfolio.run_one(self.spec(sitemap="sm.xml"))
        self.assertTrue(any("hreflang" in n for n in result["notes"]))

    def test_huge_grace_days_is_a_project_error(self):
        result = portfolio.run_one(self.spec(profile="events",
                                             freshness={"grace_days": 10 ** 10}))
        self.assertIn("grace_days", result["error"])
        with self.assertRaises(SourceError):
            settings.check_section("freshness", {"grace_days": float("inf")})

    def test_colliding_report_names_get_distinct_files(self):
        path = os.path.join(self.dir, "pf.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"projects": [{"name": "shop/a", "root": "site", "site": SITE},
                                    {"name": "shop a", "root": "site", "site": SITE}]}, fh)
        reports = os.path.join(self.dir, "r")
        parser = cli.build_parser()
        args = parser.parse_args(["portfolio", path, "--out", os.path.join(self.dir, "o.html"),
                                  "--reports", reports])
        with contextlib.redirect_stdout(io.StringIO()):
            args.func(args)
        self.assertEqual(sorted(os.listdir(reports)), ["shop-a-2.html", "shop-a.html"])


class TestPatterns(unittest.TestCase):
    def result(self, name, issues):
        return {"name": name, "error": "", "pages": 10, "issues": issues,
                "page_urls": [u for _, u, _, _ in issues]}

    def test_level_is_the_most_severe(self):
        out = portfolio.common_patterns([
            self.result("a", [("warning", SITE + "/a/", "canonical-elsewhere", "m")]),
            self.result("b", [("info", SITE + "/b/", "canonical-elsewhere", "m")])])
        self.assertEqual(out[0]["level"], "warning")


if __name__ == "__main__":
    unittest.main()
