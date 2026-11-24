# -*- coding: utf-8 -*-
"""
1.27: машинная читаемость — что нашли независимые проверяющие.

* цена `"inf"` или `1e400` в JSON-LD роняла проверку всего сайта;
* `NaN` и `Infinity` — не JSON, а блок с ними считался валидным;
* «19» из даты и «99» из другой цены засчитывались за 19.99, «$1,600» — за 16;
* FAQ сверялся по первым 40 символам, вложенный в WebPage — не сверялся вовсе;
* `@context` без `@type` гасил находку о забытом типе;
* «By law, …» и «Written permission …» выбрасывались как подпись автора;
* `Disallow: /` с `Allow: /rent/` для OAI-SearchBot объявлялся полным запретом;
* пустой автор, дата `null`, `<time>` в комментарии и часы работы считались
  датой и автором, а микроданные на обычных элементах — нет;
* «Who we are», «What we offer» считались вопросами.
"""

import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, core

SITE = "https://demo.example"
TEXT = ("Flats in Springfield rent for about the same as last year, and most leases run "
        "for twelve months with a deposit of three monthly rents. ") * 3


def html(body="", head="", jsonld=None, raw_ld=None):
    ld = ""
    if jsonld is not None:
        ld = f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
    if raw_ld is not None:
        ld = f'<script type="application/ld+json">{raw_ld}</script>'
    return (f"<!doctype html><html lang=\"en\"><head><title>Rent in Springfield</title>"
            f"{head}{ld}</head><body><main><h1>Rent in Springfield</h1>{body}"
            f"<p>{TEXT}</p></main></body></html>")


class Site(unittest.TestCase):
    def page(self, text):
        root = tempfile.mkdtemp(prefix="indexgap-127-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return core.load_pages(root, SITE)[0][0]

    def codes(self, text):
        page = self.page(text)
        return {i[2] for i in aeo.check_jsonld(page) + aeo.check_provenance(page)
                + aeo.check_answer(page) + aeo.check_extractable(page)}


def offer(price):
    return {"@context": "https://schema.org", "@type": "Product", "name": "Flat",
            "offers": {"@type": "Offer", "price": price, "priceCurrency": "USD"}}


class Numbers(Site):
    def test_infinite_price_does_not_crash(self):
        for token in ('"inf"', '"Infinity"', '"1e400"', "1e400"):
            with self.subTest(token=token):
                ld = json.dumps(offer("X")).replace('"X"', token)
                codes = self.codes(html("<p>Monthly rent: $1,600.</p>", raw_ld=ld))
                self.assertNotIn("jsonld-mismatch", codes)

    def test_nan_and_infinity_are_not_json(self):
        for const in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(const=const):
                ld = '{"@context":"https://schema.org","@type":"Product","offers":{"price":%s}}' % const
                self.assertIn("jsonld-broken", self.codes(html(raw_ld=ld)))

    def test_parts_of_a_price_far_apart_are_not_the_price(self):
        cases = [("19.99", "<p>Now $24.99 per night. Updated 19 March 2026.</p>"),
                 ("4.99", "<p>From $9.99 for 4 rooms.</p>"),
                 ("16", "<p>Monthly rent: $1,600.</p>")]
        for price, body in cases:
            with self.subTest(price=price):
                self.assertIn("jsonld-mismatch", self.codes(html(body, jsonld=offer(price))))

    def test_rating_parts_far_apart(self):
        ld = {"@context": "https://schema.org", "@type": "Product", "name": "Flat",
              "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.9",
                                  "reviewCount": "90"}}
        body = "<p>Rated 4.2 out of 5 from 90 reviews.</p>"
        self.assertIn("jsonld-mismatch", self.codes(html(body, jsonld=ld)))

    def test_split_prices_still_match(self):
        cases = [("16.99", "<p>Only $16<sup>99</sup> today</p>"),
                 ("16.99", "<p>Only <span>$16</span><span>.99</span> today</p>"),
                 ("16", "<p>Only $16<sup>00</sup> today</p>"),
                 ("1600", "<p>Monthly rent: $1,600.</p>")]
        for price, body in cases:
            with self.subTest(body=body):
                self.assertNotIn("jsonld-mismatch", self.codes(html(body, jsonld=offer(price))))


