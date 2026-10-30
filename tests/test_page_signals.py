# -*- coding: utf-8 -*-
"""
Восемь проверок из разбора чужого списка в 232 приёма SEO: те, что считаются
по файлам сборки, без сети, и бьют по программным страницам.

* JSON-LD называет цену или рейтинг, которых нет в видимом тексте;
* раздел не ссылается на свои страницы — их находят только по sitemap;
* в title или H1 устаревший год: «Лучшие сантехники 2024» в 2026-м;
* title и H1 обещают разное;
* нет og:title / og:image — ссылка в мессенджере без превью;
* нет meta viewport — страница не для телефона;
* HTML больше 2 МБ — Googlebot читает первые 2 МБ, хвост в индекс не идёт;
* тяжёлые картинки в сборке.
"""

import datetime
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, core

SITE = "https://example.com"
TEXT = ("Plumbers in Austin fix leaks, unclog drains and install water heaters. Most "
        "visits take under two hours, and every job comes with a written quote first. ") * 3
YEAR = datetime.date.today().year


def html(title="Plumbers in Austin, TX", h1="Plumbers in Austin", body="", head="",
         viewport=True, og=True, jsonld=None):
    meta = ('<meta name="viewport" content="width=device-width, initial-scale=1">'
            if viewport else "")
    if og:
        meta += (f'<meta property="og:title" content="{title}">'
                 '<meta property="og:image" content="https://example.com/a.png">')
    ld = (f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
          if jsonld else "")
    return (f"<!doctype html><html lang=\"en\"><head><title>{title}</title>"
            f"<meta name=\"description\" content=\"Licensed plumbers in Austin for every job\">"
            f"{meta}{head}{ld}</head><body><main><h1>{h1}</h1><p>{TEXT}</p>{body}</main>"
            "</body></html>")


class Site(unittest.TestCase):
    def build(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-signals-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            mode = "wb" if isinstance(text, bytes) else "w"
            with open(path, mode, **({} if isinstance(text, bytes) else {"encoding": "utf-8"})) as fh:
                fh.write(text)
        self.root = root
        return core.load_pages(root, SITE)[0]

    def issues(self, files):
        pages = self.build(files)
        return checks.run_all(pages, SITE + "/")["issues"] + aeo.run(pages)["issues"]

    def codes(self, files, url=None):
        return sorted({(i[0], i[2]) for i in self.issues(files)
                       if url is None or i[1] == SITE + url})


class JsonLd(Site):
    def ld(self, price="1600", rating="4.6"):
        return {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "Acme",
                "aggregateRating": {"@type": "AggregateRating", "ratingValue": rating,
                                    "reviewCount": "1801"},
                "makesOffer": {"@type": "Offer", "price": price, "priceCurrency": "USD"}}

    def test_a_price_the_page_does_not_show(self):
        page = html(body="<p>Rated 4.6 out of 5 across 1,801 reviews. From $1,900 per job.</p>",
                    jsonld=self.ld())
        self.assertIn(("warning", "jsonld-mismatch"), self.codes({"index.html": page}))

    def test_matching_values_in_any_spelling(self):
        page = html(body="<p>Rated 4,6 out of 5 across 1 801 reviews. From $1,600.00 per job.</p>",
                    jsonld=self.ld(price="1600.00"))
        self.assertNotIn(("warning", "jsonld-mismatch"), self.codes({"index.html": page}))

    def test_a_rating_the_page_does_not_show(self):
        page = html(body="<p>Rated 4.2 out of 5 across 1,801 reviews. From $1,600.</p>",
                    jsonld=self.ld())
        self.assertIn(("warning", "jsonld-mismatch"), self.codes({"index.html": page}))

    def test_price_spellings_from_real_shops(self):
        # $16<sup>99</sup>, раздельные центы, индийские и швейцарские разряды, «1.2K».
        cases = [("16.99", "<p>Only $16<sup>99</sup> today</p>"),
                 ("16.99", "<p>Only <span>$16</span><span>.99</span> today</p>"),
                 ("160000", "<p>Price ₹1,60,000 per year</p>"),
                 ("1600.00", "<p>Price CHF 1'600.00 per job</p>"),
                 ("1600", "<p>From $1.6k per job</p>")]
        for price, body in cases:
            with self.subTest(body=body):
                ld = {"@context": "https://schema.org", "@type": "Product", "name": "Acme",
                      "offers": {"@type": "Offer", "price": price, "priceCurrency": "USD"}}
                self.assertNotIn(("warning", "jsonld-mismatch"),
                                 self.codes({"index.html": html(body=body, jsonld=ld)}))

    def test_review_count_in_thousands(self):
        ld = {"@context": "https://schema.org", "@type": "Product", "name": "Acme",
              "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.8",
                                  "reviewCount": "1234"}}
        page = html(body="<p>Rated 4.8 from 1.2K reviews</p>", jsonld=ld)
        self.assertNotIn(("warning", "jsonld-mismatch"), self.codes({"index.html": page}))

    def test_a_price_written_with_its_currency_in_the_markup_is_still_checked(self):
        for price in ("$1,600", "1600 USD"):
            with self.subTest(price=price):
                ld = {"@context": "https://schema.org", "@type": "Product", "name": "Acme",
                      "offers": {"@type": "Offer", "price": price}}
                page = html(body="<p>From $1,500 per job</p>", jsonld=ld)
                self.assertIn(("warning", "jsonld-mismatch"), self.codes({"index.html": page}))

    def test_no_numbers_in_markup_is_fine(self):
        page = html(jsonld={"@context": "https://schema.org", "@type": "Article",
                            "headline": "Plumbers"})
        self.assertNotIn(("warning", "jsonld-mismatch"), self.codes({"index.html": page}))


