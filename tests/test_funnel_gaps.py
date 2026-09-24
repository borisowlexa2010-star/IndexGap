# -*- coding: utf-8 -*-
"""
Два пробела воронки, найденные прогоном по rumors.app с выгрузкой Search Console.

Первый. Воронка считала адреса, которые поисковик знает, а среди страниц сайта
их нет, — и нигде их не показывала. На rumors.app таких было девять, и среди
них тестовый стенд `stage1.` и внутренний `gitlab.`: самое важное, что говорила
выгрузка, лежало в JSON и не доходило до человека.

Второй. robots.txt объявлял три sitemap-файла, а `--sitemap` принимал один.
Один `sitemap.xml` давал 13 адресов, все три вместе — 94. Шаг «в sitemap»
занижался в семь раз без единого слова об этом.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import doctor

SITE = "https://example.com"


class TestUnknownUrls(unittest.TestCase):
    """Разбор того, что поисковик знает, а сайт — нет."""

    def group(self, keys):
        return doctor.foreign_urls({"indexed_unknown": keys}, SITE)

    def test_other_hosts_are_told_apart_from_the_site(self):
        found = self.group(["//stage1.example.com/sign-in", "//gitlab.example.com/",
                            "//example.com/gone"])
        self.assertEqual(sorted(found["other_hosts"]),
                         ["//gitlab.example.com/", "//stage1.example.com/sign-in"])
        self.assertEqual(found["missing"], ["//example.com/gone"])

    def test_files_are_not_mistaken_for_lost_pages(self):
        found = self.group(["//example.com/assets/hero.webp", "//example.com/doc.pdf"])
        self.assertEqual(sorted(found["files"]),
                         ["//example.com/assets/hero.webp", "//example.com/doc.pdf"])
        self.assertEqual(found["missing"], [])

    def test_hosts_are_grouped_for_the_report(self):
        found = self.group(["//dash.example.com/a", "//dash.example.com/b",
                            "//stage1.example.com/x"])
        self.assertEqual(found["by_host"], {"dash.example.com": 2, "stage1.example.com": 1})

    def test_www_is_the_same_site(self):
        found = self.group(["//www.example.com/old"])
        self.assertEqual(found["other_hosts"], [])
        self.assertEqual(found["missing"], ["//www.example.com/old"])


class TestSeveralSitemaps(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-sm-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def sitemap(self, name, urls):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                     + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
        return path

    def test_several_sitemaps_are_read_together(self):
        a = self.sitemap("a.xml", [SITE + "/1", SITE + "/2"])
        b = self.sitemap("b.xml", [SITE + "/2", SITE + "/3"])
        result = doctor.read_sitemaps([a, b])
        self.assertEqual(sorted(result["urls"]), [SITE + "/1", SITE + "/2", SITE + "/3"])
        self.assertEqual(result["errors"], [])

    def test_one_broken_sitemap_does_not_hide_the_others(self):
        a = self.sitemap("a.xml", [SITE + "/1"])
        result = doctor.read_sitemaps([a, os.path.join(self.dir, "missing.xml")])
        self.assertEqual(result["urls"], [SITE + "/1"])
        self.assertEqual(len(result["errors"]), 1)

    def test_sitemaps_robots_declares_but_nobody_passed_are_named(self):
        robots = os.path.join(self.dir, "robots.txt")
        with open(robots, "w", encoding="utf-8") as fh:
            fh.write("User-agent: *\nAllow: /\n"
                     f"Sitemap: {SITE}/sitemap.xml\n"
                     f"Sitemap: {SITE}/sitemap-blog.xml\n"
                     f"Sitemap: {SITE}/sitemap-landings.xml\n")
        missing = doctor.undeclared_sitemaps(robots, [f"{SITE}/sitemap.xml"])
        self.assertEqual(missing, [f"{SITE}/sitemap-blog.xml", f"{SITE}/sitemap-landings.xml"])

    def test_a_local_copy_counts_as_passed(self):
        """Скачанный sitemap-landings.xml — тот же файл, что объявлен по адресу."""
        robots = os.path.join(self.dir, "robots.txt")
        with open(robots, "w", encoding="utf-8") as fh:
            fh.write(f"Sitemap: {SITE}/sitemap.xml\nSitemap: {SITE}/sitemap-landings.xml\n")
        local = self.sitemap("sitemap-landings.xml", [SITE + "/1"])
        missing = doctor.undeclared_sitemaps(robots, [f"{SITE}/sitemap.xml", local])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
