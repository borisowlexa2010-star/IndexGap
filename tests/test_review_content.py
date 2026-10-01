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


class Loaded(unittest.TestCase):
    def load(self, html, name="index.html"):
        import os, shutil, tempfile
        from indexgap import core
        root = tempfile.mkdtemp(prefix="indexgap-content-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
            fh.write(html)
        return core.load_pages(root, SITE)[0][0]


SCRIPTS = '<script src="/ga.js"></script><script src="/gtm.js"></script><script src="/app.js"></script>'


class TestShell(Loaded):
    def shell(self, html):
        from indexgap import checks
        return checks.is_shell(self.load(html))

    def test_short_static_page_without_p_is_not_shell(self):
        """Страница контактов: адрес и список, тридцать слов, ни одного <p>,
        три скрипта аналитики. Текст в исходнике есть — это не оболочка."""
        self.assertFalse(self.shell(
            f"<html><head><title>Contact us</title>{SCRIPTS}</head><body><h1>Contact</h1>"
            "<address>Example GmbH, Hauptstrasse 12, 10115 Berlin, Germany</address>"
            "<ul><li>Phone: 030 123 456 78</li><li>Email: hello at example dot com</li>"
            "<li>Open Monday to Friday from nine to five</li></ul>"
            "<div>We answer every message within one working day</div></body></html>"))

    def test_vite_single_script_shell_detected(self):
        self.assertTrue(self.shell(
            '<!doctype html><html><head><title>App</title></head><body><div id="root"></div>'
            '<script type="module" src="/assets/index-abc123.js"></script></body></html>'))

    def test_cjk_page_not_shell(self):
        self.assertFalse(self.shell(
            f"<html><head><title>签证</title>{SCRIPTS}</head><body><main><p>"
            + "新加坡签证申请需要护照照片和填写完整的表格" * 12 + "</p></main></body></html>"))

    def test_an_empty_page_without_scripts_is_not_a_shell(self):
        self.assertFalse(self.shell("<html><head><title>Empty</title></head><body></body></html>"))


class TestFaqMarkup(Loaded):
    def faq(self, visible, in_markup, outside_article=False):
        import json
        block = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": in_markup,
             "acceptedAnswer": {"@type": "Answer", "text": "About 1,450."}}]})
        body = f"<section><h2>{visible}</h2><p>About 1,450.</p></section>"
        main = (f"<article><h1>Rent</h1><p>{'word ' * 60}</p></article>{body}" if outside_article
                else f"<main><h1>Rent</h1><p>{'word ' * 60}</p>{body}</main>")
        page = self.load(f'<html><head><title>Rent guide</title><script type="application/ld+json">'
                         f"{block}</script></head><body>{main}</body></html>")
        return [i[2] for i in aeo.check_jsonld(page)]

    def test_faq_visible_despite_typographic_quotes(self):
        for visible, markup in (("What’s the average rent in Berlin?", "What's the average rent in Berlin?"),
                                ("What is “cold rent” – and why?", 'What is "cold rent" - and why?'),
                                ("What  is the deposit?", "What is the deposit?"),
                                ("Rent &amp; deposit: what to expect?", "Rent &amp; deposit: what to expect?")):
            self.assertEqual(self.faq(visible, markup), [], (visible, markup))

    def test_faq_section_outside_article_is_still_visible(self):
        self.assertEqual(self.faq("What is the deposit?", "What is the deposit?",
                                  outside_article=True), [])

    def test_an_invisible_question_is_still_reported(self):
        self.assertEqual(self.faq("What is the deposit?", "How do I get a visa?"),
                         ["jsonld-faq-invisible"])


class TestRowMatching(unittest.TestCase):
    def test_row_claimed_by_slug_not_fuzzy_matched_to_hub(self):
        """Строка «austin villa» принадлежит странице `/austin-villa/`. Хаб
        `/austin/` и статья блога с теми же словами в заголовке — другие
        страницы, и сверять их числа с этой строкой нельзя."""
        rows = [{"keyword": "austin villa", "price": "500000 AED"}]

        def page(path, title):
            p = Page("text", url=SITE + path)
            p.title, p.headings, p.path = title, [], path.strip("/") + "/index.html"
            return p
        pages = [page("/austin-villa/", "Austin villa for sale"),
                 page("/austin/", "Austin: villa and apartment listings"),
                 page("/blog/why-austin-villa-prices-rose/", "Why Austin villa prices rose")]
        matched = content.match_rows(pages, rows, "keyword", "")["matched"]
        self.assertEqual(sorted(matched), [SITE + "/austin-villa/"])


class TestPreamble(unittest.TestCase):
    def codes(self, first):
        page = Page("text")
        page.paragraphs = [first + " and then the paragraph goes on long enough to count."]
        return [i[2] for i in aeo.check_answer(page)]

    def test_english_wind_ups_are_caught(self):
        for first in ("Let’s dive into renting in Berlin", "In today’s market rents are high",
                      "Welcome to our guide to renting", "In this guide we explain renting"):
            self.assertEqual(self.codes(first), ["answer-preamble"], first)

    def test_a_real_opening_is_left_alone(self):
        for first in ("In this post-pandemic market a one-bedroom flat costs about 1,450",
                      "Прежде чем подавать документы, проверьте срок действия паспорта",
                      "In 2026, a one-bedroom flat in Berlin costs about 1,450 a month"):
            self.assertEqual(self.codes(first), [], first)


class TestRobotsAll(unittest.TestCase):
    def codes(self, rules):
        return [(i[0], i[2]) for i in aeo.check_robots(
            {"found": True, "sitemaps": ["x"], "rules": rules}) if i[2] == "robots-blocks-all"]

    def test_a_site_open_to_google_is_not_closed_to_everyone(self):
        found = self.codes({"*": {"disallow": ["/"], "allow": []},
                            "googlebot": {"disallow": [], "allow": ["/"]}})
        self.assertEqual([level for level, _ in found], ["warning"])

    def test_allow_of_the_home_page_only_does_not_open_the_site(self):
        self.assertEqual(self.codes({"*": {"disallow": ["/"], "allow": ["/$"]}}),
                         [("critical", "robots-blocks-all")])


class TestProvenance(Loaded):
    def test_a_publisher_is_an_organisation(self):
        import json
        block = json.dumps({"@type": "WebPage", "dateModified": "2026-09-01",
                            "publisher": {"@type": "Organization", "name": "Example"}})
        page = self.load('<html><head><title>T</title><script type="application/ld+json">'
                         f"{block}</script></head><body><main><p>text</p></main></body></html>")
        self.assertEqual(aeo.check_provenance(page), [])


if __name__ == "__main__":
    unittest.main()
