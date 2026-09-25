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



class TestImpressionsAreNotIndex(unittest.TestCase):
    """
    Выгрузка «Эффективность» из Search Console — отчёт о показах, а не об индексе.

    На eventiq.io (молодой сайт, средняя позиция 15,5) воронка печатала «в индексе
    12, потеряно 26 — причина не установлена». У 26 страниц просто не было
    показов за три месяца. Оговорка жила только в HTML-отчёте, а консоль
    уверенно называла непоказанное непроиндексированным.
    """

    PERFORMANCE = ("Top pages,Clicks,Impressions,CTR,Position\n"
                   "https://example.com/a,3,40,7.5%,8\n")
    COVERAGE = "URL,Last crawled\nhttps://example.com/a,2026-09-01\n"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-impr-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_a_performance_export_is_marked_as_impressions(self):
        result = doctor.read_sources([f"google={self.write('p.csv', self.PERFORMANCE)}"])
        self.assertEqual(result["impressions"], ["google"])

    def test_an_indexing_export_is_not(self):
        result = doctor.read_sources([f"google={self.write('c.csv', self.COVERAGE)}"])
        self.assertEqual(result["impressions"], [])

    def pages(self):
        from indexgap import core
        root = os.path.join(self.dir, "site")
        for name in ("a", "b", "c"):
            os.makedirs(os.path.join(root, name))
            with open(os.path.join(root, name, "index.html"), "w", encoding="utf-8") as fh:
                # Связаны друг с другом: иначе «сироты» объясняют всё раньше,
                # чем дело доходит до остатка без причины.
                links = "".join(f'<a href="/{o}/">{o}</a>' for o in "abc" if o != name)
                fh.write(f"<html><head><title>{name}</title></head><body><main>"
                         f"<h1>{name}</h1><p>{'слово ' * 300}</p>{links}</main></body></html>")
        return core.load_pages(root, SITE)[0]

    def test_the_step_is_named_after_what_the_export_proves(self):
        result = doctor.funnel(self.pages(), by_engine={"google": [SITE + "/a/"]},
                               impressions=["google"])
        self.assertTrue(result["impressions_only"])
        names = [s["name"] for s in result["steps"]]
        self.assertIn("С показами в поиске", names)

    def test_a_real_index_export_next_to_it_keeps_the_index_step(self):
        result = doctor.funnel(self.pages(),
                               by_engine={"google": [SITE + "/a/"], "bing": [SITE + "/b/"]},
                               impressions=["google"])
        self.assertFalse(result["impressions_only"])

    def test_unexplained_losses_are_called_what_they_are(self):
        from indexgap import checks
        pages = self.pages()
        analysis = checks.run_all(pages, SITE + "/a/")
        funnel = doctor.funnel(pages, by_engine={"google": [SITE + "/a/"]},
                               impressions=["google"])
        causes = [c["cause"] for c in doctor.explain(funnel, analysis)]
        self.assertNotIn("причина не установлена локально", causes)
        self.assertTrue(any("показов" in c for c in causes), causes)


class TestFragments(unittest.TestCase):
    """Search Console отдаёт переходы к разделу строками вида `/#how-it-works`.
    На eventiq.io таких было девять. Это та же страница, а не пропавшая."""

    def test_fragment_rows_fold_into_their_page(self):
        from indexgap import core
        root = tempfile.mkdtemp(prefix="indexgap-frag-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html><head><title>Home</title></head><body><main><h1>Home</h1>"
                     f"<p>{'слово ' * 300}</p></main></body></html>")
        pages = core.load_pages(root, SITE)[0]
        result = doctor.funnel(pages, by_engine={"google": [
            SITE + "/", SITE + "/#how-it-works", SITE + "/#solution"]})
        self.assertEqual(result["indexed_unknown"], [])
        self.assertEqual(doctor.foreign_urls(result, SITE)["missing"], [])


if __name__ == "__main__":
    unittest.main()
