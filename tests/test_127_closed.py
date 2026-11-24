# -*- coding: utf-8 -*-
"""
1.27: закрытые страницы, sitemap и noindex-group.

* sitemap сборки, который называет одну главную или адреса `localhost:3000`,
  не доказывает, что закрытые страницы убраны намеренно.
* Большие закрытые ветки каталога не уходят тихо в сведения мимо
  `noindex-group`.
* Портфель считает закрытые страницы так же, как `check`, и находит
  `robots.txt.body` сборки Next.js.
* Шаблоны закрытых веток несут риск группы; база не считает «исчезнувшими»
  страницы, которые группа поглотила, а принятая группа не принимает молча
  ветку, закрытую после базы.
"""

import io
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"
WORDS = ("river harbor market tower garden bridge station north south east west copper "
         "silver amber violet maple cedar pine birch oak willow falcon heron otter").split()


def run(argv):
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        code = cli.main(argv)
    return code, printed.getvalue()


def run_check(folder, *extra):
    out = os.path.join(folder + "-out", "r.json")
    code, printed = run(["check", folder, "--site", SITE, "--out", out, *extra])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh), printed, code


def counts(result):
    return Counter((i["level"], i["code"]) for i in result["issues"]
                   if i["code"] in ("noindex", "noindex-group"))


def sitemap(urls):
    return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")


def catalogue(folder, branches=13, per=5, closed=4, names=None, map_mode=None):
    """Каталог `/visa/<ветка>/qNN/`; первые `closed` веток закрыты noindex."""
    names = names or [f"c{n:02d}" for n in range(branches)]
    listed = ["/", "/visa/"]
    hub = []

    def write(path, title, body, shut=False):
        d = os.path.join(folder, path.strip("/"))
        os.makedirs(d, exist_ok=True)
        robots = '<meta name="robots" content="noindex">' if shut else ""
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                     f'<title>{title}</title><meta name="description" content="{title} '
                     f'explained in detail for travellers and residents alike.">'
                     f'<link rel="canonical" href="{SITE}{path}">{robots}</head><body>'
                     f'<nav><a href="/">Home</a> <a href="/visa/">Visa</a></nav><main>'
                     f'<h1>{title}</h1><p>{body}</p></main></body></html>')

    for i, name in enumerate(names):
        for q in range(per):
            path = f"/visa/{name}/q{q:02d}/"
            r = random.Random(i * 1000 + q)
            write(path, f"Visa {name} question {q}",
                  " ".join(r.choice(WORDS) for _ in range(260)), i < closed)
            hub.append(path)
            if i >= closed or map_mode == "all":
                listed.append(path)
    links = "".join(f' <a href="{p}">{p}</a>' for p in hub)
    r = random.Random(7)
    write("/", "Home of the demo visa guide",
          " ".join(r.choice(WORDS) for _ in range(260)) + links)
    write("/visa/", "Visa hub", " ".join(r.choice(WORDS) for _ in range(260)) + links)
    if map_mode:
        with open(os.path.join(folder, "sitemap.xml"), "w", encoding="utf-8") as fh:
            fh.write(sitemap(SITE + u for u in listed))
    return folder


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-127-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def demo(self):
        folder = self.path("site")
        shutil.copytree(DEMO, folder)
        return folder


