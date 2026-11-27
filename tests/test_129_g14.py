# -*- coding: utf-8 -*-
"""
1.29 (g14): микроданные и RDFa, автор и дата, свежесть событий.

* автор и дата микроданных и RDFa пропадали на страницах больше 4 КБ;
* `<time>` в комментарии снова считался датой на больших страницах;
* скрытая копия цены гасила `microdata-mismatch`, цена текстом скрытого
  элемента не сверялась, `price` под чужим `vocab` сверялся;
* пустые, безгодовые и вне сущности микроданные, `"0000-00-00"`, `"N/A"`,
  `true` и `{"@id": "#"}` считались автором и датой;
* статья в `WebPage.mainEntity`, `dateCreated`, `uploadDate` и организатор
  события не считались;
* `endDate: 9999-12-31` и огромный `grace_days` роняли прогон;
* у события считался только первый `<time>`, вложенное в `mainEntity` и
  микроданные `<time itemprop="startDate">` не читались;
* отзыв 2024 года прятал устаревший год в заголовках раздела.
"""

import datetime
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, core, freshness, signals

SITE = "https://demo.example"
TEXT = ("Flats in Springfield rent for about the same as last year, and most leases run "
        "for twelve months with a deposit of three monthly rents. ") * 3
TODAY = datetime.date(2026, 11, 1)


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


ARTICLE = '<div itemscope itemtype="https://schema.org/Article">{}</div>'
AUTH = '<meta name="author" content="Jane"><meta property="article:published_time" content="2025-01-01">'


