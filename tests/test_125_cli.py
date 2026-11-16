# -*- coding: utf-8 -*-
"""
1.25: командная строка и чтение входов.

* строка вместо списка в `fact_units` / `vague_anchors` разбиралась по буквам
  и молча выключала проверку;
* одна мусорная строка в access-логе роняла `doctor --logs`;
* ячейка датасета длиннее 131 072 символов роняла `check`;
* `--site` с непарной «[» падал трассировкой, а с `?x=1` или пробелом
  попадал в sitemap невалидным <loc>;
* `--no-content` с `--dataset` молча выключал сверку фактов;
* каталог-симлинк в сборке пропускался, а ссылки на него считались битыми;
* страница в KOI8-R без объявления читалась как cp1251.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, crawlers, generate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"
WRONG = "the average commute to the centre is 41 minutes."
RIGHT = "the average commute to the centre is 34 minutes."


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
        code = cli.main(list(argv))
    return code, out.getvalue() + err.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.site = os.path.join(self.tmp, "site")
        shutil.copytree(DEMO, self.site)

    def plant_wrong_fact(self):
        path = os.path.join(self.site, "rent", "berlin", "index.html")
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn(RIGHT, html)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html.replace(RIGHT, WRONG))

    def check(self, *extra):
        out = os.path.join(self.tmp, "r.json")
        code, text = run("check", self.site, "--site", SITE,
                         "--dataset", os.path.join(self.site, "cities.csv"),
                         "--keyword", "keyword", "--out", out, *extra)
        data = {}
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
        return code, text, data


class ConfigLists(Case):
    def write_config(self, data):
        with open(os.path.join(self.site, "indexgap.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_a_list_of_units_still_catches_the_wrong_fact(self):
        self.plant_wrong_fact()
        self.write_config({"fact_units": ["minutes"]})
        code, _, data = self.check()
        self.assertEqual(code, 0)
        self.assertTrue(any(i["code"] == "unsupported-number" and "berlin" in i["url"]
                            for i in data["issues"]))

    def test_a_string_of_units_is_rejected_instead_of_split_into_letters(self):
        self.plant_wrong_fact()
        for key in ("fact_units", "extra_fact_units", "vague_anchors"):
            self.write_config({key: "minutes"})
            code, text, _ = self.check()
            self.assertEqual(code, 2, key)
            self.assertIn(f"`{key}`", text)
            self.assertIn("списком строк", text)


class Logs(Case):
    def test_a_garbage_request_target_is_skipped(self):
        ua = "Mozilla/5.0 (compatible; GPTBot/1.0)"
        lines = [
            f'1.2.3.4 - - [10/Nov/2026:10:00:00 +0000] "GET /rent/berlin/ HTTP/1.1" 200 512 "-" "{ua}"',
            f'5.6.7.8 - - [10/Nov/2026:10:01:00 +0000] "GET //[evil HTTP/1.1" 404 0 "-" "{ua}"',
            f'5.6.7.8 - - [10/Nov/2026:10:02:00 +0000] "GET http://[bad/ HTTP/1.1" 404 0 "-" "{ua}"',
        ]
        path = os.path.join(self.tmp, "access.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        result = crawlers.read_logs([path], SITE)
        self.assertEqual(result["lines"], 3)
        self.assertEqual(result["bot_hits"], 1)
        self.assertEqual([e[5] for e in result["events"]], ["/rent/berlin/"])


class BigCell(Case):
    def test_a_cell_over_the_csv_limit_is_read(self):
        path = os.path.join(self.tmp, "big.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('keyword,city,notes\nberlin,Berlin,"' + "x" * 200000 + '"\n')
        data = generate.read_dataset(path)
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(len(data["rows"][0]["notes"]), 200000)


class SiteUrl(unittest.TestCase):
    def test_an_unbalanced_bracket_is_a_clean_error(self):
        for bad in ("http://[::1", "https://[demo.example", "https://demo.example:port"):
            with self.assertRaises(core.SourceError, msg=bad):
                core.check_site_url(bad)

    def test_a_query_or_fragment_is_rejected(self):
        for bad in ("https://demo.example/?x=1", "https://demo.example/#top",
                    "https://demo.example/?"):
            with self.assertRaises(core.SourceError) as caught:
                core.check_site_url(bad)
            self.assertIn("https://demo.example/", str(caught.exception))

    def test_the_base_path_is_percent_encoded(self):
        self.assertEqual(core.check_site_url("https://demo.example/sub dir/"),
                         "https://demo.example/sub%20dir/")
        # Уже закодированный путь не кодируется второй раз.
        self.assertEqual(core.check_site_url("https://demo.example/sub%20dir"),
                         "https://demo.example/sub%20dir/")

    def test_ordinary_addresses_are_unchanged(self):
        for good, expected in (("https://demo.example", "https://demo.example/"),
                               ("https://demo.example/", "https://demo.example/"),
                               ("http://example.com:8080/docs/", "http://example.com:8080/docs/"),
                               ("http://[::1]:8000", "http://[::1]:8000/")):
            self.assertEqual(core.check_site_url(good), expected)

    def test_the_command_does_not_crash(self):
        code, text = run("check", DEMO, "--site", "http://[::1", "--out",
                         os.path.join(tempfile.mkdtemp(prefix="indexgap-125-"), "r.html"))
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", text)


class NoContent(Case):
    def test_no_content_with_a_dataset_says_facts_were_not_checked(self):
        self.plant_wrong_fact()
        code, text, data = self.check("--no-content", "--strict")
        self.assertIn("--no-content выключает сверку фактов", text)
        self.assertTrue(any("--no-content" in n for n in data.get("notes") or []))

    def test_no_note_without_a_dataset(self):
        out = os.path.join(self.tmp, "r.json")
        _, text = run("check", self.site, "--site", SITE, "--no-content", "--out", out)
        self.assertNotIn("--no-content выключает", text)


@unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "нужны симлинки")
class SymlinkedDirectory(Case):
    def setUp(self):
        super().setUp()
        shared = os.path.join(self.tmp, "shared", "guide")
        os.makedirs(shared)
        with open(os.path.join(shared, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><html lang=\"en\"><head><title>Guide</title></head>"
                     "<body><h1>Guide</h1><p>How to rent a flat.</p>"
                     "<a href=\"/\">Home</a></body></html>")
        os.symlink(os.path.join("..", "shared", "guide"), os.path.join(self.site, "guide"))
        # Ссылка внутрь сборки и петля на каталог выше не обходятся.
        os.symlink(os.path.join("rent", "berlin"), os.path.join(self.site, "alias"))
        os.symlink("..", os.path.join(self.site, "rent", "up"))

    def test_pages_behind_a_symlinked_directory_are_loaded(self):
        pages, _ = core.load_pages(self.site, SITE + "/")
        urls = {p.url for p in pages}
        self.assertIn(SITE + "/guide/", urls)
        self.assertNotIn(SITE + "/alias/", urls)
        self.assertFalse(any("/rent/up/" in u for u in urls))
        plain = [u for u in urls if u not in (SITE + "/guide/",)]
        self.assertEqual(len(plain), len(set(plain)))


class Koi8(unittest.TestCase):
    TITLE = "Аренда квартиры в Берлине: цены и районы"
    BODY = ("Однокомнатная квартира в Берлине стоит около 1450 долларов в месяц. "
            "Залог обычно составляет три месячные платы.")

    def read(self, encoding, title=None):
        html = (f"<html><head><title>{title or self.TITLE}</title></head>"
                f"<body><p>{self.BODY}</p></body></html>")
        folder = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "index.html")
        with open(path, "wb") as fh:
            fh.write(html.encode(encoding))
        return core.read_text(path)

    def test_undeclared_koi8_r_is_detected(self):
        text, encoding = self.read("koi8_r")
        self.assertEqual(encoding, "koi8-r")
        self.assertIn(self.TITLE, text)

    def test_cp1251_stays_cp1251(self):
        text, encoding = self.read("cp1251")
        self.assertEqual(encoding, "cp1251")
        self.assertIn(self.TITLE, text)

    def test_cp1251_with_a_capitalised_heading_stays_cp1251(self):
        text, encoding = self.read("cp1251", title="АРЕНДА КВАРТИРЫ В БЕРЛИНЕ")
        self.assertEqual(encoding, "cp1251")
        self.assertIn("АРЕНДА КВАРТИРЫ", text)

    def test_mac_cyrillic_label_is_understood(self):
        html = ('<html><head><meta charset="x-mac-cyrillic"><title>'
                + self.TITLE + "</title></head><body></body></html>")
        folder = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "index.html")
        with open(path, "wb") as fh:
            fh.write(html.encode("mac_cyrillic"))
        text, _ = core.read_text(path)
        self.assertIn(self.TITLE, text)


if __name__ == "__main__":
    unittest.main()