class Hubs(Site):
    def site(self, linked=("austin", "dallas", "houston"), extra=None):
        cities = ("austin", "dallas", "houston", "boston")
        files = {"index.html": html(body='<a href="/plumbing/">plumbing</a>'),
                 "plumbing/index.html": html(title="Plumbing in every city", h1="Plumbing",
                                             body="".join(f'<a href="/plumbing/{c}/">{c}</a>'
                                                          for c in linked))}
        for c in cities:
            files[f"plumbing/{c}/index.html"] = html(title=f"Plumbers in {c.title()}",
                                                     h1=f"Plumbers in {c.title()}",
                                                     body='<a href="/plumbing/">all</a>')
        files.update(extra or {})
        return files

    def test_a_section_page_that_misses_its_children(self):
        issues = [i for i in self.issues(self.site()) if i[2] == "hub-missing-links"]
        self.assertEqual([(i[0], i[1]) for i in issues], [("warning", SITE + "/plumbing/")])
        self.assertIn("/plumbing/boston", issues[0][3])

    def test_a_section_that_links_all_is_fine(self):
        files = self.site(linked=("austin", "dallas", "houston", "boston"))
        self.assertNotIn("hub-missing-links", [i[2] for i in self.issues(files)])

    def test_pagination_of_the_section_counts(self):
        files = self.site(extra={"plumbing/page/2/index.html": html(
            title="Plumbing page 2", h1="Plumbing",
            body='<a href="/plumbing/boston/">boston</a>')})
        self.assertNotIn("hub-missing-links", [i[2] for i in self.issues(files)])


class StaleYear(Site):
    """
    Прошлый год в заголовке — находка шаблона, а не страницы.

    Одна страница с годом в заголовке неоднозначна: «2019 Honda Civic price»,
    «The Batman (2022) review», «Paris Olympics 2024» — о том годе и написаны.
    Забытый шаблон виден иначе: один и тот же прошлый год стоит в заголовках
    заметной доли страниц раздела.
    """

    CITIES = ("Austin", "Boston", "Dallas", "Denver", "Miami", "Tampa")

    def section(self, title, head="", n=6):
        return {f"plumbing/{c.lower()}/index.html": html(title=title.format(city=c),
                                                         h1=title.format(city=c), head=head)
                for c in self.CITIES[:n]}

    def stale(self, files):
        return [i for i in self.issues(files) if i[2] == "stale-year"]

    def test_a_template_with_last_years_title_is_one_finding(self):
        found = self.stale(self.section("Best plumbers in {city} %d | Acme" % (YEAR - 2)))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "warning")
        self.assertIn(str(YEAR - 2), found[0][3])
        self.assertIn("6", found[0][3])

    def test_old_publication_date_does_not_hide_a_stale_template(self):
        head = f'<meta property="article:published_time" content="{YEAR - 2}-03-01">'
        found = self.stale(self.section("Plumber prices in {city} %d" % (YEAR - 1), head=head))
        self.assertEqual(len(found), 1)

    def test_one_page_is_not_a_template(self):
        self.assertEqual(self.stale({"index.html": html(title=f"Best plumbers in Boston {YEAR - 2}")}), [])

    def test_years_that_differ_page_to_page_are_the_subject(self):
        files = {f"cars/m{i}/index.html": html(title=f"{YEAR - 1 - i} Honda Civic price and specs",
                                                h1=f"{YEAR - 1 - i} Honda Civic")
                 for i in range(6)}
        self.assertEqual(self.stale(files), [])

    def test_this_year_and_ranges_reaching_it(self):
        for title in ("Best plumbers in {city} %d" % YEAR,
                      "Best plumbers in {city} %d–%d" % (YEAR - 1, YEAR),
                      "Season %d/%s in {city}" % (YEAR - 1, str(YEAR)[2:]),
                      "Plumbing in {city} since %d" % (YEAR - 9)):
            with self.subTest(title=title):
                self.assertEqual(self.stale(self.section(title)), [])

    def test_dated_posts_about_their_own_year(self):
        y = YEAR - 3
        files = {f"blog/p{i}/index.html": html(title=f"Weekly report {y} #{i}", h1=f"Weekly report {y}",
                                               body=f'<time datetime="{y}-0{i + 1}-12">{y}</time>')
                 for i in range(6)}
        self.assertEqual(self.stale(files), [])