class SitemapTrust(Base):
    """«Нет в sitemap» значит «убрана намеренно» только для полного списка."""

    def test_stale_build_sitemap_does_not_lower_noindex(self):
        folder = self.demo()
        with open(os.path.join(folder, "sitemap.xml"), "w", encoding="utf-8") as fh:
            fh.write(sitemap([SITE + "/"]))
        result, printed, _ = run_check(folder)
        self.assertEqual(counts(result)[("critical", "noindex")], 1)
        self.assertIn("noindex не сверен с sitemap", printed)
        self.assertNotIn("понижены до сведений", printed)

    def test_stale_build_sitemap_keeps_the_group_critical(self):
        folder = catalogue(self.path("g"))
        with open(os.path.join(folder, "sitemap.xml"), "w", encoding="utf-8") as fh:
            fh.write(sitemap([SITE + "/"]))
        result, _, _ = run_check(folder)
        self.assertEqual(counts(result)[("critical", "noindex-group")], 1)

    def test_sitemap_for_another_host_does_not_lower_noindex(self):
        folder = self.demo()
        path = os.path.join(folder, "sitemap.xml")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body.replace(SITE, "http://localhost:3000"))
        for extra in ((), ("--sitemap", path)):
            result, _, _ = run_check(folder, *extra)
            self.assertEqual(counts(result)[("critical", "noindex")], 1, extra)

    def test_full_sitemap_still_lowers_unlisted_noindex(self):
        folder = catalogue(self.path("g"), map_mode="open")
        result, printed, _ = run_check(folder)
        got = counts(result)
        self.assertEqual(got[("info", "noindex-group")], 1)
        self.assertEqual(got[("critical", "noindex-group")], 0)
        group = [i for i in result["issues"] if i["code"] == "noindex-group"][0]
        self.assertIn("сведением. В sitemap их нет", group["message"])

    def test_listed_group_is_counted_once_and_no_negative_note(self):
        folder = catalogue(self.path("g"), map_mode="all")
        result, printed, _ = run_check(folder)
        got = counts(result)
        self.assertEqual(got[("critical", "noindex-group")], 1)
        self.assertEqual(got[("critical", "noindex")], 0)
        self.assertNotIn(": -", printed)
        self.assertNotIn("понижены до сведений", printed)