class Site(unittest.TestCase):
    def page(self, text):
        root = tempfile.mkdtemp(prefix="indexgap-129-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return core.load_pages(root, SITE)[0][0]

    def provenance(self, text):
        return {i[2] for i in aeo.check_provenance(self.page(text))}

    def mismatch(self, text):
        return [i for i in aeo.run([self.page(text)])["issues"] if i[2] == "microdata-mismatch"]


class InlineProvenance(Site):
    MICRODATA = ('<div itemscope itemtype="https://schema.org/Article">'
                 '<span itemprop="author" itemscope itemtype="https://schema.org/Person">'
                 '<span itemprop="name">Jane Doe</span></span>'
                 '<time itemprop="datePublished" datetime="2026-03-01">1 March</time></div>')
    RDFA = ('<div vocab="https://schema.org/" typeof="Article">'
            '<span property="author">Jane Doe</span>'
            '<span property="datePublished" content="2026-03-01">1 March</span></div>')

    def test_large_pages_keep_inline_author_and_date(self):
        for body in (self.MICRODATA, self.RDFA):
            for pad in (0, 12):
                with self.subTest(body=body[:30], pad=pad):
                    text = html(body, pad=pad)
                    self.assertEqual(len(text) >= 4096, bool(pad))
                    self.assertEqual(self.provenance(text), set())

    def test_publisher_named_by_attribute(self):
        body = ('<div itemscope itemtype="https://schema.org/Article">'
                '<div itemprop="publisher" itemscope itemtype="https://schema.org/Organization">'
                '<meta itemprop="name" content="Demo Press"></div>'
                '<meta itemprop="datePublished" content="2026-03-01"></div>')
        self.assertEqual(self.provenance(html(body, pad=12)), set())

    def test_empty_yearless_unscoped_and_inert_do_not_count(self):
        for body in (ARTICLE.format('<meta itemprop="author" content="">'
                                    '<meta itemprop="datePublished" content="">'),
                     ARTICLE.format('<span itemprop="author"></span>'
                                    '<span itemprop="datePublished"></span>'),
                     ARTICLE.format('<meta itemprop="datePublished" content="soon">'),
                     '<div data-itemprop="author" data-property="datePublished">x</div>',
                     '<span itemprop="author">Jane</span>',
                     '<template>' + ARTICLE.format('<span itemprop="author">Jane</span>') + '</template>',
                     '<script>var t=\'<span itemprop="author">Jane</span>\';</script>'):
            with self.subTest(body=body[:60]):
                self.assertEqual(self.provenance(html(body)), {"no-author", "no-date"})

    def test_commented_and_template_time_on_large_pages(self):
        for body in ('<!-- <time datetime="2019-01-01">1 Jan</time> -->',
                     '<template><time datetime="2019-01-01">1 Jan</time></template>'):
            for pad in (0, 12):
                with self.subTest(body=body[:20], pad=pad):
                    self.assertIn("no-date", self.provenance(html(body, pad=pad)))

    def test_live_time_on_large_page_is_a_date(self):
        body = '<p>Open <time datetime="09:00">9</time>, updated <time datetime="2026-03-01">1 March</time></p>'
        self.assertNotIn("no-date", self.provenance(html(body, pad=12)))


class JsonLdProvenance(Site):
    def ld(self, **fields):
        return {"@context": "https://schema.org", "@type": "Article", "headline": "Rent", **fields}

    def test_garbage_values_are_not_provenance(self):
        for fields in ({"datePublished": "0000-00-00", "author": "N/A"},
                       {"datePublished": True, "author": True},
                       {"datePublished": "null", "author": "null"},
                       {"datePublished": "2025-01-01", "publisher": {"@id": "#"}}):
            with self.subTest(fields=fields):
                found = self.provenance(html(jsonld=self.ld(**fields)))
                self.assertIn("no-author", found)
                if fields["datePublished"] != "2025-01-01":
                    self.assertIn("no-date", found)

    def test_nested_article_and_other_date_keys(self):
        nested = {"@context": "https://schema.org", "@type": "WebPage",
                  "mainEntity": {"@type": "Article", "datePublished": "2026-10-01",
                                 "author": {"@type": "Person", "name": "Jane Doe"}}}
        part = {"@context": "https://schema.org", "@type": "WebPage",
                "hasPart": [{"@type": "Article", "datePublished": "2026-10-01",
                             "author": "Jane Doe"}]}
        for ld in (nested, part, self.ld(dateCreated="2026-10-01", author="Jane"),
                   {"@context": "https://schema.org", "@type": "VideoObject",
                    "uploadDate": "2026-10-01", "author": "Jane"}):
            with self.subTest(ld=str(ld)[:60]):
                self.assertEqual(self.provenance(html(jsonld=ld)), set())

    def test_event_organizer_is_an_organisation(self):
        ld = {"@context": "https://schema.org", "@type": "MusicEvent", "name": "Concert",
              "startDate": "2026-12-20", "organizer": {"@type": "Organization", "name": "Demo Hall"}}
        self.assertNotIn("no-author", self.provenance(html(jsonld=ld)))

    def test_id_reference_still_counts(self):
        self.assertTrue(aeo._filled({"@id": "https://demo.example/#organization"}))
        self.assertFalse(aeo._filled(True))


class MicrodataPrice(Site):
    def test_hidden_copy_does_not_hide_a_mismatch(self):
        for copy in ('<span style="display:none">$999</span>', '<span hidden>$999</span>'):
            with self.subTest(copy=copy):
                body = product(f'<meta itemprop="price" content="999">{copy}<p>Rent: $1,600.</p>')
                self.assertEqual(len(self.mismatch(html(body, AUTH))), 1)

    def test_hidden_element_text_price(self):
        body = product('<span itemprop="price" style="display:none">999</span><p>Rent: $1,600.</p>')
        self.assertEqual(len(self.mismatch(html(body, AUTH))), 1)

    def test_visible_element_text_and_tabs_stay_quiet(self):
        for body in (product('<span itemprop="price">1600</span><p>Rent: $1,600.</p>'),
                     product('<button aria-controls="t2">More</button><div id="t2" hidden>'
                             '<span itemprop="price">999</span></div><p>Rent: $1,600.</p>')):
            with self.subTest(body=body[-80:]):
                self.assertEqual(self.mismatch(html(body, AUTH)), [])

    def test_other_vocabulary_and_declared_prefix(self):
        other = ('<div vocab="http://purl.org/goodrelations/v1#" typeof="Offering">'
                 '<span property="price" content="999"></span><p>Rent: $1,600.</p></div>')
        self.assertEqual(self.mismatch(html(other, AUTH)), [])
        prefixed = ('<div prefix="s: https://schema.org/" typeof="s:Offer">'
                    '<meta property="s:price" content="999"><p>Rent: $1,600.</p></div>')
        self.assertEqual(len(self.mismatch(html(prefixed, AUTH))), 1)


class Freshness(Site):
    def event(self, body="", jsonld=None):
        return self.page(html(body, jsonld=jsonld))

    def stale(self, page, cfg=None):
        return [i[2] for i in freshness.check([page], cfg, today=TODAY)["issues"]]

    def test_far_future_end_date_does_not_crash(self):
        ld = {"@context": "https://schema.org", "@type": "ExhibitionEvent",
              "startDate": "2020-01-01", "endDate": "9999-12-31"}
        self.assertEqual(self.stale(self.event(jsonld=ld)), [])

    def test_huge_grace_days_do_not_crash(self):
        ld = {"@context": "https://schema.org", "@type": "Event", "startDate": "2025-01-10"}
        for grace in (3000000, 1e9, 99999999999):
            with self.subTest(grace=grace):
                self.assertEqual(self.stale(self.event(jsonld=ld), {"grace_days": grace}), [])

    def test_latest_time_counts(self):
        ld = {"@context": "https://schema.org", "@type": "MusicEvent", "name": "Concert"}
        body = ('<time datetime="2024-05-01">Announced</time> '
                '<time datetime="2026-12-20">Concert night</time>')
        self.assertEqual(self.stale(self.event(body, ld)), [])

    def test_event_in_main_entity(self):
        ld = {"@context": "https://schema.org", "@type": "WebPage",
              "mainEntity": {"@type": "Event", "startDate": "2025-03-10", "endDate": "2025-03-12"}}
        self.assertEqual(self.stale(self.event(jsonld=ld)), ["stale-event"])

    def test_item_list_archive_is_not_an_event(self):
        ld = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "item": {"@type": "Event", "startDate": "2025-03-10"}}]}
        self.assertEqual(self.stale(self.event(jsonld=ld)), [])

    def test_microdata_time_event(self):
        body = ('<div itemscope itemtype="https://schema.org/Event"><span itemprop="name">Gig</span>'
                '<time itemprop="startDate" datetime="2025-02-14">14 Feb</time></div>')
        self.assertEqual(self.stale(self.event(body)), ["stale-event"])


class StaleYear(unittest.TestCase):
    def pages(self, review):
        out = []
        for i in range(8):
            ld = {"@context": "https://schema.org", "@type": "LocalBusiness",
                  "name": f"Plumber {i}", "datePublished": "2026-10-01"}
            if review:
                ld["review"] = {"@type": "Review", "datePublished": "2024-06-01",
                                "author": "Sam", "reviewBody": "Fine."}
            title = f"Best plumbers in Town{i} 2024"
            out.append(core.Page(path=f"/x/{i}.html", url=f"{SITE}/plumbing/t{i}/", title=title,
                                 headings=[(1, title)], jsonld=[json.dumps(ld)]))
        return out

    def test_nested_review_date_is_not_the_page_date(self):
        for review in (False, True):
            with self.subTest(review=review):
                found = signals.stale_years(self.pages(review), TODAY)
                self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
