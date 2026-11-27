# -*- coding: utf-8 -*-
"""
1.30 (facts): годы и даты против колонок строки (#22), цены, перепутанные
между позициями в переводе (#76), бессрочная серия рядом с прошедшим
событием (#222).
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import date

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import content, core, facts, freshness

SITE = "https://demo.example"
FILLER = " ".join("Newcomers usually compare several offices before they sign anything." for _ in range(6))
TODAY = date(2026, 11, 27)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-130-facts-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, html):
        folder = os.path.join(self.root, rel.strip("/"))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html)

    def pages(self):
        return core.load_pages(self.root, SITE)[0]


# ── #22: годы и даты ─────────────────────────────────────────────────────────

ROWS = [
    {"keyword": "alpha", "city": "Alpha", "founded": "1998", "opened": "March 2015",
     "deadline": "2026-12-31", "checked": "2026-11-18"},
    {"keyword": "beta", "city": "Beta", "founded": "2004", "opened": "June 2019",
     "deadline": "2027-01-15", "checked": "2026-11-18"},
    {"keyword": "gamma", "city": "Gamma", "founded": "1987", "opened": "May 2010",
     "deadline": "2027-02-28", "checked": "2026-11-18"},
]


def sentence(row):
    return (f"{row['city']} was founded in {row['founded']} and the office opened in "
            f"{row['opened']}. Apply by {row['deadline']}. Data checked on {row['checked']}.")


class Dates(Tmp):
    def site(self, bodies):
        for row in ROWS:
            body = bodies.get(row["keyword"], sentence(row))
            self.write(row["keyword"], f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                                       f'<title>Guide to {row["city"]}</title></head><body><main>'
                                       f'<h1>Guide to {row["city"]}</h1><p>{body}</p><p>{FILLER}</p>'
                                       '</main></body></html>')
        result = content.run(self.pages(), ROWS, "keyword", self.root)
        return {i[1].rstrip("/").rsplit("/", 1)[-1]: str(i[3]) for i in result["issues"]
                if i[2] in ("check-by-eye", "unsupported-number")}

    def test_wrong_year_and_dates_are_shown(self):
        found = self.site({"gamma": "Gamma was founded in 1978 and the office opened in May 2001. "
                                    "Apply by 2027-03-28. Data checked on 2026-11-18."})
        self.assertEqual(list(found), ["gamma"])
        for wrong in ("1978", "May 2001", "2027-03-28"):
            self.assertIn(wrong, found["gamma"])
        self.assertIn("1987", found["gamma"])

    def test_named_date_against_iso_column(self):
        # Верные даты другими словами на соседней странице — не находка.
        found = self.site({"gamma": "Gamma was founded in 1987 and the office opened in May 2010. "
                                    "The deadline is March 28th, 2027. Data checked on 2026-11-18.",
                           "beta": "Beta was founded in 2004. The office opened in June 2019. "
                                   "The deadline is January 15th, 2027."})
        self.assertEqual(list(found), ["gamma"])
        self.assertIn("March 28th, 2027", found["gamma"])

    def test_years_that_are_not_the_column_are_quiet(self):
        year = date.today().year
        body = ("Gamma was founded in 1978 and expanded in 1995, then moved in 2008. The office "
                "opened in May 2010 at 2000 Main Street. Applications open on 2026-12-01 and close "
                f"on 2027-02-28. Updated 2025. Applications for {year + 1} are open, since {year}. "
                "Copyright © 2024 Demo. The rules changed in 2019. Founded in 1987, the office "
                "served clients in 2023.")
        found = self.site({"gamma": body})
        self.assertEqual(list(found), ["gamma"])
        shown = found["gamma"].split(": ", 1)[1]
        self.assertTrue(shown.startswith("1978 "), shown)
        for quiet in ("1995", "2008", "2000", "2026-12-01", "2025", "2024", "2019", "2023"):
            self.assertNotIn(quiet, shown)

    def test_a_year_cell_in_a_money_column_is_not_a_year(self):
        self.assertEqual(content._dated_columns({"price": "2000", "founded": "1987",
                                                 "rent": "$1,999"}), {"founded": ("1987",)})


# ── #76: цены, перепутанные между позициями ──────────────────────────────────

def link(code, href):
    return f'<link rel="alternate" hreflang="{code}" href="{href}">'


class Swap(Tmp):
    def page(self, lang, body, slug="plans", langs=("en", "de")):
        alts = "".join(link(code, f"{SITE}/{code}/{slug}/") for code in langs)
        alts += link("x-default", f"{SITE}/en/{slug}/")
        self.write(f"{lang}/{slug}", f'<html lang="{lang}"><head><title>Plans {lang}</title>{alts}'
                                     f"</head><body><main><h1>Plans</h1>{body}</main></body></html>")

    def drift(self):
        return {i[1]: str(i[3]) for i in facts.drift(self.pages())}

    def test_swapped_prices_are_reported(self):
        self.page("en", "<p>Basic costs $29 and Pro costs $49.</p>")
        self.page("de", "<p>Basic kostet $49 und Pro kostet $29.</p>")
        # Перестановка фраз, метка после цены, пересчёт и повторенная метка — не находка.
        quiet = {"reorder": ("Pro kostet $49, und Basic kostet nur $29.", "de"),
                 "after": ("Für $29 bekommen Sie Basic und für $49 Pro.", "de"),
                 "convert": ("Basic cuesta $580 y Pro cuesta $980.", "es")}
        for slug, (body, lang) in quiet.items():
            self.page("en", "<p>Basic costs $29 and Pro costs $49.</p>", slug, ("en", lang))
            self.page(lang, f"<p>{body}</p>", slug, ("en", lang))
        self.page("en", "<p>Basic costs $29. Basic yearly costs $290. Pro costs $49.</p>", "twice")
        self.page("de", "<p>Basic kostet $49. Basic jährlich kostet $290. Pro kostet $29.</p>", "twice")
        found = self.drift()
        self.assertEqual(list(found), [f"{SITE}/de/plans/"])
        self.assertIn("Basic $49", found[f"{SITE}/de/plans/"])

    def test_swapped_prices_in_a_table(self):
        row = "<tr><td>{}</td><td>{}</td></tr>"
        self.page("en", "<table>" + row.format("Basic", "$29") + row.format("Pro", "$49") + "</table>")
        self.page("de", "<table>" + row.format("Basic", "$49") + row.format("Pro", "$29") + "</table>")
        self.assertEqual(list(self.drift()), [f"{SITE}/de/plans/"])


# ── #222: бессрочная серия и прошедшее событие ───────────────────────────────

def event_page(root, ld, meta=None):
    path = os.path.join(root, "e", "index.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f'<html><head><title>Events</title><script type="application/ld+json">'
                 f'{json.dumps(ld)}</script></head><body><main><h1>Events</h1><p>Text.</p>'
                 '</main></body></html>')
    page = core.load_page(path, root, SITE)
    if meta:
        page.meta = dict(page.meta or {}, **meta)
    return page


WEEKLY = {"@type": "Event", "name": "Weekly jam", "startDate": "2026-01-05",
          "eventSchedule": {"@type": "Schedule", "repeatFrequency": "P1W"}}
FESTIVAL = {"@type": "Event", "name": "Summer festival", "startDate": "2025-07-01",
            "endDate": "2025-07-03"}


class Series(Tmp):
    def check(self, ld, meta=None):
        page = event_page(self.root, ld, meta)
        return page, [(i[0], i[2]) for i in freshness.check([page], today=TODAY)["issues"]]

    def test_past_one_off_next_to_a_series_is_a_warning(self):
        page, issues = self.check({"@context": "https://schema.org", "@graph": [WEEKLY, FESTIVAL]})
        self.assertEqual(freshness.page_dates(page)["jsonld:endDate"], date(2025, 7, 3))
        self.assertEqual(issues, [("warning", "stale-event-part")])
        # Одна серия или серия рядом с будущим событием — тишина.
        page, issues = self.check(WEEKLY)
        self.assertEqual((freshness.page_dates(page), issues), ({}, []))
        future = dict(FESTIVAL, startDate="2027-07-01", endDate="2027-07-03")
        self.assertEqual(self.check({"@graph": [WEEKLY, future]})[1], [])

    def test_own_end_date_closes_the_series(self):
        ld = dict(WEEKLY, startDate="2024-01-05", endDate="2024-06-01")
        page, issues = self.check(ld)
        self.assertEqual(freshness.page_dates(page)["jsonld:endDate"], date(2024, 6, 1))
        self.assertEqual(issues, [("critical", "stale-event")])

    def test_frontmatter_date_still_counts(self):
        page, issues = self.check(WEEKLY, {"date": "2025-01-01"})
        self.assertIn("frontmatter:date", freshness.page_dates(page))
        self.assertEqual(issues, [("warning", "stale-event-part")])


if __name__ == "__main__":
    unittest.main()
