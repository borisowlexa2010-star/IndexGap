# -*- coding: utf-8 -*-
"""
1.29 (g21): plan, brief и поверхность командной строки.

Однобуквенные и «c++»-ключи, -ино/-ово у названий мест, собственный slug в
проверке совпадений, номера строк файла, кириллические имена нарядов,
принятые через ignore почти-дубли, нейтральный совет без датасета,
отрицательные пределы, разорванный пайп, базовая линия при выключенных
проверках, портфель и чужие файлы, сокращённый --lang, diff без --site.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, generate, repair

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(os.path.dirname(HERE), "examples", "demo-site")
SITE = "https://demo.example/"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, self.cwd)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def demo(self, name="demo"):
        target = os.path.join(self.dir, name)
        shutil.copytree(DEMO, target)
        return target


class IntentTest(unittest.TestCase):
    def test_single_letters_and_symbols_are_part_of_the_intent(self):
        key = generate.intent_key
        self.assertNotEqual(key("vitamin c benefits"), key("vitamin d benefits"))
        self.assertNotEqual(key("class b license"), key("class c license"))
        self.assertNotEqual(key("c++ course"), key("c course"))
        self.assertNotEqual(key("c# course"), key("c++ course"))
        self.assertNotEqual(key("iphone x"), key("iphone"))
        # Служебные слова по-прежнему не меняют интент.
        self.assertEqual(key("виза в таиланд"), key("таиланд виза"))

    def test_place_names_in_ino_ovo_keep_their_ending(self):
        key = generate.intent_key
        self.assertNotEqual(key("аренда квартир пушкино"), key("аренда квартир пушкин"))
        self.assertNotEqual(key("иваново квартиры"), key("иванов квартиры"))
        # Словоформы по-прежнему сводятся.
        self.assertEqual(key("квартиры москва"), key("квартира москва"))


class PlanTest(Temp):
    def test_own_slugs_decide_the_collision(self):
        path = self.write("s.csv", "keyword,slug,price\nc++ course,cpp-course,10\n"
                                   "c# course,csharp-course,12\nc course,c-course,9\n")
        data = generate.read_dataset(path)
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        self.assertEqual(len(audit["keep"]), 3, audit["rejected"])

        path = self.write("d.csv", "keyword,slug,price\nrent in berlin,berlin,1\n"
                                   "berlin apartments for rent,berlin,2\n"
                                   "rent munich,Munich,3\nmunich flats,munich,4\n")
        data = generate.read_dataset(path)
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        self.assertEqual(sorted(r["code"] for r in audit["rejected"]),
                         ["slug-collision", "slug-collision"])
        # Шаблон с другой колонкой разводит одинаковые slug по каталогам.
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword",
                                       {"own_slug_is_path": False})
        self.assertEqual(len(audit["keep"]), 4)

    def test_write_failures_give_a_nonzero_code(self):
        path = self.write("d.csv", "keyword,slug,city\nrent a,same,x\nrent b,same,x\n")
        code, out, _ = run("plan", path, "--pattern", "{city}/{slug}.md",
                           "--write", "--out-dir", os.path.join(self.dir, "out"))
        self.assertEqual(code, 1, out)

    def test_row_numbers_are_file_lines(self):
        path = self.write("s.csv", 'keyword,price\nberlin rent,10\n,,\n\n"munich\nrent",12\n'
                                   "hamburg rent,1\nhamburg rent,2\n,5\n")
        data = generate.read_dataset(path)
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword",
                                       lines=data["lines"])
        rows = {r["code"]: r["row"] for r in audit["rejected"]}
        self.assertEqual(rows, {"exact-duplicate": 8, "empty-keyword": 9})

    def test_min_filled_is_a_share(self):
        path = self.write("s.csv", "keyword,price\nberlin rent,10\n")
        code, _, err = run("plan", path, "--min-filled", "5")
        self.assertEqual(code, 2)
        self.assertIn("--min-filled", err)


class BriefNamesTest(unittest.TestCase):
    def test_cyrillic_url_gives_a_readable_short_name(self):
        url = ("https://demo.example/%D0%B0%D1%80%D0%B5%D0%BD%D0%B4%D0%B0-"
               "%D0%BC%D0%BE%D1%81%D0%BA%D0%B2%D0%B0/")
        self.assertEqual(repair._slug(url), "аренда-москва")
        long_url = "https://demo.example/" + "квартира-" * 40 + "/"
        name = repair._slug(long_url)
        self.assertLessEqual(len(name.encode("utf-8")), 200)
        self.assertNotEqual(name, repair._slug(long_url.replace("квартира", "комната")))


class BriefTest(Temp):
    def test_accepted_near_duplicates_get_no_group_brief(self):
        root = self.demo()
        self.write("demo/indexgap.json", json.dumps({
            "site": "https://demo.example",
            "ignore": {"near-duplicate": ["/rent/frankfurt/", "/rent/stuttgart/"]}}))
        out = os.path.join(self.dir, "b")
        code, text, _ = run("brief", root, "--config", os.path.join(root, "indexgap.json"),
                            "--dataset", os.path.join(root, "cities.csv"),
                            "--write", "--out-dir", out)
        self.assertEqual(code, 0, text)
        self.assertFalse(os.path.isdir(os.path.join(out, "_duplicates")))

    def test_without_dataset_the_group_advice_is_neutral(self):
        root = self.demo()
        out = os.path.join(self.dir, "b")
        code, text, _ = run("brief", root, "--site", SITE, "--write", "--out-dir", out)
        self.assertEqual(code, 0, text)
        folder = os.path.join(out, "_duplicates")
        body = "".join(open(os.path.join(folder, n), encoding="utf-8").read()
                       for n in os.listdir(folder))
        self.assertIn("сначала реши, один ли это интент", body)

    def test_negative_limit_is_refused(self):
        root = self.demo()
        code, _, err = run("brief", root, "--site", SITE, "--limit", "-3")
        self.assertEqual(code, 2)
        self.assertIn("--limit", err)


class CliTest(Temp):
    def test_broken_pipe_keeps_the_strict_code_and_the_report(self):
        root = self.demo()
        env = dict(os.environ, PYTHONPATH=os.path.dirname(HERE))
        script = ("import sys\nfrom indexgap import cli\n"
                  "sys.exit(cli.main(sys.argv[1:]))\n")
        proc = subprocess.Popen(
            [sys.executable, "-c", script, "check", root, "--strict", "--out", "bp.html"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=self.dir, env=env)
        proc.stdout.readline()
        proc.stdout.close()
        self.assertEqual(proc.wait(timeout=120), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "bp.html")))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "bp.json")))

    def test_switched_off_checks_are_not_gone(self):
        root = self.demo()
        dataset = os.path.join(root, "cities.csv")
        run("check", root, "--dataset", dataset, "--out", "base.html")
        code, out, _ = run("check", root, "--dataset", dataset, "--baseline", "base.json",
                           "--no-aeo", "--out", "x.html")
        with open("x.json", encoding="utf-8") as fh:
            diff = json.load(fh)["baseline"]
        self.assertEqual(diff["fixed"], [])
        self.assertTrue(diff["unchecked"])
        self.assertEqual(diff["checks_off"], ["aeo"])

    def test_portfolio_does_not_overwrite_foreign_files(self):
        self.demo()
        self.write("reps/demo.html", "<html>notes</html>")
        self.write("p.json", json.dumps({"projects": [
            {"name": "demo", "root": "demo", "site": SITE}]}))
        code, _, err = run("portfolio", "p.json", "--reports", "reps", "--out", "pf.html")
        self.assertEqual(code, 2)
        with open("reps/demo.html", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "<html>notes</html>")

    def test_abbreviated_lang_is_honoured(self):
        code, out, _ = run("profiles", "--la", "en")
        try:
            self.assertEqual(code, 0)
            self.assertNotRegex(out.splitlines()[0], "[а-яА-Я]")
        finally:
            cli.preset_language(["--lang", "ru"])

    def test_cite_needs_at_least_one_run_and_question(self):
        code, _, err = run("cite", "--domain", "demo.example", "--prompt", "q", "--runs", "0")
        self.assertEqual(code, 2)
        self.assertIn("--runs", err)
        code, _, err = run("cite", "--domain", "demo.example", "--prompt", "q", "--limit", "0")
        self.assertEqual(code, 2)

    def test_doctor_history_file_is_refused_before_work(self):
        root = self.demo()
        self.write("h.json", "{}")
        code, _, err = run("doctor", root, "--site", SITE, "--history", "h.json",
                           "--out", "dz.html")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists("dz.html"))

    def test_notify_write_key_error_goes_to_stderr(self):
        root = self.demo()
        code, out, err = run("notify", root, "--site", SITE, "--key", "abcdefgh1234",
                             "--offline", "--write-key")
        self.assertEqual(code, 1)
        self.assertIn("--write-key", err)
        self.assertNotIn("--write-key", out)

    def test_empty_out_is_refused_up_front(self):
        root = self.demo()
        code, out, err = run("check", root, "--site", SITE, "--out", "")
        self.assertEqual(code, 2)
        self.assertIn("--out", err)
        self.assertNotIn("Разобрано страниц", out)

    def test_diff_detects_the_site_and_localises_levels(self):
        old = self.demo("old")
        new = self.demo("new")
        shutil.rmtree(os.path.join(new, "rent", "hamburg"))
        code, out, err = run("diff", old, new, "--out", "d.html")
        self.assertEqual(code, 0, err)
        self.assertIn("критично page-removed", out)


if __name__ == "__main__":
    unittest.main()
