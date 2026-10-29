# -*- coding: utf-8 -*-
"""
Страницы у первой страницы выдачи — самый дешёвый рост.

Выгрузка «Эффективность → Страницы» из Search Console несёт средние позиции.
Страница на 8–20-м месте с показами уже нравится поисковику; доработать её
дешевле, чем написать новую. Пакет читал из этой выгрузки только адреса.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, doctor

SITE = "https://example.com"
CSV = ("Top pages,Clicks,Impressions,CTR,Position\n"
       "https://example.com/a/,40,3000,1.3%,9.4\n"
       "https://example.com/b/,2,900,0.2%,14.0\n"
       "https://example.com/c/,300,5000,6%,3.1\n"
       "https://example.com/d/,0,4,0%,12.0\n"
       "https://example.com/e/,0,800,0%,35.0\n"
       "https://example.com/gone/,1,700,0.1%,11.0\n")


class NearPageOne(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-near-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name in "abcde":
            path = os.path.join(self.dir, "site", name, "index.html")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"<!doctype html><html><head><title>Page {name}</title></head><body>"
                         f"<main><h1>Page {name}</h1><p>text</p><a href=\"/\">home</a></main>"
                         "</body></html>")
        self.csv = os.path.join(self.dir, "gsc-pages.csv")
        with open(self.csv, "w", encoding="utf-8") as fh:
            fh.write(CSV)

    def test_positions_eight_to_twenty_with_impressions(self):
        pages = core.load_pages(os.path.join(self.dir, "site"), SITE)[0]
        near = doctor.near_page_one([f"google={self.csv}"], pages, SITE)
        self.assertEqual([(r["url"], r["position"]) for r in near],
                         [(SITE + "/a/", 9.4), (SITE + "/b/", 14.0)])
        self.assertEqual(near[0]["impressions"], 3000)

    def test_an_index_list_without_positions_gives_nothing(self):
        plain = os.path.join(self.dir, "list.csv")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write("URL,Last crawled\nhttps://example.com/a/,2026-10-01\n")
        pages = core.load_pages(os.path.join(self.dir, "site"), SITE)[0]
        self.assertEqual(doctor.near_page_one([f"google={plain}"], pages, SITE), [])

    def test_doctor_prints_and_writes_them(self):
        out = os.path.join(self.dir, "doc.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["doctor", os.path.join(self.dir, "site"), "--site", SITE,
                             "--indexed", f"google={self.csv}", "--out", out])
        self.assertEqual(code, 0)
        self.assertIn(SITE + "/a/", buf.getvalue())
        data = json.load(open(out, encoding="utf-8"))
        self.assertEqual([r["url"] for r in data["near_page_one"]], [SITE + "/a/", SITE + "/b/"])


if __name__ == "__main__":
    unittest.main()
