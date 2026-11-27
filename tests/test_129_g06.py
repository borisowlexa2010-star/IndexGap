# -*- coding: utf-8 -*-
"""
1.29 (g06): hreflang рядом с canonical, noindex, редиректами и запаркованными
переводами; определение языка текста.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, langid, signals

SITE = "https://demo.example"


def alt(pairs):
    return "".join('<link rel="alternate" hreflang="%s" href="%s">' % p for p in pairs)


def doc(lang, head="", words=None, body=""):
    words = words or ("%s слова про город " % lang) * 40
    lang_attr = ' lang="%s"' % lang if lang else ""
    return ('<!doctype html><html%s><head><meta charset="utf-8"><title>Страница %s %s</title>'
            '<meta name="description" content="Описание %s">%s</head>'
            '<body><main><h1>Заголовок</h1><p>%s</p>%s</main></body></html>'
            % (lang_attr, lang, abs(hash(head)) % 9999, abs(hash(head)) % 99999, head, words, body))


class Base(unittest.TestCase):
    def setUp(self):
        self.top = tempfile.mkdtemp(prefix="indexgap-129-g06-")
        self.addCleanup(shutil.rmtree, self.top, True)

    def site(self, name, pages):
        root = os.path.join(self.top, name)
        for rel, html in pages.items():
            path = os.path.join(root, rel, "index.html")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
        return root

    def run_check(self, root, *extra):
        out = os.path.join(self.top, os.path.basename(root) + ".json")
        code = 0
        with mock.patch.object(sys, "stdout", io.StringIO()):
            try:
                code = cli.main(["check", root, "--site", SITE, "--out", out,
                                 "--no-content", "--no-aeo", *extra]) or 0
            except SystemExit as exc:
                code = exc.code or 0
        with open(out, encoding="utf-8") as fh:
            return json.load(fh), code

    def issues(self, root, *extra, prefix="hreflang"):
        data, _ = self.run_check(root, *extra)
        return [i for i in data["issues"] if i["code"].startswith(prefix)
                and i["code"] != "hreflang-unknown-target"]


class CanonicalConflict(Base):
    def pages(self, x_first=True, lang=True):
        pages = {}
        for c in "abc":
            en, de = "%s/en/%s/" % (SITE, c), "%s/de/%s/" % (SITE, c)
            pairs = [("en", en), ("de", de)]
            pairs = [("x-default", en)] + pairs if x_first else pairs + [("x-default", en)]
            head = alt(pairs) + '<link rel="canonical" href="%s">' % en
            pages["en/" + c] = doc("en" if lang else "", head, ("english %s words " % c) * 80)
            pages["de/" + c] = doc("de" if lang else "", head, ("deutsch %s wörter " % c) * 80)
        return pages

    def test_x_default_first_still_conflicts(self):
        found = self.issues(self.site("xfirst", self.pages(x_first=True)))
        self.assertEqual(3, sum(i["code"] == "hreflang-canonical-conflict" for i in found))

    def test_without_html_lang_uses_hreflang_codes(self):
        found = self.issues(self.site("nolang", self.pages(x_first=False, lang=False)))
        self.assertEqual(3, sum(i["code"] == "hreflang-canonical-conflict" for i in found))


class ExactAddress(Base):
    def test_sister_domain_does_not_become_site_address(self):
        pages = {}
        for c in "abc":
            us, gb = "%s/us/%s/" % (SITE, c), "%s/gb/%s/" % (SITE, c)
            head = alt([("en-US", us), ("en-GB", gb)] + [
                (l, "https://demo.eu/%s/%s/" % (l, c)) for l in ("de", "fr", "it")])
            pages["us/" + c] = doc("en", head + '<link rel="canonical" href="%s">' % us,
                                   ("american %s dollars " % c) * 60)
            pages["gb/" + c] = doc("en", head + '<link rel="canonical" href="%s">' % gb,
                                   ("british %s pounds " % c) * 60)
        found = self.issues(self.site("sister", pages))
        self.assertEqual([], [i for i in found if i["code"] == "hreflang-no-return"])

    def test_majority_http_without_canonical_does_not_flag_https(self):
        pages = {}
        for i, c in enumerate("abcde"):
            host = "http://demo.example" if i < 3 else SITE
            head = alt([("en", "%s/en/%s/" % (host, c)), ("de", "%s/de/%s/" % (host, c))])
            pages["en/" + c] = doc("en", head, ("english %s words " % c) * 80)
            pages["de/" + c] = doc("de", head, ("deutsch %s wörter " % c) * 80)
        found = self.issues(self.site("mixed", pages))
        flagged = [i for i in found if i["code"] == "hreflang-no-return"]
        self.assertFalse([i for i in flagged if "/d/" in i["url"] or "/e/" in i["url"]], flagged)

    def test_self_link_on_redirect_variant(self):
        pages = {}
        for c in "abcd":
            en, de = "%s/en/%s/" % (SITE, c), "%s/de/%s/" % (SITE, c)
            mine = {"a": "http://demo.example/en/a/", "b": "https://www.demo.example/en/b/"}.get(c, en)
            pages["en/" + c] = doc("en", alt([("en", mine), ("de", de)])
                                   + '<link rel="canonical" href="%s">' % en, ("english %s " % c) * 80)
            pages["de/" + c] = doc("de", alt([("en", en), ("de", de)])
                                   + '<link rel="canonical" href="%s">' % de, ("deutsch %s " % c) * 80)
        found = self.issues(self.site("selfvariant", pages))
        self.assertEqual(["%s/en/a/" % SITE, "%s/en/b/" % SITE],
                         sorted(i["url"] for i in found if i["code"] == "hreflang-no-self"))

    def test_slash_and_index_variants_in_return_link(self):
        variants = {"a": SITE + "/en/a", "b": SITE + "/en/b/index.html"}
        pages = {}
        for c in "abcd":
            en, de = "%s/en/%s/" % (SITE, c), "%s/de/%s/" % (SITE, c)
            pages["en/" + c] = doc("en", alt([("en", en), ("de", de)])
                                   + '<link rel="canonical" href="%s">' % en, ("english %s " % c) * 80)
            pages["de/" + c] = doc("de", alt([("en", variants.get(c, en)), ("de", de)])
                                   + '<link rel="canonical" href="%s">' % de, ("deutsch %s " % c) * 80)
        found = self.issues(self.site("slash", pages))
        self.assertEqual(["%s/en/a/" % SITE, "%s/en/b/" % SITE],
                         sorted(i["url"] for i in found if i["code"] == "hreflang-no-return"))

    def test_consistent_site_is_silent(self):
        pages = {}
        for c in "abc":
            en, de = "%s/en/%s/" % (SITE, c), "%s/de/%s/" % (SITE, c)
            head = alt([("en", en), ("de", de), ("x-default", en)])
            pages["en/" + c] = doc("en", head + '<link rel="canonical" href="%s">' % en, ("english %s " % c) * 80)
            pages["de/" + c] = doc("de", head + '<link rel="canonical" href="%s">' % de, ("deutsch %s " % c) * 80)
        self.assertEqual([], self.issues(self.site("ok", pages)))


class RelativeHrefs(Base):
    def pages(self, prefix):
        pages = {}
        for c in "abc":
            head = alt([("en", "%s/en/%s/" % (prefix, c)), ("de", "%s/de/%s/" % (prefix, c))])
            pages["en/" + c] = doc("en", head + '<link rel="canonical" href="%s/en/%s/">' % (SITE, c),
                                   ("english %s " % c) * 80)
            pages["de/" + c] = doc("de", head + '<link rel="canonical" href="%s/de/%s/">' % (SITE, c),
                                   ("deutsch %s " % c) * 80)
        return pages

    def test_relative_hrefs_named_not_misread(self):
        found = self.issues(self.site("relative", self.pages("")))
        self.assertEqual({"hreflang-bad-code"}, {i["code"] for i in found})
        self.assertEqual(6, len(found))

    def test_protocol_relative_named(self):
        found = self.issues(self.site("protocol", self.pages("//demo.example")))
        self.assertEqual(6, sum(i["code"] == "hreflang-bad-code" for i in found))

    def test_one_http_among_relative_is_not_template_wide(self):
        pages = self.pages("")
        pages["de/a"] = doc("de", alt([("en", "http://demo.example/en/a/"), ("de", "/de/a/")])
                            + '<link rel="canonical" href="%s/de/a/">' % SITE, "deutsch a " * 80)
        found = self.issues(self.site("onehttp", pages))
        self.assertFalse([i for i in found if i["code"] == "hreflang-no-return" and not i["url"]])
        self.assertEqual(["%s/en/a/" % SITE],
                         [i["url"] for i in found if i["code"] == "hreflang-no-return"])


class InBodyWithSitemap(Base):
    def test_sitemap_cluster_silences_body_links(self):
        pages = {}
        sm = ['<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/'
              'schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
        for c in "abc":
            en, de = "%s/en/%s/" % (SITE, c), "%s/de/%s/" % (SITE, c)
            for l, u in (("en", en), ("de", de)):
                pages["%s/%s" % (l, c)] = doc(l, '<link rel="canonical" href="%s">' % u,
                                              ("%s %s " % (l, c)) * 80,
                                              body=alt([("en", en), ("de", de)]))
                sm.append('<url><loc>%s</loc><xhtml:link rel="alternate" hreflang="en" href="%s"/>'
                          '<xhtml:link rel="alternate" hreflang="de" href="%s"/></url>' % (u, en, de))
        sm.append("</urlset>")
        root = self.site("sitemap", pages)
        path = os.path.join(self.top, "sitemap.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(sm))
        self.assertEqual([], [i for i in self.issues(root, "--sitemap", path)
                              if i["code"] == "hreflang-in-body"])
        # Без sitemap связей нет — находка остаётся.
        self.assertTrue([i for i in self.issues(root) if i["code"] == "hreflang-in-body"])


class ParkedBaseline(Base):
    def pages(self, parked):
        pages = {}
        for c in "abcdef":
            urls = {l: "%s/%s/%s/" % (SITE, l, c) for l in ("en", "de", "fr")}
            head = alt(list(urls.items()))
            for l, u in urls.items():
                if l in parked:
                    extra = ('<meta name="robots" content="noindex">'
                             '<link rel="canonical" href="%s">' % urls["en"])
                else:
                    extra = '<link rel="canonical" href="%s">' % u
                pages["%s/%s" % (l, c)] = doc(l, head + extra, ("%s %s слова " % (l, c)) * 60)
        return pages

    def test_new_parked_language_is_new(self):
        before = self.site("before", self.pages({"de"}))
        base = os.path.join(self.top, "base.json")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["check", before, "--site", SITE, "--out", base, "--no-content", "--no-aeo"])
        data, _ = self.run_check(before, "--baseline", base, "--strict")
        self.assertEqual([], data["baseline"]["new"])
        after = self.site("after", self.pages({"de", "fr"}))
        data, code = self.run_check(after, "--baseline", base, "--strict")
        self.assertIn("translations-parked", [i["code"] for i in data["baseline"]["new"]])
        self.assertNotEqual(0, code)


def lang_issues(html):
    root = tempfile.mkdtemp(prefix="indexgap-129-lang-")
    try:
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        pages, _ = core.load_pages(root, "https://example.com")
        return [i[2] for i in signals.lang_script(pages)]
    finally:
        shutil.rmtree(root, True)


def page(lang, body, head=""):
    return ('<!doctype html><html lang="%s"><head><title>Page</title>%s</head>'
            '<body><main><h1>T</h1>%s</main></body></html>' % (lang, head, body))


EN = ("<p>This page explains how to apply for the visa, which documents are needed and "
      "how long the review takes for most travellers who apply online. </p>") * 4
DE = ("Diese Seite erklärt, wie man das Visum beantragt, welche Unterlagen man braucht "
      "und wie lange die Prüfung für die meisten Reisenden dauert. ") * 4


class LanguageDetection(unittest.TestCase):
    def test_model_names_are_not_czech(self):
        items = ["Example Book Pro 14 M3 Pro Gray", "Sample Tab Pro 13 Silver",
                 "Demo Phone 15 Pro Max Titanium", "Model Book Pro 360",
                 "Neutral Slate Pro 11 Platinum"] * 4
        body = "<ul>" + "".join("<li>%s</li>" % i for i in items) + "</ul>"
        for lang in ("en", "de", "fr", "pl"):
            self.assertEqual([], lang_issues(page(lang, body)), lang)

    def test_place_names_are_not_spanish(self):
        cities = ("Los Angeles, East Los Angeles, Las Vegas, La Mesa, El Cajon, Del Mar, "
                  "La Jolla, San Diego, Santa Fe, El Paso, Los Gatos, Las Cruces, La Puente, "
                  "El Monte, Los Altos, La Habra, El Segundo, La Verne, Los Banos, Las Lomas")
        body = ("<p>Looking for a licensed plumber nearby? Our team handles leaks, water "
                "heaters and drain cleaning across the county, with same-day visits.</p>"
                "<p>%s.</p><p>Call us for a free estimate.</p>" % cities)
        self.assertEqual([], lang_issues(page("en", body)))

    def test_foreign_titles_in_translated_shop(self):
        titles = ["The Art of War", "The Lord of the Flies", "The Catcher in the Rye",
                  "Of Mice and Men", "The Grapes of Wrath", "The Picture of Dorian Gray",
                  "The Call of the Wild", "The Wind in the Willows", "The Name of the Wind",
                  "The Way of Kings", "The Fault in Our Stars", "The Power of Now"]
        items = "<ul>" + "".join("<li>%s — 12,90 €</li>" % t for t in titles) + "</ul>"
        fr = ("<p>Découvrez notre sélection de livres en anglais pour progresser dans la "
              "langue de Shakespeare. Livraison gratuite dès 30 euros.</p>")
        de = ("<p>Entdecken Sie unsere Auswahl englischer Bücher, um Ihre Sprachkenntnisse "
              "zu verbessern. Kostenloser Versand ab 30 Euro.</p>")
        self.assertEqual([], lang_issues(page("fr", fr + items)))
        self.assertEqual([], lang_issues(page("de", de + items)))

    def test_untranslated_body_still_found(self):
        self.assertEqual(["lang-text-mismatch"], lang_issues(page("de", EN)))
        self.assertEqual("en", langid.mismatch("de", "\n".join([EN.replace("<p>", "").replace("</p>", "")])))

    def test_unseen_code_does_not_silence(self):
        template = ('<script type="text/x-template" id="t"><pre><code>'
                    + "function renderWidget(options) { return template(options); }\n" * 10
                    + "</code></pre></script>")
        comment = "<!-- <pre>" + "debug output line for developers only\n" * 20 + "</pre> -->"
        hidden = "<div hidden><pre>" + "lorem ipsum dolor sit amet consectetur\n" * 20 + "</pre></div>"
        self.assertEqual(["lang-text-mismatch"], lang_issues(page("de", EN + template)))
        self.assertEqual(["lang-script-mismatch"], lang_issues(page("ru", EN + comment)))
        self.assertEqual(["lang-script-mismatch"], lang_issues(page("ru", EN + hidden)))

    def test_visible_code_still_counts(self):
        code = "<pre><code>" + "function renderWidget(options) { return template(options); }\n" * 10 + "</code></pre>"
        self.assertEqual([], lang_issues(page("de", EN + code)))

    def test_element_lang_is_respected(self):
        self.assertEqual([], lang_issues(
            '<!doctype html><html lang="en"><head><title>x</title></head><body>'
            '<main lang="de"><h1>T</h1><p>%s</p></main></body></html>' % DE))
        self.assertEqual([], lang_issues(
            '<!doctype html><html lang="de"><head><title>x</title></head><body><main>'
            '<p>Kurz.</p><div lang="en">%s</div></main></body></html>' % EN))


if __name__ == "__main__":
    unittest.main()
