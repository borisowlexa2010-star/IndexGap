# -*- coding: utf-8 -*-
"""
Портфель и профили: один прогон по нескольким проектам.

Проверяется главное свойство режима — что он не превращается в «пять раз
одно и то же»: профили действительно меняют вердикт, ошибка одного проекта
не роняет остальные, а общие грабли считаются в долях страниц, а не в штуках.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexgap import freshness, portfolio, profiles, report
from indexgap.core import SourceError


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-pf-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path) or self.dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def portfolio_file(self, projects):
        path = os.path.join(self.dir, "projects.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"projects": projects}, fh, ensure_ascii=False)
        return path


# ── профили ───────────────────────────────────────────────────────────────────

class TestProfiles(unittest.TestCase):
    def test_unknown_profile_is_an_error_not_a_silent_default(self):
        with self.assertRaises(SourceError):
            profiles.get("magazine")

    def test_profile_thresholds_differ_where_it_matters(self):
        catalog = profiles.apply({}, "catalog")["checks"]
        events = profiles.apply({}, "events")["checks"]
        ugc = profiles.apply({}, "ugc")["checks"]
        self.assertGreater(catalog["thin_words"], events["thin_words"])
        self.assertGreater(events["thin_words"], ugc["thin_words"])
        self.assertLess(catalog["near_duplicate"], ugc["near_duplicate"])

    def test_explicit_config_beats_the_profile(self):
        merged = profiles.apply({"checks": {"thin_words": 999}}, "ugc")
        self.assertEqual(merged["checks"]["thin_words"], 999)

    def test_ugc_declares_that_facts_are_not_checked(self):
        self.assertTrue(profiles.apply({}, "ugc")["_skip_facts"])
        self.assertFalse(profiles.apply({}, "catalog")["_skip_facts"])


# ── свежесть ──────────────────────────────────────────────────────────────────

class _Page:
    def __init__(self, url, meta=None, raw="", jsonld=None, robots=""):
        self.url, self.meta, self.raw = url, meta or {}, raw
        self.jsonld = jsonld or []
        self.robots = robots
        self.canonical = ""

    @property
    def noindex(self):
        from indexgap.core import Page
        return Page.noindex.fget(self)

    @property
    def key(self):
        from indexgap.core import url_key
        return url_key(self.url)


class TestFreshness(Fixture):
    def test_past_event_still_indexable_is_critical(self):
        past = (date(2026, 8, 28) - timedelta(days=60)).isoformat()
        page = _Page("https://e.example/a/", meta={"date": past})
        result = freshness.check([page], today=date(2026, 8, 28))
        self.assertEqual(result["issues"][0][2], "stale-event")
        self.assertEqual(result["issues"][0][0], "critical")

    def test_past_event_closed_from_index_is_fine(self):
        past = (date(2026, 8, 28) - timedelta(days=60)).isoformat()
        page = _Page("https://e.example/a/", meta={"date": past}, robots="noindex")
        result = freshness.check([page], today=date(2026, 8, 28))
        self.assertEqual(result["issues"][0][2], "stale-closed")
        self.assertEqual(result["issues"][0][0], "info")

    def test_upcoming_event_is_not_flagged(self):
        soon = (date(2026, 8, 28) + timedelta(days=30)).isoformat()
        page = _Page("https://e.example/a/", meta={"date": soon})
        self.assertEqual(freshness.check([page], today=date(2026, 8, 28))["issues"], [])

    def test_grace_period_protects_a_just_passed_event(self):
        recent = (date(2026, 8, 28) - timedelta(days=5)).isoformat()
        page = _Page("https://e.example/a/", meta={"date": recent})
        self.assertEqual(freshness.check([page], today=date(2026, 8, 28))["issues"], [])

    def test_jsonld_event_start_date_is_read(self):
        past = (date(2026, 8, 28) - timedelta(days=90)).isoformat()
        page = _Page("https://e.example/a/", jsonld=[json.dumps(
            {"@type": "Event", "startDate": past})])
        result = freshness.check([page], today=date(2026, 8, 28))
        self.assertEqual(result["issues"][0][2], "stale-event")

    def test_undated_site_gets_an_honest_note_not_a_clean_bill(self):
        pages = [_Page(f"https://e.example/p{i}/") for i in range(10)]
        result = freshness.check(pages, today=date(2026, 8, 28))
        self.assertEqual(result["issues"], [])
        self.assertIn("даты нашлись", result["note"])


# ── портфель ──────────────────────────────────────────────────────────────────

class TestPortfolio(Fixture):
    def _project(self, name, pages=4, words=60):
        for i in range(pages):
            self.write(f"{name}/p{i}/index.md",
                       f"---\ntitle: Страница {i} проекта {name}\n"
                       f"description: Описание страницы {i} проекта {name}, "
                       f"достаточно длинное для проверки длины описания сайта.\n---\n\n"
                       f"# Страница {i}\n\n" + f"слово{i} текст страницы " * words
                       + f"\n\n[Соседняя](/p{(i + 1) % pages}/)\n")
        self.write(f"{name}/index.md",
                   f"---\ntitle: Главная проекта {name}\n---\n\n# {name}\n\n"
                   + "\n".join(f"* [Страница {i}](/p{i}/)" for i in range(pages)))
        return {"name": name, "root": name, "site": f"https://{name}.example"}

    def test_paths_are_relative_to_the_portfolio_file(self):
        spec = self._project("alpha")
        path = self.portfolio_file([spec])
        specs = portfolio.read_portfolio(path)
        self.assertTrue(os.path.isabs(specs[0]["root"]))
        self.assertTrue(os.path.isdir(specs[0]["root"]))

    def test_missing_fields_are_named(self):
        path = self.portfolio_file([{"name": "a", "root": "x"}])
        with self.assertRaises(SourceError) as ctx:
            portfolio.read_portfolio(path)
        self.assertIn("site", str(ctx.exception))

    def test_duplicate_names_are_refused(self):
        spec = self._project("alpha")
        path = self.portfolio_file([spec, dict(spec)])
        with self.assertRaises(SourceError):
            portfolio.read_portfolio(path)

    def test_one_broken_project_does_not_kill_the_run(self):
        good = self._project("alpha")
        bad = {"name": "beta", "root": "nowhere", "site": "https://beta.example"}
        specs = portfolio.read_portfolio(self.portfolio_file([good, bad]))
        results = [portfolio.run_one(s) for s in specs]
        self.assertEqual(results[0]["error"], "")
        self.assertTrue(results[1]["error"])
        self.assertGreater(results[0]["pages"], 0)

    def test_profile_changes_the_verdict_on_the_same_pages(self):
        spec = self._project("alpha", pages=6, words=40)
        specs = portfolio.read_portfolio(self.portfolio_file([
            dict(spec, name="as-catalog", profile="catalog"),
            dict(spec, name="as-ugc", profile="ugc"),
        ]))
        as_catalog, as_ugc = (portfolio.run_one(s) for s in specs)
        thin_catalog = [i for i in as_catalog["issues"] if i[2] == "thin"]
        thin_ugc = [i for i in as_ugc["issues"] if i[2] == "thin"]
        self.assertGreater(len(thin_catalog), len(thin_ugc))

    def test_ugc_says_facts_were_not_checked(self):
        spec = dict(self._project("feed"), profile="ugc")
        result = portfolio.run_one(portfolio.read_portfolio(
            self.portfolio_file([spec]))[0])
        self.assertTrue(any("сверять не с чем" in n for n in result["notes"]))

    def test_catalog_without_dataset_says_so(self):
        spec = dict(self._project("cat"), profile="catalog")
        result = portfolio.run_one(portfolio.read_portfolio(
            self.portfolio_file([spec]))[0])
        self.assertTrue(any("датасет не указан" in n for n in result["notes"]))

    def test_common_patterns_use_shares_not_counts(self):
        big = self._project("big", pages=40, words=4)
        small = self._project("small", pages=4, words=4)
        specs = portfolio.read_portfolio(self.portfolio_file([big, small]))
        results = [portfolio.run_one(s) for s in specs]
        patterns = portfolio.common_patterns(results)
        thin = [p for p in patterns if p["code"] == "thin"]
        self.assertTrue(thin)
        self.assertAlmostEqual(thin[0]["detail"]["big"]["share"],
                               thin[0]["detail"]["small"]["share"], delta=0.15)

    def test_site_level_findings_are_not_reported_as_page_shares(self):
        specs = portfolio.read_portfolio(self.portfolio_file([
            self._project("alpha"), self._project("beta")]))
        results = [portfolio.run_one(s) for s in specs]
        patterns = portfolio.common_patterns(results)
        robots = [p for p in patterns if p["code"] == "no-robots"]
        if robots:
            self.assertEqual(robots[0]["scope"], "site")

    def test_findings_seen_in_one_project_are_listed_separately(self):
        alpha = self._project("alpha")
        self.write("beta/p0/index.md",
                   "---\ntitle: Одинокая страница проекта бета\n"
                   "description: Описание одинокой страницы проекта бета, "
                   "достаточно длинное для проверки.\nstatus: draft\n---\n\nТекст")
        beta = {"name": "beta", "root": "beta", "site": "https://beta.example"}
        specs = portfolio.read_portfolio(self.portfolio_file([alpha, beta]))
        results = [portfolio.run_one(s) for s in specs]
        uniques = {u["name"]: u["codes"] for u in portfolio.unique_findings(results)}
        self.assertIn("still-draft", uniques.get("beta", []))

    def test_portfolio_report_is_written_and_marked_as_ours(self):
        specs = portfolio.read_portfolio(self.portfolio_file([self._project("alpha")]))
        results = [portfolio.run_one(s) for s in specs]
        path = report.build_portfolio(results, portfolio.common_patterns(results), [],
                                      out_path=os.path.join(self.dir, "pf.html"))
        html = open(path, encoding="utf-8").read()
        self.assertIn("indexgap-report", html)
        self.assertIn("alpha", html)

    def test_report_survives_a_portfolio_where_everything_failed(self):
        results = [{"name": "a", "error": "нет каталога", "pages": 0, "issues": []}]
        path = report.build_portfolio(results, [], [],
                                      out_path=os.path.join(self.dir, "pf.html"))
        self.assertIn("не проверен", open(path, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
