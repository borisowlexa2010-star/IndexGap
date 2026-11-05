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


class TestPricesInEveryScript(unittest.TestCase):
    """1.23: цена и процент находятся в любой письменности и с местным знаком."""

    def kinds(self, text):
        from indexgap import content
        return {n: facts._kind(u) for n, u in content._numbers_in(text, None).items()}

    def test_currency_words_in_more_scripts(self):
        for text, kind in (("هزینه ۳۵ دلار", "USD"), ("費用は35ドルです", "USD"),
                           ("费用为35美元", "USD"), ("수수료는 35달러", "USD"),
                           ("ค่าธรรมเนียม 35 ดอลลาร์", "USD"), ("Збір 35 доларів", "USD"),
                           ("فیس 35 ڈالر", "USD"), ("ফি 35 টাকা", "BDT"),
                           ("Preis 35 ユーロ", "EUR"), ("35 ringgit", "MYR")):
            with self.subTest(text):
                self.assertEqual(self.kinds(text), {"35": kind})

    def test_local_dollar_signs_are_their_own_currency(self):
        for text, number, kind in (("S$35", "35", "SGD"), ("HK$200", "200", "HKD"),
                                   ("R$ 90", "90", "BRL"), ("US$ 35", "35", "USD"),
                                   ("RM 35", "35", "MYR"), ("Rp 350.000", "350000", "IDR"),
                                   ("Rs. 500", "500", "INR")):
            with self.subTest(text):
                self.assertEqual(self.kinds(text), {number: kind})
        self.assertEqual(self.kinds("$35 and S$47"), {"35": "USD", "47": "SGD"})

    def test_percent_written_as_a_word(self):
        for text in ("85 per cent", "85 процентов", "۸۵ درصد", "85 Prozent", "85 por ciento"):
            with self.subTest(text):
                self.assertEqual(self.kinds(text), {"85": "%"})

    def test_a_list_shares_the_unit_written_after_its_last_number(self):
        self.assertEqual(self.kinds("چهار خدمت ۲۹، ۴۹، ۱۴۹ و ۲۴۹ دلار آمریکا"),
                         {"29": "USD", "49": "USD", "149": "USD", "249": "USD"})
        self.assertEqual(self.kinds("plans at 29, 49 and 149 dollars"),
                         {"29": "USD", "49": "USD", "149": "USD"})
        self.assertEqual(self.kinds("1, 2 und 3 Prozent"), {"1": "%", "2": "%", "3": "%"})

    def test_a_year_or_a_lone_comma_is_not_a_list(self):
        self.assertEqual(self.kinds("Since 2019, 35 dollars"), {"35": "USD"})
        self.assertEqual(self.kinds("In 2026, 15% of visas"), {"15": "%"})
        self.assertEqual(self.kinds("between 2019 and 2026, 40%"), {"40": "%"})

    def test_ordinary_words_are_not_currencies(self):
        self.assertEqual(self.kinds("we won 3 awards"), {})
        self.assertEqual(self.kinds("Version 2.5 percentile"), {})

    def test_local_signs_are_shown_as_written(self):
        from indexgap import content
        self.assertEqual(content._shown("30", "S$"), "S$30")
        self.assertEqual(content._shown("35", "RM"), "RM 35")


class TestDriftInEveryScript(Cluster):
    def test_a_persian_price_that_changed(self):
        self.page("en", "fee", "The visa fee is $35 for adults.")
        self.page("ar", "fee", "هزینه ویزا ۵۳ دلار برای بزرگسالان.")
        self.assertEqual(sorted(self.drift()), [f"{SITE}/ar/fee/"])

    def test_a_percent_word_that_changed(self):
        self.page("en", "fee", "The approval rate is 85% this year.")
        self.page("de", "fee", "Die Quote liegt bei 58 Prozent in diesem Jahr.")
        self.assertEqual(sorted(self.drift()), [f"{SITE}/de/fee/"])

    def test_the_same_list_written_with_one_currency_word(self):
        self.page("en", "fee", "Plans cost $29, $49 and $149.")
        self.page("ar", "fee", "الخطط بسعر ۲۹، ۴۹ و ۱۴۹ دلار.")
        self.assertEqual(self.drift(), {})

    def test_prices_converted_under_the_same_sign_are_localisation(self):
        """«$700» в песо при «$35» в оригинале — пересчёт, а не расхождение."""
        self.page("en", "fee", "The fee is $35 and the express fee is $60.")
        self.page("de", "fee", "Die Gebühr beträgt $700, express $1200.")
        self.assertEqual(self.drift(), {})

    def test_a_local_dollar_is_another_currency(self):
        self.page("en", "fee", "The fee is $35 for adults.")
        self.page("id", "fee", "Biaya S$47 untuk dewasa.")
        self.assertEqual(self.drift(), {})

    def test_a_longer_translation_is_not_drift(self):
        """Пример расчёта, которого нет в оригинале, — другой текст, не другая цифра."""
        self.page("en", "fee", "The official fee is S$30.")
        self.page("id", "fee", "Hotel S$600, makan S$250, cadangan S$150, total S$1,000.")
        self.assertEqual(self.drift(), {})


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
