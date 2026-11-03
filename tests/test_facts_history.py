# -*- coding: utf-8 -*-
"""
1.22: цифры, разошедшиеся между языковыми версиями, и история прогонов.

Перевод — место, где факт портится тихо: читатель каждой версии видит
только свою. А без истории пакет советовал, но не показывал, сработали ли
правки.
"""

import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, facts, history

SITE = "https://example.com"
LANGS = ("en", "ar", "id", "de")


def alternates(slug, langs=LANGS, default="en"):
    links = "".join(f'<link rel="alternate" hreflang="{l}" href="{SITE}/{l}/{slug}/">'
                    for l in langs)
    if default:
        links += f'<link rel="alternate" hreflang="x-default" href="{SITE}/{default}/{slug}/">'
    return links


class Cluster(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-facts-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def page(self, lang, slug, body, head="", langs=LANGS, default="en"):
        path = os.path.join(self.dir, lang, slug, "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f'<html lang="{lang}"><head><title>{slug} {lang}</title>'
                     f'{alternates(slug, langs, default)}{head}</head>'
                     f"<body><main><p>{body}</p></main></body></html>")

    def drift(self):
        pages, _ = core.load_pages(self.dir, SITE)
        return {i[1]: i[3] for i in facts.drift(pages)}


class TestFactDrift(Cluster):
    def test_a_price_and_a_percent_that_changed_in_translation(self):
        self.page("en", "fee", "The visa fee is $35 and the approval rate is 85% this year.")
        self.page("ar", "fee", "رسوم التأشيرة ٥٣ دولار ونسبة الموافقة ٨٥٪ هذا العام.")
        self.page("id", "fee", "Biaya visa adalah 35 dolar dan tingkat persetujuan 58% tahun ini.")
        self.page("de", "fee", "Die Gebühr beträgt 35 $ und die Quote 85 % in diesem Jahr.")
        got = self.drift()
        self.assertEqual(sorted(got), [f"{SITE}/ar/fee/", f"{SITE}/id/fee/"])
        self.assertIn("53", got[f"{SITE}/ar/fee/"])
        self.assertIn("$35", got[f"{SITE}/ar/fee/"])
        self.assertIn("58", got[f"{SITE}/id/fee/"])

    def test_a_local_currency_is_localisation_not_drift(self):
        """Арабская версия в дирхамах, английская в долларах — сравнивать нечего."""
        self.page("en", "fee", "The visa fee is $35 for adults.")
        self.page("ar", "fee", "رسوم التأشيرة ١٣٠ درهم للبالغين.")
        self.assertEqual(self.drift(), {})

    def test_a_shortened_translation_is_not_drift(self):
        """Перевод опустил одну цифру — это сокращение, не расхождение."""
        self.page("en", "fee", "The fee is $35, the express fee is $60.")
        self.page("id", "fee", "Biaya visa adalah 35 dolar.")
        self.assertEqual(self.drift(), {})

    def test_closed_translations_are_left_out(self):
        self.page("en", "fee", "The visa fee is $35 for adults.")
        self.page("ar", "fee", "رسوم التأشيرة ٥٣ دولار للبالغين.",
                  head='<meta name="robots" content="noindex">')
        self.assertEqual(self.drift(), {})

    def test_without_x_default_english_is_the_reference(self):
        self.page("en", "fee", "The visa fee is $35 for adults.", default="")
        self.page("de", "fee", "Die Gebühr beträgt 53 $ für Erwachsene.", default="")
        self.assertEqual(sorted(self.drift()), [f"{SITE}/de/fee/"])

    def test_currency_words_after_the_number(self):
        from indexgap import content
        for text, number in (("Biaya visa adalah 35 dolar", "35"),
                             ("Сбор 35 долларов за визу", "35"),
                             ("Цена 1 200 евро", "1200")):
            with self.subTest(text):
                self.assertIn(number, content._numbers_in(text, None))

    def test_the_finding_reaches_check(self):
        self.page("en", "fee", "The visa fee is $35 and the approval rate is 85% this year.")
        self.page("ar", "fee", "رسوم التأشيرة ٥٣ دولار ونسبة الموافقة ٨٥٪ هذا العام.")
        out = os.path.join(self.dir + "-r.json")
        self.addCleanup(lambda: [os.path.exists(p) and os.remove(p)
                                 for p in (out, out[:-5] + ".html")])
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", self.dir, "--site", SITE, "--out", out])
        with open(out, encoding="utf-8") as fh:
            codes = {i["code"] for i in json.load(fh)["issues"]}
        self.assertIn("fact-drift", codes)


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-hist-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    @staticmethod
    def run_data(in_sitemap):
        return {"site": SITE, "funnel": {"steps": [
            {"id": "generated", "name": "Сгенерировано", "count": 10},
            {"id": "in-sitemap", "name": "В sitemap", "count": in_sitemap}]}}

    def test_saved_in_order_and_latest_is_the_last(self):
        root = os.path.join(self.dir, "reports")
        t = datetime.datetime(2026, 11, 1, 10, 0, 0)
        history.save(root, self.run_data(8), now=t)
        history.save(root, self.run_data(9), now=t + datetime.timedelta(days=1))
        self.assertEqual(len(history.runs(root)), 2)
        self.assertEqual(history.latest(root)["funnel"]["steps"][1]["count"], 9)

    def test_two_runs_in_one_second_do_not_overwrite(self):
        root = os.path.join(self.dir, "reports")
        t = datetime.datetime(2026, 11, 1, 10, 0, 0)
        history.save(root, self.run_data(8), now=t)
        history.save(root, self.run_data(9), now=t)
        self.assertEqual(len(history.runs(root)), 2)

    def test_trend_page_has_every_step_and_date(self):
        root = os.path.join(self.dir, "reports")
        for day, count in ((1, 7), (2, 8), (3, 10)):
            history.save(root, self.run_data(count), now=datetime.datetime(2026, 11, day))
        path = history.render(root, SITE)
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("<svg", page)
        self.assertIn("В sitemap: 10", page)
        self.assertIn("2026-11-01", page)
        self.assertIn("2026-11-03", page)

    def test_an_empty_history_has_no_latest(self):
        self.assertIsNone(history.latest(os.path.join(self.dir, "none")))

    def test_doctor_compares_with_the_last_run_by_itself(self):
        site = os.path.join(self.dir, "site")
        for i in range(6):
            os.makedirs(os.path.join(site, "a", f"p{i}"))
            with open(os.path.join(site, "a", f"p{i}", "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f"<html><head><title>page {i} title</title></head><body><p>x</p></body></html>")
        urls = [f"{SITE}/a/p{i}/" for i in range(6)]

        def sitemap(listed):
            path = os.path.join(self.dir, "sm.xml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                         + "".join(f"<url><loc>{u}</loc></url>" for u in listed) + "</urlset>")
            return path

        reports = os.path.join(self.dir, "reports")
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            cli.main(["doctor", site, "--site", SITE, "--sitemap", sitemap(urls),
                      "--history", reports, "--out", os.path.join(self.dir, "r1.html")])
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            code = cli.main(["doctor", site, "--site", SITE, "--sitemap", sitemap(urls[:4]),
                             "--history", reports, "--out", os.path.join(self.dir, "r2.html")])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("С прошлого прогона", out.getvalue())
        self.assertIn("Выпали из sitemap (2)", out.getvalue())
        self.assertEqual(len(history.runs(reports)), 2)
        self.assertTrue(os.path.exists(os.path.join(reports, "trend.html")))


if __name__ == "__main__":
    unittest.main()
