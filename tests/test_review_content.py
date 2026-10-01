# -*- coding: utf-8 -*-
"""
Проверка чисел и машинной читаемости: находки ревью десяти агентов.

Проверка выдуманных чисел — то, ради чего пакет не пишет текст сам. Она
ошибалась в обе стороны. Цена `1,299.99 USD`, дословно стоящая в данных,
резалась пополам и объявлялась выдумкой «299.99 USD». Диапазон `3-5 days`
из той же строки не давал ни одного числа. А цена `$95` при `$60` в данных
не замечалась вовсе: валюту искали только после числа.
"""

import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, content

SITE = "https://example.com"


class Page:
    def __init__(self, text, url=SITE + "/a/"):
        self.url, self.text, self.meta, self.path = url, text, {}, "a.html"


def findings(text, row, units=("USD", "EUR", "AED", "days", "руб")):
    page = Page(text)
    issues = content.check_facts([page], {page.url: row}, [row], fact_units=list(units))
    return {code: message for _, _, code, message in issues}


class TestNumbersAreReadWhole(unittest.TestCase):
    def test_grouped_number_with_decimals_matches_row(self):
        for value in ("1,299.99 USD", "1,250,000 AED", "1.299,99 EUR", "12 500 руб"):
            found = findings(f"The package costs {value} in total.", {"k": "a", "price": value})
            self.assertNotIn("unsupported-number", found, (value, found))

    def test_a_wrong_grouped_number_is_still_reported_whole(self):
        found = findings("The package costs 1,399.99 USD.", {"k": "a", "price": "1,299.99 USD"})
        self.assertIn("1399.99", found.get("unsupported-number", ""), found)

    def test_range_in_row_supports_both_ends(self):
        for text in ("Processing takes 3-5 days.", "Processing takes 3–5 days.",
                     "Processing takes 3 to 5 days."):
            found = findings(text, {"k": "a", "processing": "3-5 days"})
            self.assertNotIn("unsupported-number", found, (text, found))

    def test_a_date_in_the_row_gives_its_numbers(self):
        found = findings("Open for 15 days.", {"k": "a", "opens": "2026-03-15"})
        self.assertNotIn("unsupported-number", found, found)

    def test_sku_still_does_not_pardon_a_fake_number(self):
        found = findings("Lasts 90 days.", {"k": "a", "sku": "A-90-15"})
        self.assertIn("unsupported-number", found, found)


class TestPrefixCurrency(unittest.TestCase):
    def test_prefix_currency_invention_is_reported(self):
        for text in ("The application fee is $95.", "It costs €1,950 today.",
                     "The fee is USD 95.", "Rent is $1,900 per month."):
            found = findings(text, {"k": "a", "fee": "$60"}, units=())
            self.assertIn("unsupported-number", found, (text, found))

    def test_prefix_currency_from_the_row_is_supported(self):
        for text, fee in (("The application fee is $60.", "$60"),
                          ("Rent is $1,900 per month.", "$1,900"),
                          ("The fee is USD 60.", "60 USD")):
            found = findings(text, {"k": "a", "fee": fee}, units=())
            self.assertNotIn("unsupported-number", found, (text, found))

    def test_a_bare_year_is_still_not_a_fact(self):
        found = findings("Updated in 2026 for travellers.", {"k": "a", "fee": "$60"}, units=())
        self.assertEqual(found, {})


class TestAiCrawlerLevel(unittest.TestCase):
    """Важность находки — свойство бота, а не языка, на котором её печатают."""

    ROBOTS = {"found": True, "sitemaps": ["x"], "rules": {
        "*": {"disallow": [], "allow": ["/"]},
        "oai-searchbot": {"disallow": ["/"], "allow": []},
        "gptbot": {"disallow": ["/"], "allow": []}}}

    def levels(self):
        return sorted((i[0], i[3].split()[0].rstrip(":")) for i in aeo.check_robots(self.ROBOTS)
                      if i[2] == "ai-crawler-blocked")

    def test_ai_crawler_level_same_in_en_and_ru(self):
        from indexgap import i18n
        russian = self.levels()
        i18n.set_lang("en")
        try:
            english = self.levels()
        finally:
            i18n.set_lang("ru")
        self.assertEqual([lvl for lvl, _ in russian], [lvl for lvl, _ in english])
        self.assertIn("critical", [lvl for lvl, _ in english])
        self.assertIn("info", [lvl for lvl, _ in english])


class TestEventsProfileAndDates(unittest.TestCase):
    """Дата публикации — не дата события."""

    def page(self, **kw):
        import json
        from datetime import date
        page = Page("текст")
        page.meta = kw.get("meta", {})
        page.jsonld = [json.dumps(j) for j in kw.get("jsonld", [])]
        page.raw = kw.get("raw", "")
        page.robots, page.canonical = "", ""
        from indexgap import freshness
        return freshness.page_dates(page)

    def test_time_tag_on_non_event_not_stale(self):
        raw = 'Last reviewed <time datetime="2026-03-02">2 March</time>'
        self.assertEqual(self.page(raw=raw), {})
        self.assertEqual(self.page(raw=raw, jsonld=[
            {"@type": "NewsArticle", "datePublished": "2026-03-02"}]), {})

    def test_time_tag_on_an_event_still_counts(self):
        found = self.page(raw='<time datetime="2026-03-02">', jsonld=[
            {"@type": "MusicEvent", "name": "Концерт"}])
        self.assertEqual(sorted(found), ["time"])

    def test_recurring_event_not_stale(self):
        from datetime import date
        found = self.page(jsonld=[{"@type": "Event", "startDate": "2026-01-05",
                                   "eventSchedule": {"@type": "Schedule", "repeatFrequency": "P1W",
                                                     "endDate": "2027-12-27"}}])
        self.assertEqual(max(found.values()), date(2027, 12, 27))
        open_ended = self.page(jsonld=[{"@type": "Event", "startDate": "2026-01-05",
                                        "eventSchedule": {"@type": "Schedule",
                                                          "repeatFrequency": "P1W"}}])
        self.assertEqual(open_ended, {})

    def test_a_blog_with_publish_dates_is_not_an_events_site(self):
        import os, shutil, tempfile
        from indexgap import install
        root = tempfile.mkdtemp(prefix="indexgap-blog-")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "content", "posts"))
        for i in range(6):
            with open(os.path.join(root, "content", "posts", f"p{i}.md"), "w", encoding="utf-8") as fh:
                fh.write(f"---\ntitle: Пост {i}\ndate: 2026-0{i + 1}-10\n---\n\n" + "слово " * 200)
        profile, _ = install.detect_profile(root, "content", "")
        self.assertNotEqual(profile, "events")

    def test_event_fields_still_select_the_events_profile(self):
        import os, shutil, tempfile
        from indexgap import install
        root = tempfile.mkdtemp(prefix="indexgap-ev-")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "content"))
        for i in range(6):
            with open(os.path.join(root, "content", f"e{i}.md"), "w", encoding="utf-8") as fh:
                fh.write(f"---\ntitle: Концерт {i}\nstart_date: 2026-0{i + 1}-10\n---\n\n" + "слово " * 200)
        self.assertEqual(install.detect_profile(root, "content", "")[0], "events")


if __name__ == "__main__":
    unittest.main()
