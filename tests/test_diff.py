# -*- coding: utf-8 -*-
"""
`indexgap diff OLD NEW`: что сломает этот деплой.

Каждая сборка по отдельности может выглядеть прилично: пропавшая страница
не оставляет находки, а noindex на всём разделе — это одна строка в шаблоне.
Видно это только в сравнении со сборкой, которая сейчас на проде.
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import cli, diff

SITE = "https://example.com"
CITIES = 8


def page(title, words=80, head="", h1=None, description="Аренда техники в городе, цены"):
    body = " ".join(f"слово{i}" for i in range(words))
    links = "".join(f'<a href="/city/c{i}/">Город {i}</a> ' for i in range(CITIES))
    return (f"<!doctype html><html lang=\"ru\"><head><title>{title}</title>"
            f"<meta name=\"description\" content=\"{description}\">{head}</head>"
            f"<body><main><h1>{h1 or title}</h1><p>{body}</p>"
            f"<a href=\"/\">Главная</a> {links}</main></body></html>")


class Build:
    def __init__(self, root):
        self.root = root
        self.write("index.html", page("Аренда техники"))
        for i in range(CITIES):
            self.write(f"city/c{i}/index.html", page(f"Аренда в городе {i}"))

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def remove(self, name):
        shutil.rmtree(os.path.join(self.root, name))


class Diff(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-diff-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old = Build(os.path.join(self.dir, "old"))
        self.new = Build(os.path.join(self.dir, "new"))
        self.out = os.path.join(self.dir, "d.html")

    def run_diff(self, *extra):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            code = cli.main(["diff", self.old.root, self.new.root, "--site", SITE,
                             "--out", self.out, *extra])
        data = None
        if os.path.exists(os.path.join(self.dir, "d.json")):
            with open(os.path.join(self.dir, "d.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        return code, data

    def codes(self, data, level=None):
        return [(i["code"], i["url"]) for i in data["items"]
                if level is None or i["level"] == level]

    def test_identical_builds_have_nothing_to_say(self):
        code, data = self.run_diff("--strict")
        self.assertEqual(code, 0)
        self.assertEqual(data["schema"], 2)
        self.assertIn("_indexgap", data)
        self.assertEqual(data["summary"], {"critical": 0, "warning": 0, "info": 0})
        self.assertTrue(os.path.exists(self.out))

    def test_a_removed_indexable_page_is_critical(self):
        self.new.remove("city/c3")
        code, data = self.run_diff("--strict")
        self.assertEqual(code, 1)
        self.assertIn(("page-removed", SITE + "/city/c3/"), self.codes(data, "critical"))
        self.assertIn("page-removed", self.stdout.getvalue())

    def test_without_strict_the_exit_code_is_zero(self):
        self.new.remove("city/c3")
        code, _ = self.run_diff()
        self.assertEqual(code, 0)

    def test_a_redirect_in_the_new_build_covers_the_removed_page(self):
        self.new.remove("city/c3")
        self.new.write("_redirects", "# moved\n/city/c3/  /city/c4/  301\n")
        code, data = self.run_diff("--strict")
        self.assertEqual(code, 0)
        self.assertIn(("page-redirected", SITE + "/city/c3/"), self.codes(data, "info"))
        self.assertEqual(data["redirects"], [os.path.relpath(
            os.path.join(self.new.root, "_redirects"))])

    def test_a_redirect_to_a_page_that_is_also_gone_is_a_warning(self):
        self.new.remove("city/c3")
        self.new.write("_redirects", "/city/c3 /city/nowhere/ 301\n")
        _, data = self.run_diff()
        self.assertIn(("page-redirected", SITE + "/city/c3/"), self.codes(data, "warning"))

    def test_splat_rules_in_netlify_toml_and_vercel_json(self):
        rules = diff._netlify_toml('[[redirects]]\nfrom = "/city/*"\nto = "/towns/:splat"\n'
                                   'status = 301\n\n[build]\ncommand = "x"\n', "netlify.toml")
        self.assertEqual(diff.redirect_for(rules, SITE + "/city/c3/"), "/towns/:splat")
        rules = diff._vercel(json.dumps({"redirects": [
            {"source": "/city/:slug", "destination": "/towns/:slug", "permanent": True}]}),
            "vercel.json")
        self.assertEqual(diff.redirect_for(rules, SITE + "/city/c3/"), "/towns/:slug")
        self.assertEqual(diff.redirect_for(rules, SITE + "/city/c3/deeper/"), "")
        self.assertEqual(diff._netlify_lines("/old /new 404\n", "_redirects"), [])

    def test_a_page_that_gets_noindex_is_closed(self):
        self.new.write("city/c1/index.html",
                       page("Аренда в городе 1", head='<meta name="robots" content="noindex">'))
        code, data = self.run_diff("--strict")
        self.assertEqual(code, 1)
        self.assertIn(("page-closed", SITE + "/city/c1/"), self.codes(data, "critical"))
        closed = [i for i in data["items"] if i["code"] == "page-closed"][0]
        self.assertIn("noindex", closed["message"])
        # Та же беда не считается второй раз как новая находка `noindex`.
        self.assertFalse([i for i in data["items"] if i["code"] == "new-finding"
                          and i["url"] == SITE + "/city/c1/"])

    def test_a_canonical_that_starts_pointing_elsewhere_closes_the_page(self):
        self.new.write("city/c1/index.html", page(
            "Аренда в городе 1", head=f'<link rel="canonical" href="{SITE}/city/c2/">'))
        _, data = self.run_diff()
        closed = [i for i in data["items"] if i["code"] == "page-closed"]
        self.assertEqual([i["url"] for i in closed], [SITE + "/city/c1/"])
        self.assertIn("/city/c2/", closed[0]["message"])

    def test_a_template_wide_title_change_is_summarised_per_pattern(self):
        for i in range(CITIES):
            self.new.write(f"city/c{i}/index.html", page(f"Город {i} — аренда",
                                                         h1=f"Аренда в городе {i}"))
        _, data = self.run_diff()
        changes = [c for c in data["template_changes"] if c["template"]]
        self.assertEqual([(c["pattern"], c["field"]) for c in changes], [("/city/*/", "title")])
        self.assertEqual(changes[0]["changed"], CITIES)
        self.assertEqual(changes[0]["pages"], CITIES)
        self.assertIn(("template-change", "/city/*/"), self.codes(data, "warning"))
        self.assertIn("/city/*/", self.stdout.getvalue())

    def test_one_changed_title_is_not_a_template_change(self):
        self.new.write("city/c1/index.html", page("Новое имя", h1="Аренда в городе 1"))
        _, data = self.run_diff()
        self.assertFalse([c for c in data["template_changes"] if c["template"]])
        self.assertNotIn(("template-change", "/city/*/"), self.codes(data, "warning"))

    def test_text_that_halves_is_flagged(self):
        self.new.write("city/c2/index.html", page("Аренда в городе 2", words=20))
        _, data = self.run_diff()
        self.assertIn(("text-shrunk", SITE + "/city/c2/"), self.codes(data, "warning"))
        shrunk = data["shrunk"][0]
        self.assertGreater(shrunk["drop"], 0.5)

    def test_new_pages_are_counted_per_pattern(self):
        for i in range(CITIES, CITIES + 6):
            self.new.write(f"city/c{i}/index.html", page(f"Аренда в городе {i}"))
        self.new.write("about/index.html", page("О нас"))
        _, data = self.run_diff()
        self.assertEqual(data["added"]["total"], 7)
        by = {a["pattern"]: a["pages"] for a in data["added"]["by_pattern"]}
        self.assertEqual(by, {"/city/*/": 6, "other": 1})

    def test_a_new_critical_finding_is_reported(self):
        # Пропавший title — находка `check`, а не изменение страницы как таковой.
        self.new.write("city/c5/index.html",
                       page("", h1="Аренда в городе 5").replace("<title></title>", ""))
        code, data = self.run_diff("--strict")
        self.assertEqual(code, 1)
        new = [i for i in data["items"] if i["code"] == "new-finding"]
        self.assertIn(SITE + "/city/c5/", [i["url"] for i in new])
        self.assertIn("no-title", [i["code"] for i in data["findings"]["new"]])

    def test_no_checks_skips_the_findings_delta(self):
        code, data = self.run_diff("--no-checks")
        self.assertEqual(code, 0)
        self.assertIsNone(data["findings"])

    def test_bad_input_exits_2(self):
        self.stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(self.stderr):
            code = cli.main(["diff", self.old.root, os.path.join(self.dir, "nope"),
                             "--site", SITE, "--out", self.out])
        self.assertEqual(code, 2)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["diff", self.old.root, self.old.root,
                                       "--site", SITE, "--out", self.out]), 2)

    def test_site_is_required(self):
        err = io.StringIO()
        here = os.getcwd()
        os.chdir(self.dir)              # чтобы indexgap.json самого репозитория не нашёлся
        self.addCleanup(os.chdir, here)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = cli.main(["diff", self.old.root, self.new.root, "--out", self.out])
        self.assertEqual(code, 2)
        self.assertIn("--site", err.getvalue())

    def test_the_html_report_lists_the_changes(self):
        self.new.remove("city/c3")
        self.run_diff()
        with open(self.out, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("<!-- indexgap-report -->", html)
        self.assertIn("page-removed", html)
        self.assertIn("/city/c3/", html)

    def test_the_report_does_not_overwrite_a_foreign_file(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            fh.write("<html>чужой файл</html>")
        code, _ = self.run_diff()
        self.assertEqual(code, 2)


class English(unittest.TestCase):
    """В английском режиме у diff не остаётся русского — ни в консоли, ни в отчёте."""

    def setUp(self):
        from indexgap import i18n
        self.i18n = i18n
        i18n.set_lang("en")
        self.dir = tempfile.mkdtemp(prefix="indexgap-diff-en-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def tearDown(self):
        self.i18n.set_lang("ru")

    def test_everything_is_english(self):
        for side in ("old", "new"):
            for i in range(8):
                if side == "new" and i == 3:
                    continue
                head = ('<meta name="robots" content="noindex">'
                        if side == "new" and i == 1 else "")
                title = f"City {i} rental" if side == "old" else f"Rental in city {i}"
                words = 20 if side == "new" and i == 2 else 80
                path = os.path.join(self.dir, side, "city", f"c{i}", "index.html")
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(f"<html lang=\"en\"><head><title>{title}</title>{head}</head>"
                             f"<body><main><h1>City {i}</h1><p>"
                             + " ".join(f"word{n}" for n in range(words))
                             + "</p></main></body></html>")
        out = io.StringIO()
        report = os.path.join(self.dir, "d.html")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["diff", os.path.join(self.dir, "old"), os.path.join(self.dir, "new"),
                      "--site", SITE, "--lang", "en", "--out", report])
        with open(report, encoding="utf-8") as fh:
            html = fh.read()
        for text in (out.getvalue(), html):
            self.assertEqual(re.findall(r"[А-Яа-яЁё]", text), [], text[:300])
        self.assertIn("page-removed", out.getvalue())
        self.assertIn("template change", out.getvalue())


if __name__ == "__main__":
    unittest.main()