class Faq(Site):
    def faq(self, question, wrap=None):
        faq = {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": question,
             "acceptedAnswer": {"@type": "Answer", "text": "About $1,600."}}]}
        if wrap:
            faq = {"@context": "https://schema.org", "@type": "WebPage", "mainEntity": faq}
        else:
            faq["@context"] = "https://schema.org"
        return faq

    VISIBLE = "<h2>What is the average rent for a two-bedroom flat in Springfield?</h2>"

    def test_a_question_that_differs_in_the_tail(self):
        ld = self.faq("What is the average rent for a two-bedroom flat in Shelbyville?")
        self.assertIn("jsonld-faq-invisible", self.codes(html(self.VISIBLE, jsonld=ld)))

    def test_the_same_question_passes(self):
        for question in ("What is the average rent for a two-bedroom flat in Springfield?",
                         "What is the average rent for a two-bedroom flat in Springfield"):
            with self.subTest(question=question):
                ld = self.faq(question)
                self.assertNotIn("jsonld-faq-invisible",
                                 self.codes(html(self.VISIBLE, jsonld=ld)))

    def test_faq_nested_in_a_web_page(self):
        ld = self.faq("How do I get a residence permit elsewhere?", wrap=True)
        self.assertIn("jsonld-faq-invisible", self.codes(html(self.VISIBLE, jsonld=ld)))
        ld = self.faq("What is the average rent for a two-bedroom flat in Springfield?",
                      wrap=True)
        self.assertNotIn("jsonld-faq-invisible", self.codes(html(self.VISIBLE, jsonld=ld)))


class NoType(Site):
    def test_context_without_type(self):
        ld = {"@context": "https://schema.org", "name": "Flat", "offers": {"price": "1600"}}
        self.assertIn("jsonld-no-type", self.codes(html("<p>$1,600</p>", jsonld=ld)))

    def test_graph_wrapper_is_not_flagged(self):
        ld = {"@context": "https://schema.org",
              "@graph": [{"@type": "WebPage", "name": "Rent"}]}
        self.assertNotIn("jsonld-no-type", self.codes(html(jsonld=ld)))


class Datelines(unittest.TestCase):
    def test_sentence_openings_are_not_datelines(self):
        for text in ("By law, a deposit is capped at three net monthly rents for any flat.",
                     "By 2026, rents will rise in most cities.",
                     "Written permission from the landlord is required for subletting.",
                     "Updated: in this article we will explore everything about rent."):
            with self.subTest(text=text):
                self.assertFalse(aeo._is_dateline(text))

    def test_real_datelines(self):
        for text in ("Updated 19 March 2026", "By Jane Doe · 5 min read",
                     "Last updated: March 3, 2026", "Published on 12 March",
                     "Обновлено 12 марта 2026", "Автор: Иван Петров"):
            with self.subTest(text=text):
                self.assertTrue(aeo._is_dateline(text))


class Answers(Site):
    def test_by_law_is_the_answer(self):
        body = ("<p>By law, a deposit in Springfield is capped at three net monthly rents "
                "for any flat.</p><p>See the table of costs below.</p>")
        page = self.page(html(body))
        page.paragraphs = page.paragraphs[:2]
        self.assertEqual(aeo.check_answer(page), [])

    def test_labelled_preamble(self):
        body = "<p>Updated: in this article we will explore everything about renting here.</p>"
        page = self.page(html(body))
        self.assertIn("answer-preamble", {i[2] for i in aeo.check_answer(page)})


