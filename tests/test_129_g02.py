# -*- coding: utf-8 -*-
"""
1.29 (g02): даты, время и единицы в сверке фактов; связь страницы со строкой.
"""

import csv
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, content, core
from indexgap.core import _parse_frontmatter
from indexgap.generate import slugify

SITE = "https://demo.example"
FILLER = " ".join("Newcomers usually compare several listings before they sign anything." for _ in range(6))


class Site:
    def __init__(self, case):
        self.root = tempfile.mkdtemp(prefix="indexgap-129-g02-")
        case.addCleanup(shutil.rmtree, self.root, True)

    def page(self, path, title, body, head=""):
        folder = os.path.join(self.root, path.strip("/"))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                     f'<title>{title}</title>{head}</head><body><main><h1>{title}</h1>'
                     f'<p>{body}</p><p>{FILLER}</p></main></body></html>')

    def run(self, rows, keyword="keyword"):
        pages, _ = core.load_pages(self.root, SITE)
        return content.run(pages, rows, keyword, self.root, fact_units=["minutes", "months"])


def by_code(result, code):
    return {i[1].rstrip("/").rsplit("/", 1)[-1]: str(i[3]) for i in result["issues"] if i[2] == code}


ROWS = [
    {"keyword": "alpha", "rent": "$1,450", "deposit": "3 months", "commute": "34 minutes"},
    {"keyword": "beta", "rent": "$1,600", "deposit": "2 months", "commute": "29 minutes"},
    {"keyword": "gamma", "rent": "$1,300", "deposit": "2 months", "commute": "27 minutes"},
    {"keyword": "delta", "rent": "$1,350", "deposit": "3 months", "commute": "41 minutes"},
]


def rows_with(column, values):
    return [dict(r, **{column: v}) for r, v in zip(ROWS, values)]


class DatesInCells(unittest.TestCase):
    def check(self, column, values, bodies):
        site = Site(self)
        for row, body in zip(ROWS, bodies):
            site.page(f"/{row['keyword']}/", f"Guide to {row['keyword']}", body)
        return site.run(rows_with(column, values))

    def test_month_name_dates_are_not_row_numbers(self):
        result = self.check("checked", ["18 Nov 2026", "Nov 18, 2026", "18 November 2026", "November 18, 2026"], [
            "Rent is $1,450 a month, deposit 18 months, commute 34 minutes.",
            "Rent is $18 a month, deposit 2 months, commute 29 minutes.",
            "Rent is $1,300 a month, deposit 2 months, commute 18 minutes.",
            "Rent is $1,350 a month, deposit 3 months, commute 41 minutes, or $2026 per year."])
        crit = by_code(result, "unsupported-number")
        self.assertEqual(set(crit), {"alpha", "beta", "gamma", "delta"})
        self.assertIn("18", crit["alpha"])
        self.assertIn("2026", crit["delta"])

    def test_clock_times_and_short_dates_are_not_counts(self):
        result = self.check("opens", ["8:30", "9:15", "10:45", "9:00-18:00"], [
            "Rent is $1,450 a month, deposit 3 months, commute 30 minutes.",
            "Rent is $1,600 a month, deposit 15 months, commute 29 minutes.",
            "Rent is $1,300 a month, deposit 2 months, commute 45 minutes.",
            "Rent is $1,350 a month, deposit 9 months, commute 41 minutes."])
        self.assertEqual(set(by_code(result, "unsupported-number")), {"alpha", "beta", "gamma", "delta"})
        result = self.check("checked", ["11/2026", "18/11/26", "2026-11", "11/18/26"], [
            "Rent is $1,450 a month, deposit 11 months, commute 34 minutes.",
            "Rent is $1,600 a month, deposit 2 months, commute 18 minutes.",
            "Rent is $1,300 a month, deposit 11 months, commute 27 minutes.",
            "Rent is $1,350 a month, deposit 3 months, commute 26 minutes."])
        self.assertEqual(set(by_code(result, "unsupported-number")), {"alpha", "beta", "gamma", "delta"})

    def test_correct_page_with_times_and_dates_stays_clean(self):
        result = self.check("hours", ["9:00-18:00", "10:00-19:00", "8:30-17:30", "9:00-18:00"], [
            "Rent is $1,450 a month and the office is open from 9:00 am to 6:00 pm.",
            "Rent is $1,600 a month and the office is open from 10 am to 7 pm.",
            "Rent is $1,300 a month and the office is open from 8:30 am to 5:30 pm.",
            "Rent is $1,350 a month, deposit 3 months, commute 41 minutes."])
        self.assertEqual(by_code(result, "unsupported-number"), {})
        self.assertEqual(by_code(result, "check-by-eye"), {})

    def test_ordinal_and_kana_dates_match_the_row(self):
        result = self.check("deadline", ["2026-12-31", "2027-01-15", "2027-02-28", "2027-03-10"], [
            "Rent is $1,450 a month. Applications close on December 31st.",
            "Rent is $1,600 a month. Applications close on January 15th, 2027.",
            "Rent is $1,300 a month. The 3rd deadline is February 28th.",
            "締切は2027年3月10日です。"])
        self.assertEqual(by_code(result, "check-by-eye"), {})