class LargeBranches(Base):
    """Двадцать вопросов на страну — та же авария, что и пять."""

    def test_large_closed_branches_form_a_group(self):
        small = run_check(catalogue(self.path("small"), per=5))[0]
        large = run_check(catalogue(self.path("large"), per=20))[0]
        self.assertEqual(counts(small)[("critical", "noindex-group")], 1)
        self.assertEqual(counts(large)[("critical", "noindex-group")], 1)
        self.assertEqual(counts(large)[("info", "noindex")], 80)

    def test_closed_documentation_versions_stay_a_decision(self):
        names = ["1.0", "1.1", "1.2", "1.3"] + [f"topic{n}" for n in range(9)]
        result = run_check(catalogue(self.path("docs"), per=20, names=names))[0]
        self.assertEqual(counts(result)[("critical", "noindex-group")], 0)
        self.assertEqual(counts(result)[("critical", "noindex")], 0)

    def test_section_note_dropped_when_sitemap_raises_it(self):
        folder = self.path("old")
        catalogue(folder, branches=3, per=10, closed=0)
        for n in range(20):
            d = os.path.join(folder, "old", f"p{n}")
            os.makedirs(d)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f'<html><head><title>Old page {n}</title>'
                         f'<meta name="robots" content="noindex"></head>'
                         f'<body><p>{" ".join(WORDS * 5)}</p></body></html>')
        urls = [SITE + "/", SITE + "/visa/"]
        urls += [f"{SITE}/visa/c{b:02d}/q{q:02d}/" for b in range(3) for q in range(10)]
        urls += [f"{SITE}/old/p{n}/" for n in range(20)]
        path = self.path("map.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(sitemap(urls))
        result, printed, _ = run_check(folder, "--sitemap", path)
        self.assertEqual(counts(result)[("critical", "noindex")], 20)
        self.assertNotIn("раздел /old/", printed)


class Portfolio(Base):
    """Портфель и `check` дают один счёт."""

    def portfolio(self, spec):
        path = self.path("pf.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"projects": [spec]}, fh)
        out = self.path("pf-out/p.json")
        code, _ = run(["portfolio", path, "--out", out, "--strict"])
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)["projects"][0], code

    def test_next_robots_body_is_read(self):
        folder = self.demo()
        for name in ("robots.txt", "sitemap.xml"):
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            os.remove(path)
            os.makedirs(path)
            with open(path + ".body", "w", encoding="utf-8") as fh:
                fh.write(body)
        check = run_check(folder)[0]
        project, _ = self.portfolio({"name": "next", "root": folder, "site": SITE})
        crit = sum(1 for i in check["issues"] if i["level"] == "critical")
        self.assertEqual(project["counts"].get("critical", 0), crit)

    def test_group_collapsed_like_check(self):
        folder = catalogue(self.path("g"))
        project, _ = self.portfolio({"name": "g", "root": folder, "site": SITE})
        self.assertEqual(project["counts"].get("critical", 0), 1)

    def test_listed_closed_section_stays_critical(self):
        folder = self.path("old")
        catalogue(folder, branches=3, per=10, closed=0)
        for n in range(20):
            d = os.path.join(folder, "old", f"p{n}")
            os.makedirs(d)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f'<html><head><title>Old page {n}</title>'
                         f'<meta name="robots" content="noindex"></head>'
                         f'<body><p>{" ".join(WORDS * 5)}</p></body></html>')
        urls = [SITE + "/", SITE + "/visa/"]
        urls += [f"{SITE}/visa/c{b:02d}/q{q:02d}/" for b in range(3) for q in range(10)]
        urls += [f"{SITE}/old/p{n}/" for n in range(20)]
        path = self.path("map.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(sitemap(urls))
        project, code = self.portfolio({"name": "old", "root": folder, "site": SITE,
                                        "sitemap": path})
        self.assertGreaterEqual(project["counts"].get("critical", 0), 20)
        self.assertEqual(code, 1)

    def test_profile_title_is_translated(self):
        from indexgap import i18n
        folder = catalogue(self.path("g"))
        self.addCleanup(i18n.set_lang, "ru")
        with mock.patch.dict(os.environ, {"INDEXGAP_LANG": "en"}):
            i18n.set_lang("en")
            project, _ = self.portfolio({"name": "g", "root": folder, "site": SITE})
        self.assertNotRegex(project["profile_title"], "[А-Яа-я]")


class TemplatesAndBaseline(Base):
    def test_closed_branch_templates_carry_group_risk(self):
        result = run_check(catalogue(self.path("g"), per=12))[0]
        risk = {t["pattern"]: t["risk"] for t in result["templates"]}
        self.assertGreater(risk["/visa/c00/*/"], 50)
        self.assertGreater(risk["/visa/c00/*/"], risk["/visa/c09/*/"])

    def test_pages_absorbed_into_a_group_are_not_gone(self):
        before = run_check(catalogue(self.path("a"), closed=2, per=12))[0]
        base = self.path("a-out/r.json")
        after = run_check(catalogue(self.path("b"), closed=3, per=12),
                          "--baseline", base)[0]
        fixed = Counter((i["level"], i["code"]) for i in after["baseline"]["fixed"])
        self.assertEqual(fixed[("critical", "noindex")], 0)
        self.assertEqual(counts(before)[("critical", "noindex")], 24)
        new = Counter((i["level"], i["code"]) for i in after["baseline"]["new"])
        self.assertEqual(new[("info", "noindex")], 12)
        self.assertEqual(new[("critical", "noindex-group")], 1)

    def test_accepted_group_does_not_accept_a_newly_closed_branch(self):
        ignore = {"ignore": {"noindex-group": ["/visa/"]}}
        first = catalogue(self.path("a"), closed=3, per=8)
        second = catalogue(self.path("b"), closed=4, per=8)
        for folder in (first, second):
            with open(os.path.join(folder, "indexgap.json"), "w", encoding="utf-8") as fh:
                json.dump(ignore, fh)
        _, _, code = run_check(first, "--strict")
        self.assertEqual(code, 0)
        base = self.path("a-out/r.json")
        result, _, code = run_check(second, "--strict", "--baseline", base)
        new = Counter((i["level"], i["code"]) for i in result["baseline"]["new"])
        self.assertEqual(new[("critical", "noindex")], 8)
        self.assertEqual(code, 1)
        # Те же ветки, что в базе, — принятый долг, сборку не валят.
        _, _, code = run_check(first, "--strict", "--baseline", base)
        self.assertEqual(code, 0)


class Helpers(unittest.TestCase):
    def test_group_message_ends_sentences(self):
        from indexgap.subject import Said
        issues = [("critical", "/visa/", "noindex-group",
                   Said("в /visa/ закрыты ветки — тогда находка станет сведением",
                        [SITE + "/visa/a/q/"]))]
        out = checks.closed_off_map(issues, [SITE + "/"])
        self.assertIn("сведением. В sitemap", out[0][3])


if __name__ == "__main__":
    unittest.main()
