# -*- coding: utf-8 -*-
"""
1.28: скрытое не видно.

Вопрос FAQ в `<div hidden>` или `display:none` и цена в `<p hidden>` считались
видимыми: разметка «совпадала» со страницей, которую читатель не видит.
Скрытым считаются только `hidden` и `display:none` / `visibility:hidden` в
style, и только вне `<details>`. Вкладки, раскрывашки, `hidden="until-found"`,
`aria-hidden` и потоковый рендер React остаются видимыми: Google считает
содержимое вкладок видимым.
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
BLOCK = f"<h2>{QUESTION}</h2><p>Up to three net monthly rents.</p>"


def html(body="", jsonld=None):
    ld = ""
    if jsonld is not None:
        ld = f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
    return (f"<!doctype html><html lang=\"en\"><head><title>Rent in Springfield</title>"
            f"{ld}</head><body><main><h1>Rent in Springfield</h1>{body}"
            f"<p>{TEXT}</p></main></body></html>")


def faq(question=QUESTION):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": question,
         "acceptedAnswer": {"@type": "Answer", "text": "Up to three net monthly rents."}}]}


def product(price="1600", rating="4.9", count="312"):
    return {"@context": "https://schema.org", "@type": "Product", "name": "Flat",
            "offers": {"@type": "Offer", "price": price, "priceCurrency": "USD"},
            "aggregateRating": {"@type": "AggregateRating", "ratingValue": rating,
                                "reviewCount": count}}


class Site(unittest.TestCase):
    def page(self, text):
        root = tempfile.mkdtemp(prefix="indexgap-128-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return core.load_pages(root, SITE)[0][0]

    def codes(self, text):
        return {i[2] for i in aeo.check_jsonld(self.page(text))}


class HiddenFaq(Site):
    def test_hidden_attribute(self):
        codes = self.codes(html(f"<div hidden>{BLOCK}</div>", faq()))
        self.assertIn("jsonld-faq-invisible", codes)

    def test_inline_styles(self):
        for style in ("display:none", "display: none !important", "DISPLAY:NONE",
                      "color:red; visibility: hidden"):
            with self.subTest(style=style):
                codes = self.codes(html(f'<div style="{style}">{BLOCK}</div>', faq()))
                self.assertIn("jsonld-faq-invisible", codes)

    def test_nested_inside_a_hidden_block(self):
        body = f"<section hidden><div><ul><li>{BLOCK}</li></ul></div></section>"
        self.assertIn("jsonld-faq-invisible", self.codes(html(body, faq())))

    def test_hidden_text_stays_in_page_text(self):
        # Остальные проверки по-прежнему видят весь текст страницы.
        page = self.page(html(f"<div hidden>{BLOCK}</div>", faq()))
        self.assertIn(QUESTION, page.text)
        self.assertNotIn(QUESTION, page.shown)


class Guards(Site):
    """Корректные страницы молчат."""

    def assertQuiet(self, body, ld=None):
        codes = self.codes(html(body, ld or faq()))
        self.assertNotIn("jsonld-faq-invisible", codes)
        self.assertNotIn("jsonld-mismatch", codes)

    def test_plain_visible_question(self):
        self.assertQuiet(BLOCK)
        self.assertIsNone(self.page(html(BLOCK, faq())).shown)

    def test_closed_details_are_visible(self):
        self.assertQuiet(f"<details><summary>{QUESTION}</summary><p>Up to three.</p></details>")

    def test_hidden_inside_details_is_visible(self):
        self.assertQuiet(f"<details><summary>FAQ</summary><div hidden>{BLOCK}</div></details>")

    def test_hidden_until_found(self):
        self.assertQuiet(f'<div hidden="until-found">{BLOCK}</div>')

    def test_aria_hidden_is_still_visible(self):
        self.assertQuiet(f'<div aria-hidden="true">{BLOCK}</div>')

    def test_inactive_tab_panels(self):
        for attrs in ('role="tabpanel" hidden', 'aria-labelledby="tab-2" hidden',
                      'data-state="closed" hidden', 'role="tabpanel" style="display:none"'):
            with self.subTest(attrs=attrs):
                self.assertQuiet(f"<div {attrs}>{BLOCK}</div>")

    def test_panel_controlled_by_a_button(self):
        for trigger in ('<button aria-controls="faq-2" aria-expanded="false">More</button>',
                        '<a href="#faq-2">More</a>',
                        '<button data-bs-target="#faq-2">More</button>'):
            with self.subTest(trigger=trigger):
                self.assertQuiet(f'{trigger}<div id="faq-2" hidden>{BLOCK}</div>')
        # Кнопка после панели — тоже кнопка.
        self.assertQuiet(f'<div id="faq-3" style="display:none">{BLOCK}</div>'
                         '<button aria-controls="faq-1 faq-3">More</button>')

    def test_page_hidden_until_styles_load(self):
        text = html(BLOCK, faq()).replace("<body>", '<body style="display:none">')
        self.assertNotIn("jsonld-faq-invisible", self.codes(text))
        text = html(BLOCK, faq()).replace('<html lang="en">',
                                          '<html lang="en" style="visibility:hidden">')
        self.assertNotIn("jsonld-faq-invisible", self.codes(text))

    def test_react_streaming_placeholder(self):
        self.assertQuiet(f'<div hidden id="S:0">{BLOCK}</div>')

    def test_visible_copy_next_to_a_hidden_one(self):
        self.assertQuiet(f"{BLOCK}<div hidden>{BLOCK}</div>")

    def test_custom_property_is_not_display(self):
        self.assertQuiet(f'<div style="--md-display:none; --x-visibility:hidden">{BLOCK}</div>')

    def test_hidden_block_closes(self):
        self.assertQuiet(f"<div hidden><p>Old banner</p></div>{BLOCK}")
        self.assertQuiet(f"<div hidden><p>Old banner</div>{BLOCK}")

    def test_visible_price_with_hidden_duplicate(self):
        body = ("<p>Monthly rent: $1,600. Rated 4.9 from 312 reviews.</p>"
                "<p hidden>Monthly rent: $1,600.</p>")
        self.assertQuiet(body, product())


class HiddenNumbers(Site):
    def test_price_and_rating_only_in_hidden_text(self):
        body = ("<p hidden>Monthly rent: $1,600. Rated 4.9 from 312 reviews.</p>"
                "<p>Monthly rent: $2,100.</p>")
        self.assertIn("jsonld-mismatch", self.codes(html(body, product())))

    def test_price_only_in_display_none(self):
        body = ('<span style="display:none">$1,600</span>'
                "<p>Monthly rent: $2,100. Rated 4.9 from 312 reviews.</p>")
        self.assertIn("jsonld-mismatch", self.codes(html(body, product())))

    def test_price_in_a_tab_stays_visible(self):
        body = ('<div role="tabpanel" hidden>Yearly plan: $1,600.</div>'
                "<p>Monthly rent: $2,100. Rated 4.9 from 312 reviews.</p>")
        self.assertNotIn("jsonld-mismatch", self.codes(html(body, product())))


if __name__ == "__main__":
    unittest.main()