class Measures(unittest.TestCase):
    def test_seconds_nights_decades_are_measures(self):
        site = Site(self)
        bodies = ["Rent is $1,450 a month, deposit 3 months, the commute is 34 seconds.",
                  "Rent is $1,600 a month, deposit 2 nights, commute 29 minutes.",
                  "Rent is $1,300 a month, deposit 2 months, commute 27 minutes.",
                  "Rent is $1,350 a month, deposit 3 decades, commute 41 sec."]
        for row, body in zip(ROWS, bodies):
            site.page(f"/{row['keyword']}/", f"Guide to {row['keyword']}", body)
        eye = by_code(site.run(ROWS), "check-by-eye")
        self.assertIn("34", eye.get("alpha", ""))
        self.assertIn("2", eye.get("beta", ""))
        self.assertIn("41", eye.get("delta", ""))
        self.assertIn("3", eye.get("delta", ""))

    def test_hours_and_minutes_compound(self):
        site = Site(self)
        rows = [dict(ROWS[0], commute="90 minutes")] + ROWS[1:]
        for row in rows:
            site.page(f"/{row['keyword']}/", f"Guide to {row['keyword']}",
                      f"Rent is {row['rent']} a month and the commute takes {row['commute']}.")
        site.page("/alpha/", "Guide to alpha", "Rent is $1,450 a month; the commute takes 1 hour 30 minutes.")
        result = site.run(rows)
        self.assertEqual(by_code(result, "unsupported-number"), {})
        site.page("/alpha/", "Guide to alpha", "Rent is $1,450 a month; the commute takes 1 hour 20 minutes.")
        self.assertIn("alpha", by_code(site.run(rows), "unsupported-number"))