class Robots(unittest.TestCase):
    def robots(self, text):
        root = tempfile.mkdtemp(prefix="indexgap-127-robots-")
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "robots.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return aeo.read_robots(path)

    def pages(self, *paths):
        from types import SimpleNamespace
        return [SimpleNamespace(url=SITE + p, robots="", raw="", canonical="", status=200,
                                noindex=False, meta={}) for p in paths]

    def crawler(self, robots, pages):
        return [i for i in aeo.check_robots(robots) + aeo.check_blocked_pages(pages, robots)
                if i[2] == "ai-crawler-blocked"]

    def test_allow_rules_that_open_every_page(self):
        robots = self.robots("User-agent: *\nAllow: /\n\nUser-agent: OAI-SearchBot\n"
                             "Disallow: /\nAllow: /rent/\nAllow: /about/\nAllow: /$\n")
        self.assertEqual(self.crawler(robots, self.pages("/", "/about/", "/rent/a/")), [])

    def test_full_block_is_still_critical(self):
        robots = self.robots("User-agent: *\nAllow: /\n\nUser-agent: OAI-SearchBot\nDisallow: /\n")
        found = self.crawler(robots, self.pages("/", "/rent/a/"))
        self.assertEqual([i[0] for i in found], ["critical"])

    def test_allow_for_one_section_leaves_the_rest_blocked(self):
        robots = self.robots("User-agent: *\nAllow: /\n\nUser-agent: OAI-SearchBot\n"
                             "Disallow: /\nAllow: /about/\n")
        found = self.crawler(robots, self.pages("/", "/rent/a/", "/rent/b/", "/about/"))
        self.assertEqual([i[0] for i in found], ["critical"])


class Provenance(Site):
    def provenance(self, text):
        return {i[2] for i in aeo.check_provenance(self.page(text))}

    def test_empty_values_are_not_provenance(self):
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": "Rent",
              "author": "", "dateModified": "", "datePublished": None}
        self.assertEqual(self.provenance(html(jsonld=ld)), {"no-date", "no-author"})

    def test_opening_hours_and_commented_time_are_not_dates(self):
        for body in ('<p>Open from <time datetime="09:00">9 am</time></p>',
                     '<!-- <time datetime="2019-01-01">1 Jan</time> -->'):
            with self.subTest(body=body):
                self.assertIn("no-date", self.provenance(html(body)))

    def test_a_real_time_element_is_a_date(self):
        body = '<p>Updated <time datetime="2026-03-01">1 March</time></p>'
        self.assertNotIn("no-date", self.provenance(html(body)))

    def test_inline_microdata_and_rdfa(self):
        microdata = ('<div itemscope itemtype="https://schema.org/Article">'
                     '<span itemprop="author" itemscope itemtype="https://schema.org/Person">'
                     '<span itemprop="name">Jane Doe</span></span>'
                     '<time itemprop="datePublished" datetime="2026-03-01">1 March</time></div>')
        rdfa = ('<div vocab="https://schema.org/" typeof="Article">'
                '<span property="author">Jane Doe</span>'
                '<span property="datePublished" content="2026-03-01">1 March</span></div>')
        for body in (microdata, rdfa):
            with self.subTest(body=body[:30]):
                self.assertEqual(self.provenance(html(body)), set())

    def test_filled_values_count(self):
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": "Rent",
              "author": {"@type": "Person", "name": "Jane Doe"},
              "datePublished": "2026-03-01"}
        self.assertEqual(self.provenance(html(jsonld=ld)), set())


class QuestionHeadings(unittest.TestCase):
    def test_declarative_wh_headings(self):
        for heading in ("Who we are", "What we offer", "Where we work", "How it works",
                        "Что мы делаем"):
            with self.subTest(heading=heading):
                self.assertFalse(aeo._is_question(heading))

    def test_real_questions(self):
        for heading in ("What is a deposit", "How to rent a flat", "Who we are?",
                        "Can you sublet?"):
            with self.subTest(heading=heading):
                self.assertTrue(aeo._is_question(heading))

    def test_about_page_gets_the_finding(self):
        from types import SimpleNamespace
        page = SimpleNamespace(url=SITE + "/", outline=None, paragraphs=[], word_count=50,
                               blocks={}, alts=[], lang="en",
                               headings=[(1, "About"), (2, "Who we are"), (2, "What we offer"),
                                         (2, "Where we work"), (2, "Contact")])
        self.assertIn("no-question-headings", {i[2] for i in aeo.check_extractable(page)})


if __name__ == "__main__":
    unittest.main()
