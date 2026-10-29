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
    def test_a_past_year_in_a_freshness_title(self):
        page = html(title=f"Best plumbers in Austin {YEAR - 2}", h1=f"Best plumbers {YEAR - 2}")
        self.assertIn(("warning", "stale-year"), self.codes({"index.html": page}))

    def test_this_year_is_fine(self):
        page = html(title=f"Best plumbers in Austin {YEAR}", h1="Best plumbers")
        self.assertNotIn(("warning", "stale-year"), self.codes({"index.html": page}))

    def test_a_dated_post_from_that_year_is_history(self):
        page = html(title=f"Weekly report {YEAR - 3}", h1=f"Weekly report {YEAR - 3}",
                    head=f'<meta property="article:published_time" content="{YEAR - 3}-05-12">')
        self.assertNotIn(("warning", "stale-year"), self.codes({"index.html": page}))

    def test_a_blog_post_about_a_past_year_is_history(self):
        # apisix: «firsthand experience … from OSPP 2020 students», опубликовано в 2021.
        page = html(title=f"Firsthand experience from OSPP {YEAR - 5} students",
                    h1=f"Experience from OSPP {YEAR - 5}",
                    head=f'<meta property="article:published_time" content="{YEAR - 4}-06-03">')
        self.assertNotIn(("warning", "stale-year"), self.codes({"index.html": page}))
        files = {f"events/{YEAR - 3}-meetups/index.html": html(title=f"Meetups in {YEAR - 3}",
                                                               h1=f"Meetups {YEAR - 3}")}
        self.assertNotIn(("warning", "stale-year"), self.codes(files))

    def test_a_year_that_is_a_name_not_a_date(self):
        for title in ("Windows 2000 drivers archive", "Plumbing since 1998",
                      "The 1990s in Austin"):
            with self.subTest(title=title):
                self.assertNotIn(("warning", "stale-year"),
                                 self.codes({"index.html": html(title=title, h1=title)}))


class TitleAndHeading(Site):
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
