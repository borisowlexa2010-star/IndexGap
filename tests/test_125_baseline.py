# -*- coding: utf-8 -*-
"""
1.25: сравнение прогонов — где «ничего нового» и «исчезло» говорили неправду.

* предмет находки читался из укороченного текста («/a, /b, /c и ещё 1»):
  новая четвёртая битая ссылка не замечалась, исправленная первая выглядела
  новой, а дубль из группы трёх после правки одной страницы — новым дублем;
* второе выдуманное число на странице с уже известным не было новой находкой;
* прогон без датасета и находки, принятые через ignore, считались «исчезло»;
* doctor без выгрузки индекса объявлял все страницы «вернувшимися в индекс»;
* trend.html раздваивал линии на разных языках, а прогоны одной секунды
  читались не по порядку;
* diff считал запасной вход SPA (`/* /index.html 200`) редиректом и не
  проверял цели с `:splat`;
* портфель не читал профиль и датасет из indexgap.json проекта;
* наряды двух страниц с одинаковым slug писались в один файл;
* «Начни с этого» в HTML не начинал с находки уровня сайта.
"""

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, diff, doctor, history, portfolio, repair

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


class Demo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = os.path.join(self.tmp, "site")
        shutil.copytree(DEMO, self.dir)
        self.dataset = os.path.join(self.dir, "cities.csv")

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def edit(self, rel, change):
        path = self.path(*rel.split("/"))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        new = change(text)
        self.assertNotEqual(new, text, rel)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)

    def write(self, rel, text):
        path = self.path(*rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_cli(self, *argv):
        self.stdout = io.StringIO()
        with contextlib.redirect_stdout(self.stdout), \
                contextlib.redirect_stderr(io.StringIO()):
            return cli.main(list(argv))

    def check(self, name, *extra):
        out = os.path.join(self.tmp, name)
        code = self.run_cli("check", self.dir, "--site", SITE, "--out", out, *extra)
        with open(out, encoding="utf-8") as fh:
            return code, json.load(fh)


LINKS = '<p><a href="/">All city guides</a></p>'


class TestSubjectIsNotReadFromShortenedText(Demo):
    def links(self, *slugs):
        return " ".join(f'<a href="/rent/{s}/">{s}</a>' for s in slugs)

    def test_a_fourth_broken_link_is_new(self):
        self.edit("rent/berlin/index.html", lambda t: t.replace(
            LINKS, f"<p>{self.links('aachen', 'bonn', 'celle')}</p>" + LINKS))
        self.check("base.json")
        self.edit("rent/berlin/index.html", lambda t: t.replace(
            self.links("celle"), self.links("celle", "zwickau")))
        _, data = self.check("now.json", "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertEqual([(i["code"], i["url"]) for i in data["baseline"]["new"]],
                         [("broken-link", SITE + "/rent/berlin/")])

    def test_fixing_one_of_four_broken_links_is_not_new(self):
        self.edit("rent/berlin/index.html", lambda t: t.replace(
            LINKS, f"<p>{self.links('aachen', 'bremen', 'kiel', 'mainz')}</p>" + LINKS))
        self.check("base.json")
        self.edit("rent/berlin/index.html", lambda t: t.replace(
            self.links("aachen") + " ", ""))
        _, data = self.check("now.json", "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertEqual(data["baseline"]["new"], [])
        self.assertEqual(data["baseline"]["fixed"], [])
        broken = [i for i in data["issues"] if i["code"] == "broken-link"][0]
        self.assertEqual(len(broken["subject"]), 3)

    def test_a_second_invented_number_on_a_page_is_new(self):
        self.check("base.json", "--dataset", self.dataset)
        self.edit("rent/hamburg/index.html", lambda t: t.replace("is 31 minutes", "is 95 minutes"))
        code, data = self.check("now.json", "--dataset", self.dataset, "--strict",
                                "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertEqual(code, 1)
        self.assertEqual([(i["code"], i["url"]) for i in data["baseline"]["new"]],
                         [("unsupported-number", SITE + "/rent/hamburg/")])

    def test_the_same_invented_number_is_not_new(self):
        self.check("base.json", "--dataset", self.dataset)
        code, data = self.check("now.json", "--dataset", self.dataset, "--strict",
                                "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertEqual(code, 0)
        self.assertEqual(data["baseline"], dict(data["baseline"], new=[], fixed=[]))

    def test_a_baseline_without_subjects_is_read_from_text(self):
        # База 1.24: поля `subject` нет. Полный предмет новой стороны против
        # укороченного старого не должен давать «новых» находок.
        self.edit("rent/berlin/index.html", lambda t: t.replace(
            LINKS, f"<p>{self.links('aachen', 'bremen', 'kiel', 'mainz')}</p>" + LINKS))
        _, data = self.check("base.json", "--dataset", self.dataset)
        for item in data["issues"]:
            item.pop("subject", None)
        data.pop("coverage", None)
        with open(os.path.join(self.tmp, "base.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        _, now = self.check("now.json", "--dataset", self.dataset,
                            "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertEqual(now["baseline"]["new"], [])
        self.assertEqual(now["baseline"]["fixed"], [])

    def test_rewriting_one_page_of_a_duplicate_group_is_not_a_new_duplicate(self):
        with open(self.path("rent", "frankfurt", "index.html"), encoding="utf-8") as fh:
            frankfurt = fh.read()
        for slug, city in (("munich", "Munich"), ("stuttgart", "Stuttgart")):
            self.write(f"rent/{slug}/index.html", frankfurt.replace("Frankfurt", city))
        self.check("base.json")
        with open(os.path.join(DEMO, "rent", "munich", "index.html"), encoding="utf-8") as fh:
            self.write("rent/munich/index.html", fh.read())
        code, data = self.check("now.json", "--strict",
                                "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertEqual([i for i in data["baseline"]["new"] if i["code"] == "near-duplicate"], [])
        self.assertEqual(code, 0)
        gone = [i["url"] for i in data["baseline"]["fixed"] if i["code"] == "near-duplicate"]
        self.assertEqual(gone, [SITE + "/rent/munich/"])


class TestWhatIsNotGone(Demo):
    def test_accepted_findings_are_not_gone(self):
        self.check("base.json")
        self.write("indexgap.json", json.dumps({"ignore": {"noindex": ["/rent/*"],
                                                           "orphan": True}}))
        _, data = self.check("now.json", "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertTrue(data["accepted"])
        self.assertEqual(data["baseline"]["fixed"], [])
        self.assertEqual(sorted(i["code"] for i in data["baseline"]["accepted"]),
                         sorted(i["code"] for i in data["accepted"]))

    def test_a_run_without_the_dataset_does_not_fix_fact_findings(self):
        _, base = self.check("base.json", "--dataset", self.dataset)
        self.assertTrue(base["coverage"]["facts"])
        self.edit("rent/berlin/index.html", lambda t: t.replace("is 34 minutes", "is 95 minutes"))
        _, data = self.check("now.json", "--baseline", os.path.join(self.tmp, "base.json"))
        self.assertFalse(data["coverage"]["facts"])
        self.assertEqual(data["baseline"]["fixed"], [])
        self.assertTrue(data["baseline"]["unchecked"])
        self.assertTrue(data["baseline"]["facts_off"])
        self.assertIn("сверкой фактов", self.stdout.getvalue())


class TestDoctorWithoutIndex(unittest.TestCase):
    def test_no_index_this_time_is_not_recovery(self):
        old = {"funnel": {"has_index": True, "has_sitemap": True,
                          "not_indexed": [SITE + "/a/", SITE + "/b/"],
                          "missing_from_sitemap": [], "steps": []},
               "segments": {"rows": [{"segment": "/rent/", "lost": 4}], "highlighted": []}}
        new = {"funnel": {"has_index": False, "has_sitemap": True, "not_indexed": [],
                          "missing_from_sitemap": [], "steps": []},
               "segments": {"rows": [{"segment": "/rent/", "lost": 2}], "highlighted": []}}
        trend = doctor.compare_runs(new, old)
        self.assertEqual(trend["recovered"], [])
        self.assertEqual(trend["newly_not_indexed"], [])
        self.assertEqual(trend["segments"]["rows"], [])
        self.assertEqual(trend["not_compared"], ["index"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_trend(trend, "old.json")
        self.assertNotIn("вернулись в индекс", out.getvalue())
        self.assertIn("только в одном из прогонов", out.getvalue())

    def test_both_runs_with_an_index_still_compare(self):
        f = {"has_index": True, "has_sitemap": True, "missing_from_sitemap": [], "steps": []}
        trend = doctor.compare_runs({"funnel": dict(f, not_indexed=[])},
                                    {"funnel": dict(f, not_indexed=[SITE + "/a/"])})
        self.assertEqual(trend["recovered"], [SITE + "/a/"])
        self.assertEqual(trend["not_compared"], [])


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-125-history-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "runs"))

    def put(self, name, steps):
        with open(os.path.join(self.root, "runs", name), "w", encoding="utf-8") as fh:
            json.dump({"funnel": {"steps": steps}, "_saved": name[:19]}, fh)

    def test_runs_of_one_second_are_in_order(self):
        stamp = "2026-01-05T10-00-00"
        for name in (f"{stamp}.json", f"{stamp}-2.json", f"{stamp}-10.json",
                     f"{stamp}-3.json", "2026-01-05T10-00-01.json"):
            self.put(name, [])
        self.assertEqual([os.path.basename(p) for p in history.runs(self.root)],
                         [f"{stamp}.json", f"{stamp}-2.json", f"{stamp}-3.json",
                          f"{stamp}-10.json", "2026-01-05T10-00-01.json"])
        self.assertTrue(history.latest(self.root)["_path"].endswith("T10-00-01.json"))

    def test_save_twice_in_one_second_reads_back_the_last(self):
        import datetime
        now = datetime.datetime(2026, 1, 5, 10, 0, 0)
        for n in (1, 2, 3):
            history.save(self.root, {"funnel": {"steps": [], "n": n}}, now=now)
        self.assertEqual(history.latest(self.root)["funnel"]["n"], 3)

    def test_lines_are_keyed_by_step_id_not_by_translated_name(self):
        self.put("2026-01-05T10-00-00.json", [{"id": "generated", "name": "Generated", "count": 10},
                                              {"id": "indexed", "name": "In at least one index",
                                               "count": 4}])
        self.put("2026-01-06T10-00-00.json", [{"id": "generated", "name": "Сгенерировано",
                                               "count": 11},
                                              {"id": "indexed", "name": "Хотя бы в одном индексе",
                                               "count": 3}])
        lines = history.series(self.root)["lines"]
        self.assertEqual(sorted(lines), ["Сгенерировано", "Хотя бы в одном индексе"])
        self.assertEqual(lines["Сгенерировано"], [(0, 10), (1, 11)])
        page = open(history.render(self.root), encoding="utf-8").read()
        colours = re.findall(r'<li><span style="background:(#\w+)"', page)
        self.assertEqual(len(colours), 2)
        self.assertEqual(len(set(colours)), 2)


class TestDiffRedirects(Demo):
    def setUp(self):
        super().setUp()
        self.new = os.path.join(self.tmp, "new")
        shutil.copytree(self.dir, self.new)

    def diff(self, *extra):
        out = os.path.join(self.tmp, "d.json")
        code = self.run_cli("diff", self.dir, self.new, "--site", SITE, "--out", out,
                            "--no-checks", *extra)
        with open(out, encoding="utf-8") as fh:
            return code, json.load(fh)

    def test_an_spa_fallback_is_not_a_redirect(self):
        for slug in ("berlin", "munich"):
            shutil.rmtree(os.path.join(self.new, "rent", slug))
        with open(os.path.join(self.new, "_redirects"), "w", encoding="utf-8") as fh:
            fh.write("/*  /index.html  200\n")
        code, data = self.diff("--strict")
        self.assertEqual(code, 1)
        self.assertEqual(sorted(r["level"] for r in data["removed"]), ["critical", "critical"])

    def test_a_vercel_catch_all_rewrite_is_not_a_redirect(self):
        rules = diff._vercel(json.dumps({"rewrites": [
            {"source": "/(.*)", "destination": "/index.html"}]}), "vercel.json")
        self.assertEqual(rules, [])
        # Точечная перезапись и редирект 301 на всё подряд — по-прежнему правила.
        self.assertTrue(diff._netlify_lines("/old/* /new/:splat 200\n", "_redirects"))
        self.assertTrue(diff._netlify_lines("/* /index.html 301\n", "_redirects"))

    def test_a_splat_target_outside_the_new_build_is_a_warning(self):
        os.rename(os.path.join(self.new, "rent"), os.path.join(self.new, "flats"))
        with open(os.path.join(self.new, "_redirects"), "w", encoding="utf-8") as fh:
            fh.write("/rent/*  /flat/:splat  301\n")
        _, data = self.diff()
        berlin = [r for r in data["removed"] if r["url"] == SITE + "/rent/berlin/"][0]
        self.assertEqual(berlin["level"], "warning")
        self.assertEqual(berlin["redirect_missing"], SITE + "/flat/berlin")

    def test_a_splat_target_inside_the_new_build_is_info(self):
        os.rename(os.path.join(self.new, "rent"), os.path.join(self.new, "flats"))
        with open(os.path.join(self.new, "_redirects"), "w", encoding="utf-8") as fh:
            fh.write("/rent/*  /flats/:splat  301\n")
        _, data = self.diff()
        berlin = [r for r in data["removed"] if r["url"] == SITE + "/rent/berlin/"][0]
        self.assertEqual((berlin["level"], berlin["redirect_missing"]), ("info", None))

    def test_destination_fills_params_and_skips_other_hosts(self):
        rules = diff._vercel(json.dumps({"redirects": [
            {"source": "/city/:slug", "destination": "/towns/:slug"},
            {"source": "/shop/:path*", "destination": "https://other.example/:path*"}]}),
            "vercel.json")
        self.assertEqual(diff.destination(rules, SITE + "/city/c3/"), SITE + "/towns/c3")
        self.assertEqual(diff.destination(rules, SITE + "/shop/a/b/"), "")
        rules = diff._netlify_lines(f"/old/* {SITE}/new/:splat 301\n", "_redirects")
        self.assertEqual(diff.destination(rules, SITE + "/old/x/"), SITE + "/new/x")


class TestPortfolioReadsProjectConfig(Demo):
    def portfolio(self, config):
        self.write("indexgap.json", json.dumps(config))
        path = os.path.join(self.tmp, "projects.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"projects": [{"name": "demo", "root": "site", "site": SITE}]}, fh)
        with mock.patch.object(sys, "stdout", io.StringIO()):
            return portfolio.run_one(portfolio.read_portfolio(path)[0])

    def codes(self, result):
        return {(i[2] if isinstance(i, (list, tuple)) else i["code"]) for i in result["issues"]}

    def test_dataset_from_indexgap_json(self):
        result = self.portfolio({"site": SITE, "pages": ".", "dataset": "cities.csv"})
        self.assertIn("unsupported-number", self.codes(result))

    def test_profile_from_indexgap_json(self):
        result = self.portfolio({"site": SITE, "pages": ".", "profile": "events"})
        self.assertEqual(result["profile"], "events")


class TestBriefNames(Demo):
    def test_colliding_slugs_get_their_own_files(self):
        with open(self.path("rent", "berlin", "index.html"), encoding="utf-8") as fh:
            berlin = fh.read()
        self.write("rent/new-york/index.html", berlin.replace("Berlin", "New York"))
        self.write("rent/new.york/index.html",
                   re.sub(r'<meta name="description"[^>]*>', "",
                          berlin.replace("Berlin", "New Amsterdam")))
        out = os.path.join(self.tmp, "briefs")
        self.run_cli("brief", self.dir, "--site", SITE, "--dataset", self.dataset,
                     "--out-dir", out, "--write")
        files = [os.path.join(b, n) for b, _, names in os.walk(out) for n in names]
        urls = []
        for path in files:
            with open(path, encoding="utf-8") as fh:
                urls += re.findall(r"^url: (.+)$", fh.read(), re.M)
        self.assertIn(SITE + "/rent/new-york/", urls)
        self.assertIn(SITE + "/rent/new.york/", urls)
        self.assertEqual(len(urls), len(set(urls)))
        said = re.search(r"Записано в .*: (\d+) файл", self.stdout.getvalue())
        self.assertEqual(int(said.group(1)), len(files))

    def test_unique_names_is_stable(self):
        briefs = [{"name": "rent/a.md", "url": SITE + "/rent/a.b/"},
                  {"name": "rent/a.md", "url": SITE + "/rent/a-b/"},
                  {"name": "rent/a-2.md", "url": SITE + "/rent/a-2/"},
                  {"name": "Rent/A.md", "url": SITE + "/Rent/A/"}]
        names = {b["url"]: b["name"] for b in repair._unique_names(briefs)}
        self.assertEqual(names[SITE + "/Rent/A/"], "Rent/A.md")
        self.assertEqual(len({n.lower() for n in names.values()}), 4)


class TestStartHereLeadsWithTheSite(Demo):
    def test_robots_blocks_all_is_first_in_html(self):
        self.write("robots.txt", "User-agent: *\nDisallow: /\n")
        out = os.path.join(self.tmp, "c.json")
        self.run_cli("check", self.dir, "--site", SITE, "--dataset", self.dataset, "--out", out)
        with open(os.path.join(self.tmp, "c.html"), encoding="utf-8") as fh:
            page = fh.read()
        first = re.search(r'<div class="first">.*?</div>', page, re.S).group(0)
        codes = re.findall(r"<li><strong>([\w-]+)</strong>", first)
        self.assertEqual(codes[0], "robots-blocks-all")
        self.assertIn("весь сайт", first)


if __name__ == "__main__":
    unittest.main()
