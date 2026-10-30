# -*- coding: utf-8 -*-
"""
Риск по шаблону.

Двести находок на сайте ничего не говорят о том, какой шаблон чинить первым.
Шаблон городов, где у каждой третьей страницы закрыт индекс, опаснее блога
с длинными заголовками, даже если находок в блоге больше. Поэтому `check`
считает по каждому шаблону адресов долю страниц с критичным и с вниманием,
три самых частых кода и риск 0–100.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import checks, cli

SITE = "https://example.com"


def fake(pattern, n):
    return [SimpleNamespace(url=f"{SITE}/{pattern}/p{i}/") for i in range(n)]


class Formula(unittest.TestCase):
    def test_every_page_with_the_most_severe_critical_scores_100(self):
        pages = fake("city", 10)
        issues = [("critical", p.url, "stale-event", "x") for p in pages]
        got = checks.template_risk(issues, pages)
        self.assertEqual(got[0]["risk"], 100)
        self.assertEqual(got[0]["critical_share"], 1.0)

    def test_share_and_weight_both_count(self):
        # orphan: вес 6 → тяжесть 1 − 6/40 = 0.85; задеты 4 из 10 → 34.
        pages = fake("city", 10)
        issues = [("critical", p.url, "orphan", "x") for p in pages[:4]]
        got = checks.template_risk(issues, pages)[0]
        self.assertEqual(got["risk"], 34)
        self.assertEqual(got["critical_share"], 0.4)
        self.assertEqual(got["warning_share"], 0.0)

    def test_warnings_weigh_less_than_criticals(self):
        # deep: вес 16 → 0.3 × (1 − 16/40) = 0.18 на каждой странице → 18.
        pages = fake("city", 10)
        issues = [("warning", p.url, "deep", "x") for p in pages]
        got = checks.template_risk(issues, pages)[0]
        self.assertEqual(got["risk"], 18)
        self.assertEqual(got["warning_share"], 1.0)

    def test_a_page_counts_once_by_its_worst_finding(self):
        pages = fake("city", 10)
        issues = ([("critical", p.url, "stale-event", "x") for p in pages]
                  + [("warning", p.url, "deep", "x") for p in pages])
        self.assertEqual(checks.template_risk(issues, pages)[0]["risk"], 100)

    def test_unknown_codes_are_treated_as_mild(self):
        pages = fake("city", 10)
        issues = [("critical", p.url, "never-heard-of-it", "x") for p in pages]
        self.assertEqual(checks.template_risk(issues, pages)[0]["risk"], 50)

    def test_info_does_not_add_risk(self):
        pages = fake("city", 10)
        issues = [("info", p.url, "similar", "x") for p in pages]
        got = checks.template_risk(issues, pages)[0]
        self.assertEqual(got["risk"], 0)
        self.assertEqual(got["top_codes"], [])


class Grouping(unittest.TestCase):
    def test_ordering_is_by_risk_then_size(self):
        pages = fake("city", 12) + fake("blog", 10) + fake("shop", 15)
        issues = ([("critical", p.url, "noindex", "x") for p in pages[:12]]
                  + [("warning", p.url, "deep", "x") for p in pages[12:22]])
        got = checks.template_risk(issues, pages)
        self.assertEqual([t["pattern"] for t in got], ["/city/*/", "/blog/*/", "/shop/*/"])
        self.assertGreater(got[0]["risk"], got[1]["risk"])
        self.assertEqual(got[2]["risk"], 0)

    def test_small_patterns_go_to_other(self):
        pages = (fake("city", 10) + fake("blog", 3) + fake("about", 1)
                 + [SimpleNamespace(url=SITE + "/")])
        got = {t["pattern"]: t for t in checks.template_risk([], pages)}
        self.assertEqual(set(got), {"/city/*/", "other"})
        self.assertEqual(got["other"]["pages"], 5)

    def test_no_pattern_of_ten_pages_means_no_templates(self):
        pages = fake("city", 9) + fake("blog", 9)
        issues = [("critical", p.url, "noindex", "x") for p in pages]
        self.assertEqual(checks.template_risk(issues, pages), [])

    def test_top_codes_are_three_by_count(self):
        pages = fake("city", 10)
        issues = ([("critical", p.url, "thin", "x") for p in pages]
                  + [("warning", p.url, "deep", "x") for p in pages[:6]]
                  + [("warning", p.url, "title-long", "x") for p in pages[:4]]
                  + [("warning", p.url, "vague-anchor", "x") for p in pages[:2]])
        got = checks.template_risk(issues, pages)[0]
        self.assertEqual(got["top_codes"], [{"code": "thin", "count": 10},
                                            {"code": "deep", "count": 6},
                                            {"code": "title-long", "count": 4}])

    def test_site_level_findings_belong_to_no_template(self):
        pages = fake("city", 10)
        issues = [("critical", "robots.txt", "robots-blocks-all", "x"),
                  ("critical", "", "ai-crawler-blocked", "x")]
        self.assertEqual(checks.template_risk(issues, pages)[0]["risk"], 0)


def page(title, body):
    return (f"<!doctype html><html lang=\"ru\"><head><title>{title}</title>"
            "<meta name=\"description\" content=\"Аренда техники в городе, цены и условия\">"
            f"</head><body><main><h1>{title}</h1><p>{body}</p>"
            "<a href=\"/\">Главная</a></main></body></html>")


class InCheck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-risk-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.site = os.path.join(self.dir, "site")
        links = "".join(f'<a href="/city/c{i}/">Город {i}</a> ' for i in range(12))
        self.write("index.html", page("Аренда техники", "Каталог. " + links))

    def write(self, name, text):
        path = os.path.join(self.site, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self):
        out = os.path.join(self.dir, "r.json")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", self.site, "--site", SITE, "--out", out])
        with open(out, encoding="utf-8") as fh:
            return code, stdout.getvalue(), json.load(fh)

    def test_templates_reach_json_console_and_html(self):
        for i in range(12):
            robots = '<meta name="robots" content="noindex">' if i < 6 else ""
            self.write(f"city/c{i}/index.html",
                       page(f"Аренда в городе {i}", f"Город номер {i}. " * 40)
                       .replace("<head>", "<head>" + robots))
        code, out, data = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(data["schema"], 2)
        templates = data["templates"]
        city = [t for t in templates if t["pattern"] == "/city/*/"][0]
        self.assertEqual(set(city), {"pattern", "pages", "critical_share",
                                     "warning_share", "top_codes", "risk"})
        self.assertEqual(city["pages"], 12)
        self.assertGreaterEqual(city["critical_share"], 0.5)
        self.assertIn("noindex", [c["code"] for c in city["top_codes"]])
        self.assertIn("Самые рискованные шаблоны", out)
        self.assertIn("/city/*/", out.split("Самые рискованные шаблоны")[1])
        with open(os.path.join(self.dir, "r.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("Риск по шаблонам", html)
        self.assertIn("/city/*/", html)

    def test_a_site_without_big_templates_prints_nothing_extra(self):
        for i in range(5):
            self.write(f"city/c{i}/index.html",
                       page(f"Аренда в городе {i}", f"Город номер {i}. " * 40))
        code, out, data = self.check()
        self.assertEqual(data["templates"], [])
        self.assertNotIn("Самые рискованные шаблоны", out)
        with open(os.path.join(self.dir, "r.html"), encoding="utf-8") as fh:
            self.assertNotIn("Риск по шаблонам", fh.read())


if __name__ == "__main__":
    unittest.main()
