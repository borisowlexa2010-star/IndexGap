# -*- coding: utf-8 -*-
"""
1.29 (g13): прямой ответ, вопросные подзаголовки, структура и сверка JSON-LD.
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
QUESTION = "How large is the deposit in Springfield?"


def html(body="", jsonld=None, raw=None, lang="en", tail=True):
    ld = ""
    if jsonld is not None:
        raw = json.dumps(jsonld)
    if raw is not None:
        ld = f'<script type="application/ld+json">{raw}</script>'
    return (f"<!doctype html><html lang=\"{lang}\"><head><title>Rent in Springfield</title>"
            f"{ld}</head><body><main><h1>Rent in Springfield</h1>{body}"
            f"{'<p>' + TEXT + '</p>' if tail else ''}</main></body></html>")


def faq(question=QUESTION):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": question,
         "acceptedAnswer": {"@type": "Answer", "text": "Up to three net monthly rents."}}]}


def product(price="1600", rating="4.9", count="312"):
    return {"@context": "https://schema.org", "@type": "Product", "name": "Flat",
            "offers": {"@type": "Offer", "price": price, "priceCurrency": "USD"},
            "aggregateRating": {"@type": "AggregateRating", "ratingValue": rating,
                                "reviewCount": count}}


class Base(unittest.TestCase):
    def page(self, text):
        root = tempfile.mkdtemp(prefix="indexgap-129-g13-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return core.load_pages(root, SITE)[0][0]

    def ld(self, text):
        page = self.page(text)
        return [i[2] for i in aeo.check_jsonld(page) + aeo.check_microdata(page)]

    def answer(self, text):
        page = self.page(text)
        return [i[2] for i in aeo.check_answer(page) + aeo.check_extractable(page)]


class Answer(Base):
    def test_by_month_sentence_is_an_answer(self):
        body = ("<p>By September 2026, every landlord in Springfield must register "
                "the deposit with the city.</p>")
        self.assertNotIn("no-answer", self.answer(html(body, tail=False)))
        self.assertFalse(aeo._is_dateline(
            "Updated 2026 rules cap the deposit at three monthly rents for every flat."))
        self.assertTrue(aeo._is_dateline("By John Smith · Updated 12 March 2026 · 5 min read"))
        self.assertTrue(aeo._is_dateline("Updated September 2026"))

    def test_preamble_after_aside(self):
        body = ("<aside><p>Related reading: how to choose a neighbourhood in Springfield</p>"
                "</aside><p>In this article we will explore everything you need to know "
                "about renting a flat in Springfield.</p>")
        self.assertIn("answer-preamble", self.answer(html(body)))

    def test_preamble_in_curly_quotes_or_after_emoji(self):
        for lead, end in (("“", "”"), ("„", "“"), ("🏠 ", "")):
            body = (f"<p>{lead}In this guide we will explore everything you need to know "
                    f"about renting a flat in Springfield.{end}</p>")
            with self.subTest(lead=lead):
                self.assertIn("answer-preamble", self.answer(html(body)))

    def test_short_chinese_answer_is_not_short(self):
        body = "<p>斯普林菲尔德的公寓月租约为一千二百美元，押金为三个月租金。</p>"
        self.assertNotIn("answer-short", self.answer(html(body, lang="zh", tail=False)))
        long_zh = "<p>" + "斯普林菲尔德的公寓月租约为一千二百美元，押金为三个月租金。" * 9 + "</p>"
        self.assertIn("answer-long", self.answer(html(long_zh, lang="zh", tail=False)))


class Questions(unittest.TestCase):
    def test_wrapped_questions(self):
        for text in ("«Можно ли сдать квартиру в субаренду?»", "“Can I sublet?”",
                     "Deposit refundable?)", "1. How much is rent", "Q: How much is rent",
                     "📌 How much is rent", "— Сколько стоит аренда"):
            with self.subTest(text=text):
                self.assertTrue(aeo._is_question(text))

    def test_auxiliary_without_subject_is_not_a_question(self):
        for text in ("Do your research first", "Do not sign without reading",
                     "Can opener and kitchen kit", "Is", "Will Smith", "How-to: rent"):
            with self.subTest(text=text):
                self.assertFalse(aeo._is_question(text))
        for text in ("Can I sublet", "Is it worth renting", "Do I need a permit"):
            with self.subTest(text=text):
                self.assertTrue(aeo._is_question(text))

    def test_more_languages(self):
        for text in ("Скільки коштує оренда", "Чи можна здавати в суборенду",
                     "Ile kosztuje wynajem", "Kolik stojí nájem", "Hoeveel kost huren",
                     "Vad kostar hyran", "Πόσο κοστίζει το ενοίκιο", "Combien coûte le loyer",
                     "Le dépôt est-il remboursable", "Bao nhiêu tiền thuê",
                     "Depozito iade edilir mi"):
            with self.subTest(text=text):
                self.assertTrue(aeo._is_question(text))
        self.assertFalse(aeo._is_question("Что-то новое"))


class Structure(Base):
    PROSE = "".join(f"<p>{TEXT}</p>" for _ in range(7))

    def test_definition_list_is_structure(self):
        dl = "<dl>" + "".join(f"<dt>Term {i}</dt><dd>Meaning {i}</dd>" for i in range(6)) + "</dl>"
        self.assertNotIn("no-structure", self.answer(html(self.PROSE + dl)))

    def test_share_button_and_layout_table_are_not_structure(self):
        share = "<ul class='share-buttons'><li><a href='#'>Share</a></li></ul>"
        self.assertIn("no-structure", self.answer(html(self.PROSE + share)))
        layout = f"<table role='presentation'><tr><td>{self.PROSE}</td></tr></table>"
        self.assertIn("no-structure", self.answer(html(layout)))

    def test_thai_volume(self):
        thai = "<p>" + "การเช่าคอนโดในเมืองนี้มีค่าใช้จ่ายรายเดือนและเงินมัดจำสามเดือน" * 40 + "</p>"
        self.assertIn("no-structure", self.answer(html(thai * 2, lang="th", tail=False)))


class JsonLd(Base):
    def test_yoast_id_references_are_resolved(self):
        graph = {"@context": "https://schema.org", "@graph": [
            {"@type": ["WebPage", "FAQPage"], "@id": SITE + "/#page",
             "mainEntity": [{"@id": SITE + "/#faq-question-1"}]},
            {"@type": "Question", "@id": SITE + "/#faq-question-1",
             "name": "Is there a pet fee in Springfield?",
             "acceptedAnswer": {"@type": "Answer", "text": "No."}}]}
        self.assertIn("jsonld-faq-invisible", self.ld(html(jsonld=graph)))
        shown = html("<h2>Is there a pet fee in Springfield?</h2>", jsonld=graph)
        self.assertNotIn("jsonld-faq-invisible", self.ld(shown))

    def test_iri_types(self):
        for name in ("https://schema.org/FAQPage", "http://schema.org/FAQPage", "schema:FAQPage"):
            data = faq()
            data["@type"] = name
            with self.subTest(name=name):
                self.assertIn("jsonld-faq-invisible", self.ld(html(jsonld=data)))
        data = product(price="2100", rating="4.9", count="312")
        data["aggregateRating"]["@type"] = "https://schema.org/AggregateRating"
        data = {"@context": "https://schema.org", "@graph": [data["aggregateRating"]]}
        self.assertIn("jsonld-mismatch", self.ld(html("<p>Rated 4.2 from 87 reviews</p>", jsonld=data)))

    def test_cents_against_decimal_comma(self):
        self.assertIn("jsonld-mismatch", self.ld(html("<p>Preis pro Nacht: 19,99 €</p>",
                                                      jsonld=product("1999", "4.9", "312")
                                                      | {"aggregateRating": None})))
        self.assertNotIn("jsonld-mismatch", self.ld(html("<p>Price: $1,600</p>",
                                                         jsonld=product("1600") | {"aggregateRating": None})))

    def test_integer_rating_is_not_the_scale(self):
        body = "<p>Rated 4.2 out of 5 from 87 reviews</p>"
        self.assertIn("jsonld-mismatch", self.ld(html(body, jsonld=product("1600", "5", "87")
                                                      | {"offers": None})))
        self.assertIn("jsonld-mismatch", self.ld(html(body, jsonld=product("1600", "4.2", "2")
                                                      | {"offers": None})))
        self.assertNotIn("jsonld-mismatch", self.ld(html("<p>Rated 5 out of 5 from 87 reviews</p>",
                                                         jsonld=product("1600", "5", "87")
                                                         | {"offers": None})))

    def test_deep_and_value_object_price(self):
        offer = {"@type": "Offer", "priceSpecification": {"@type": "UnitPriceSpecification",
                                                          "price": "1600"}}
        data = {"@context": "https://schema.org", "@graph": [{"@type": "CollectionPage",
                "mainEntity": {"@type": "ItemList", "itemListElement": [
                    {"@type": "ListItem", "item": {"@type": "Product", "offers": [offer]}}]}}]}
        self.assertIn("jsonld-mismatch", self.ld(html("<p>Only $2,100</p>", jsonld=data)))
        value = {"@context": "https://schema.org", "@type": "Offer", "price": {"@value": "1600"}}
        self.assertIn("jsonld-mismatch", self.ld(html("<p>Only $2,100</p>", jsonld=value)))

    def test_microdata_hidden_price(self):
        body = ('<div itemscope itemtype="https://schema.org/Offer">'
                '<meta itemprop="price" content="1600"></div>'
                '<p hidden>$1,600</p><p>Now $2,100</p>')
        self.assertIn("microdata-mismatch", self.ld(html(body)))

    def test_linked_or_split_question_is_visible(self):
        question = "What is Springfield's average rent?"
        for body in ('<h2>What is <a href="/springfield/">Springfield</a>\'s average rent?</h2>',
                     "<h2>What is <span>Spring</span><span>field</span>'s average rent?</h2>"):
            with self.subTest(body=body):
                self.assertEqual(self.ld(html(body, jsonld=faq(question))), [])

    def test_scalar_main_entity_does_not_crash(self):
        for value in (5, True):
            data = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": value}
            with self.subTest(value=value):
                self.assertEqual(self.ld(html(jsonld=data)), [])

    def test_german_thousands_in_markup(self):
        data = product("1.600") | {"aggregateRating": None}
        self.assertIn("jsonld-mismatch", self.ld(html("<p>Miete 1.600 €</p>", jsonld=data)))
        self.assertNotIn("jsonld-mismatch", self.ld(html("<p>Miete 1,60 €</p>", jsonld=data)))

    def test_empty_type(self):
        for value in ("", [], None, "  "):
            data = {"@context": "https://schema.org", "@type": value, "name": "Flat"}
            with self.subTest(value=value):
                self.assertIn("jsonld-no-type", self.ld(html(jsonld=data)))
        for raw in ("null", '"hello"', "42"):
            with self.subTest(raw=raw):
                self.assertIn("jsonld-no-type", self.ld(html(raw=raw)))
        self.assertEqual(self.ld(html(jsonld={"@context": "https://schema.org"})), [])

    def test_visible_child_of_visibility_hidden(self):
        body = (f'<div style="visibility:hidden"><h2 style="visibility:visible">{QUESTION}'
                "</h2></div>")
        self.assertEqual(self.ld(html(body, jsonld=faq())), [])
        hidden = (f'<div style="visibility:hidden"><span style="visibility:visible">x</span>'
                  f"<h2>{QUESTION}</h2></div>")
        self.assertIn("jsonld-faq-invisible", self.ld(html(hidden, jsonld=faq())))
        none = (f'<div style="display:none"><h2 style="visibility:visible">{QUESTION}</h2></div>')
        self.assertIn("jsonld-faq-invisible", self.ld(html(none, jsonld=faq())))

    def test_duplicate_blocks_give_one_finding(self):
        raw = json.dumps(faq())
        text = html().replace("</head>", f'<script type="application/ld+json">{raw}</script>'
                              f'<script type="application/ld+json">{raw}</script></head>')
        self.assertEqual(self.ld(text), ["jsonld-faq-invisible"])


if __name__ == "__main__":
    unittest.main()