class Binding(unittest.TestCase):
    def build(self, keys, folder="rent", head=None):
        site = Site(self)
        for row in ROWS:
            if row["keyword"] in keys:
                site.page(f"/{folder}/{keys[row['keyword']]}/", f"Renting in {row['keyword'].title()}",
                          f"A flat costs about {row['rent']} a month.", head(row) if head else "")
        return site

    def test_stamped_meta_keyword_does_not_override_slug(self):
        site = Site(self)
        for row in ROWS:
            site.page(f"/rent/{row['keyword']}/", f"Renting in {row['keyword'].title()}",
                      "A flat costs about $1,450 a month.", '<meta name="keyword" content="alpha">')
        result = site.run(ROWS)
        self.assertEqual(set(by_code(result, "unsupported-number")), {"beta", "gamma", "delta"})

    def test_title_mention_does_not_bind_a_page_without_row(self):
        site = Site(self)
        for row in ROWS[1:]:
            site.page(f"/rent/{row['keyword']}/", f"Renting in {row['keyword'].title()}",
                      f"A flat costs about {row['rent']} a month.")
        site.page("/rent/omega/", "Renting in Omega near Alpha", "A flat costs about $990 a month.")
        result = site.run(ROWS)
        self.assertEqual(result["rows_without_page"], ["alpha"])
        self.assertIn(SITE + "/rent/omega/", result["unmatched"])
        self.assertEqual(by_code(result, "unsupported-number"), {})

    def test_same_slug_in_another_section_is_not_bound(self):
        site = Site(self)
        for row in ROWS:
            site.page(f"/rent/{row['keyword']}/", f"Renting in {row['keyword'].title()}",
                      f"A flat costs about {row['rent']} a month.")
        site.page("/buy/alpha/", "Buying in Alpha", "A flat costs about $410,000.")
        result = site.run(ROWS)
        self.assertIn(SITE + "/buy/alpha/", result["unmatched"])
        self.assertEqual(by_code(result, "unsupported-number"), {})

    def test_duplicate_url_column_is_ambiguous(self):
        site = Site(self)
        rows = [dict(r, url=f"/rent/{r['keyword']}/") for r in ROWS]
        rows.append(dict(ROWS[0], keyword="alpha centre", rent="$2,900", url="/rent/alpha/"))
        for row in ROWS:
            site.page(f"/rent/{row['keyword']}/", f"Flats {row['keyword']}",
                      f"A flat costs about {row['rent']} a month.")
        result = site.run(rows)
        self.assertEqual(result["ambiguous"], [SITE + "/rent/alpha/"])
        self.assertEqual(by_code(result, "unsupported-number"), {})

    def test_unicode_and_capital_folders_bind(self):
        site = Site(self)
        rows = [dict(ROWS[0], keyword="köln"), dict(ROWS[1], keyword="Berlin"),
                dict(ROWS[2], keyword="аренда берлин"), dict(ROWS[3], keyword="łódź")]
        for row, folder in zip(rows, ["köln", "Berlin", "аренда-берлин", "lodz"]):
            site.page(f"/rent/{folder}/", "Flat prices", "A flat costs about $7 a month.")
        result = site.run(rows)
        self.assertEqual(result["matched_rows"], 4)
        self.assertEqual(len(by_code(result, "unsupported-number")), 4)

    def test_url_column_percent_encoded(self):
        site = Site(self)
        rows = [dict(r, url=f"{SITE}/rent/{r['keyword']}/") for r in ROWS]
        rows[0] = dict(rows[0], keyword="koeln", url=SITE + "/rent/k%C3%B6ln/")
        site.page("/rent/köln/", "Flat prices", "A flat costs about $7 a month.")
        result = site.run(rows)
        self.assertEqual(result["matched_rows"], 1)

    def test_slugify_latin_letters(self):
        for word, slug in [("łódź", "lodz"), ("wrocław", "wroclaw"), ("tromsø", "tromso"),
                           ("straße", "strasse"), ("æble", "aeble")]:
            self.assertEqual(slugify(word), slug)

    def test_frontmatter_single_item_list(self):
        self.assertEqual(_parse_frontmatter("keyword: [munich]"), {"keyword": "munich"})
        self.assertEqual(_parse_frontmatter("keyword:\n  - leipzig"), {"keyword": "leipzig"})
        self.assertEqual(_parse_frontmatter("tags:\n  - a\n  - b"), {})

    def test_rows_without_keyword_are_numbered(self):
        site = Site(self)
        site.page("/rent/alpha/", "Renting in Alpha", "A flat costs about $1,450 a month.")
        result = site.run([ROWS[0], dict(ROWS[1], keyword="")])
        self.assertEqual(result["rows_without_page"], ["#2"])


class HtmlCoverage(unittest.TestCase):
    def test_html_report_shows_coverage_and_rows_without_page(self):
        site = Site(self)
        for row in ROWS[:3]:
            site.page(f"/rent/{row['keyword']}/", f"Renting in {row['keyword'].title()}",
                      f"A flat costs about {row['rent']} a month.")
        data = os.path.join(site.root, "data.csv")
        with open(data, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(ROWS[0]))
            writer.writeheader()
            writer.writerows(ROWS)
        out = os.path.join(tempfile.mkdtemp(prefix="indexgap-129-out-"), "r.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", site.root, "--site", SITE, "--dataset", data, "--no-aeo", "--out", out])
        with open(out[:-5] + ".html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("Сверено с датасетом: 3 из 3", html)
        self.assertIn("delta", html)


if __name__ == "__main__":
    unittest.main()
