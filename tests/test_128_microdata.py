# -*- coding: utf-8 -*-
"""
1.28: цена микроданных и RDFa сверяется с видимым текстом.

`<meta itemprop="price" content="999">` рядом с видимыми «$1,600» Google
читает так же, как JSON-LD, но `jsonld-mismatch` смотрел только JSON-LD.
Теперь такое расхождение — `microdata-mismatch`. Верные страницы молчат:
цена текстом элемента, цена в другом написании, свойство вне сущности,
в `<template>` и `<noscript>`, словари не schema.org, число из JSON-LD.
"""

import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, core, report, repair

SITE = "https://demo.example"
TEXT = ("Flats in Springfield rent for about the same as last year, and most leases run "
        "for twelve months with a deposit of three monthly rents. ") * 3


def html(body="", head="", jsonld=None, pad=0):
    ld = ""
    if jsonld is not None:
        ld = f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
    filler = ("<p>" + TEXT + "</p>") * pad
    return (f"<!doctype html><html lang=\"en\"><head><title>Rent in Springfield</title>"
            f"{head}{ld}</head><body><main><h1>Rent in Springfield</h1>{body}"
            f"<p>{TEXT}</p>{filler}</main></body></html>")


def product(inner):
    return ('<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Flat</span>'
            '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
            f'{inner}</div></div>')


class Site(unittest.TestCase):
    def page(self, text):
        root = tempfile.mkdtemp(prefix="indexgap-128-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return core.load_pages(root, SITE)[0][0]

    def found(self, text):
        return [i for i in aeo.run([self.page(text)])["issues"] if i[2] == "microdata-mismatch"]


class Mismatch(Site):
    def test_meta_price_differs_from_visible(self):
        issues = self.found(html(product(
            '<meta itemprop="price" content="999"><meta itemprop="priceCurrency" content="USD">'
            '<p>Monthly rent: $1,600.</p>')))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0][0], "warning")
        self.assertIn("price 999", issues[0][3])

    def test_large_page_still_checked(self):
        # Исходник больших страниц не хранится целиком: цена должна прийти из разбора.
        text = html(product('<meta itemprop="price" content="999"><p>Monthly rent: $1,600.</p>'),
                    pad=40)
        self.assertGreater(len(text), 8000)
        self.assertEqual(len(self.found(text)), 1)

    def test_span_content_differs_from_its_text(self):
        issues = self.found(html(product(
            '<p>Monthly rent: <span itemprop="price" content="999">$1,600</span></p>')))
        self.assertEqual(len(issues), 1)

    def test_rdfa_schema_prefix(self):
        body = ('<div vocab="https://schema.org/" typeof="Offer">'
                '<span property="schema:price" content="49.99"></span>'
                '<p>Monthly fee: $59.99.</p></div>')
        self.assertEqual(len(self.found(html(body))), 1)

    def test_rdfa_bare_property(self):
        body = ('<div vocab="https://schema.org/" typeof="Offer">'
                '<meta property="price" content="2500"><p>Monthly rent: $1,600.</p></div>')
        self.assertEqual(len(self.found(html(body))), 1)

    def test_low_and_high_price(self):
        body = ('<div itemscope itemtype="https://schema.org/AggregateOffer">'
                '<meta itemprop="lowPrice" content="10"><meta itemprop="highPrice" content="90">'
                '<p>From $10 to $20.</p></div>')
        issues = self.found(html(body))
        self.assertEqual(len(issues), 1)
        self.assertIn("highPrice 90", issues[0][3])
        self.assertNotIn("lowPrice", issues[0][3])

    def test_data_element_value(self):
        body = product('<data itemprop="price" value="999">Monthly rent: $1,600</data>')
        self.assertEqual(len(self.found(html(body))), 1)

    def test_english_message(self):
        from indexgap import i18n
        page = self.page(html(product('<meta itemprop="price" content="999"><p>Rent: $1,600.</p>')))
        old = i18n.get_lang()
        i18n.set_lang("en")
        try:
            issues = aeo.check_microdata(page)
        finally:
            i18n.set_lang(old)
        self.assertTrue(issues[0][3].startswith("the microdata says price 999"))