class TitleAndHeading(Site):
    def test_a_logo_h1_in_the_header_is_not_the_heading(self):
        page = ("<!doctype html><html lang=\"en\"><head><title>Plumbers in Austin, TX</title>"
                "</head><body><header><h1><a href=\"/\">Acme</a></h1></header><main>"
                f"<h1>Plumbers in Austin</h1><p>{TEXT}</p></main></body></html>")
        self.assertNotIn(("info", "title-h1-mismatch"), self.codes({"index.html": page}))


    def test_title_and_h1_about_different_things(self):
        page = html(title="Emergency electricians in Dallas", h1="Garden furniture sale")
        self.assertIn(("info", "title-h1-mismatch"), self.codes({"index.html": page}))

    def test_an_article_prefix_is_the_same_word(self):
        # visatosingapore.com/ar/guides: «أدلة» и «الأدلة».
        page = html(title="أدلة وأخبار تأشيرات سنغافورة | VisatoSingapore", h1="الأدلة والأخبار")
        self.assertNotIn(("info", "title-h1-mismatch"), self.codes({"index.html": page}))

    def test_brand_and_wording_differences_are_fine(self):
        page = html(title="Austin plumbers — Acme", h1="Plumbers in Austin, TX")
        self.assertNotIn(("info", "title-h1-mismatch"), self.codes({"index.html": page}))


class Previews(Site):
    def test_missing_og_tags(self):
        self.assertIn(("info", "no-og"), self.codes({"index.html": html(og=False)}))
        self.assertNotIn(("info", "no-og"), self.codes({"index.html": html()}))

    def test_relative_og_image(self):
        page = html(og=False, head='<meta property="og:title" content="Plumbers">'
                                   '<meta property="og:image" content="/img/card.png">')
        self.assertIn(("info", "no-og"), self.codes({"index.html": page}))

    def test_thai_words_are_whole(self):
        self.assertEqual(core.tokenize("กรุงเทพมหานคร คือเมืองหลวง"),
                         ["กรุงเทพมหานคร", "คือเมืองหลวง"])

    def test_missing_viewport(self):
        self.assertIn(("warning", "no-viewport"), self.codes({"index.html": html(viewport=False)}))
        self.assertNotIn(("warning", "no-viewport"), self.codes({"index.html": html()}))

    def test_markdown_sources_are_not_judged(self):
        md = "---\ntitle: Plumbers in Austin\n---\n# Plumbers in Austin\n\n" + TEXT
        codes = [c for _, c in self.codes({"index.md": md})]
        self.assertNotIn("no-viewport", codes)
        self.assertNotIn("no-og", codes)


class Weight(Site):
    def test_html_over_two_megabytes(self):
        big = html(body="<p>" + ("padding text " * 180000) + "</p>")
        self.assertGreater(len(big.encode()), 2 * 1024 * 1024)
        self.assertIn(("warning", "heavy-html"), self.codes({"index.html": big}))

    def test_an_ordinary_page_is_light(self):
        self.assertNotIn(("warning", "heavy-html"), self.codes({"index.html": html()}))

    def test_heavy_images_are_one_site_finding(self):
        files = {"index.html": html(body='<img src="/img/a.jpg" alt="a">'),
                 "img/a.jpg": b"\xff\xd8" + b"0" * (1100 * 1024),
                 "img/b.png": b"\x89PNG" + b"0" * (1300 * 1024),
                 "img/small.png": b"\x89PNG" + b"0" * 1000}
        found = [i for i in self.issues(files) if i[2] == "heavy-images"]
        self.assertEqual(len(found), 1)
        self.assertIn("2", found[0][3])
        self.assertIn("b.png", found[0][3])


if __name__ == "__main__":
    unittest.main()