class StaysQuiet(Site):
    def test_same_price_other_spelling(self):
        for content, shown in (("1600", "$1,600"), ("1600.00", "$1,600"), ("16.99", "16,99 €"),
                               ("1600", "1 600 €"), ("1600", "$1.6k")):
            with self.subTest(content=content, shown=shown):
                body = product(f'<meta itemprop="price" content="{content}"><p>Rent: {shown}.</p>')
                self.assertEqual(self.found(html(body)), [])

    def test_price_as_element_text(self):
        body = product('<p>Monthly rent: $<span itemprop="price">1600</span></p>')
        self.assertEqual(self.found(html(body)), [])

    def test_zero_and_empty_price(self):
        for content in ("0", "0.00", "", "  "):
            with self.subTest(content=content):
                body = product(f'<meta itemprop="price" content="{content}"><p>Free entry.</p>')
                self.assertEqual(self.found(html(body)), [])

    def test_outside_itemscope(self):
        body = '<meta itemprop="price" content="999"><p>Monthly rent: $1,600.</p>'
        self.assertEqual(self.found(html(body)), [])

    def test_offers_itemprop_on_scope_is_not_a_price(self):
        body = ('<div itemscope itemtype="https://schema.org/Product">'
                '<div itemprop="price" itemscope content="999"></div><p>Rent: $1,600.</p></div>')
        self.assertEqual(self.found(html(body)), [])

    def test_after_scope_closes(self):
        body = (product('<meta itemprop="price" content="1600"><p>Rent: $1,600.</p>')
                + '<p>Other block</p><meta itemprop="price" content="999">')
        self.assertEqual(self.found(html(body)), [])

    def test_inert_blocks(self):
        for wrap in ("<template>{}</template>", "<noscript>{}</noscript>",
                     "<!-- {} -->", "<script type=\"text/template\">{}</script>"):
            with self.subTest(wrap=wrap):
                inner = product('<meta itemprop="price" content="999">')
                body = wrap.format(inner) + "<p>Monthly rent: $1,600.</p>"
                self.assertEqual(self.found(html(body)), [])

    def test_open_graph_and_other_vocabularies(self):
        head = ('<meta property="og:price:amount" content="999">'
                '<meta property="product:price:amount" content="999">')
        body = ('<div typeof="gr:Offering"><span property="gr:price" content="999"></span>'
                '<span property="http://example.org/vocab/price" content="999"></span>'
                '<p>Monthly rent: $1,600.</p></div>')
        self.assertEqual(self.found(html(body, head=head)), [])

    def test_number_in_json_ld_left_to_jsonld_check(self):
        ld = {"@context": "https://schema.org", "@type": "Product", "name": "Flat",
              "offers": {"@type": "Offer", "price": "999", "priceCurrency": "USD"}}
        page = self.page(html(product('<meta itemprop="price" content="999"><p>Rent: $1,600.</p>'),
                              jsonld=ld))
        codes = [i[2] for i in aeo.run([page])["issues"]]
        self.assertIn("jsonld-mismatch", codes)
        self.assertNotIn("microdata-mismatch", codes)

    def test_rating_text_not_judged(self):
        body = ('<div itemscope itemtype="https://schema.org/Product">'
                '<div itemprop="aggregateRating" itemscope>'
                '<meta itemprop="ratingValue" content="4.9"><meta itemprop="reviewCount" content="77">'
                '</div><p>Rated by our tenants.</p></div>')
        self.assertEqual(self.found(html(body)), [])

    def test_page_without_microdata(self):
        page = self.page(html("<p>Monthly rent: $1,600.</p>"))
        self.assertEqual(page.microdata, [])
        self.assertEqual(aeo.check_microdata(page), [])


class Registered(unittest.TestCase):
    def test_code_everywhere(self):
        self.assertIn("microdata-mismatch", checks.CODE_WEIGHT)
        self.assertIn("microdata-mismatch", report.CODE_HELP)
        self.assertIn("microdata-mismatch", repair.FIX)


if __name__ == "__main__":
    unittest.main()
