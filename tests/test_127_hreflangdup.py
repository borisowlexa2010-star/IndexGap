# -*- coding: utf-8 -*-
"""
1.27: hreflang и дубли.

* Явный порт по умолчанию (`:443`) и punycode того же хоста — точный адрес,
  а не «другой».
* Шаблон, который пишет http:// во всех альтернативах при https-canonical,
  виден одной находкой.
* hreflang после первого тега тела — в <body>, даже если самого <body> нет.
* Региональные версии, связанные hreflang, не попадают в duplicate-risk.
"""

import io
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, hreflang

SITE = "https://demo.example"


def run_check(folder, *extra, site=SITE):
    out = os.path.join(folder, "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()):
        cli.main(["check", folder, "--site", site, "--out", out, *extra])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


def write(folder, rel, html):
    path = os.path.join(folder, rel, "index.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


def doc(lang, head="", body="", words="text"):
    return (f'<!doctype html><html lang="{lang}"><head><title>{lang} page</title>{head}'
            f'</head><body><h1>{lang}</h1><p>{words}</p>{body}</body></html>')


def links(en, de):
    return (f'<link rel="alternate" hreflang="en" href="{en}">'
            f'<link rel="alternate" hreflang="de" href="{de}">')


class HreflangAddress(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-127h-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def build(self, host, variant=None, canonical=None):
        for city in ("a", "b", "c"):
            for lang in ("en", "de"):
                en = host + f"/en/{city}/"
                if lang == "de" and city == "a" and variant:
                    en = variant
                head = links(en, host + f"/de/{city}/")
                if canonical:
                    head += f'<link rel="canonical" href="{canonical}/{lang}/{city}/">'
                write(self.dir, f"{lang}/{city}", doc(lang, head))

    def found(self, site=SITE):
        report = run_check(self.dir, "--no-content", site=site)
        return [i for i in report["issues"] if i["code"].startswith("hreflang")]

    def test_default_port_is_the_same_address(self):
        self.build(SITE, variant="https://demo.example:443/en/a/")
        self.assertFalse([i for i in self.found() if i["code"] == "hreflang-no-return"])

    def test_punycode_is_the_same_host(self):
        self.build("https://пример.рф", variant="https://xn--e1afmkfd.xn--p1ai/en/a/")
        self.assertFalse([i for i in self.found("https://пример.рф")
                          if i["code"] == "hreflang-no-return"])

    def test_http_return_link_is_still_reported(self):
        self.build(SITE, variant="http://demo.example/en/a/")
        returns = [i for i in self.found() if i["code"] == "hreflang-no-return"]
        self.assertEqual([i["url"] for i in returns], [SITE + "/en/a/"])

    def test_http_in_every_alternate_against_https_canonical(self):
        self.build("http://demo.example", canonical=SITE)
        returns = [i for i in self.found() if i["code"] == "hreflang-no-return"]
        self.assertEqual([(i["level"], i["url"]) for i in returns], [("critical", "")])
        self.assertIn("http://demo.example", returns[0]["message"])
        self.assertIn(SITE, returns[0]["message"])

    def test_matching_canonical_is_quiet(self):
        self.build(SITE, canonical=SITE)
        self.assertFalse([i for i in self.found() if i["code"] == "hreflang-no-return"])

    def test_relative_canonical_says_nothing_about_the_site(self):
        """Относительный canonical достроен от --site: неверный --site не находка."""
        for city in ("a", "b", "c"):
            for lang in ("en", "de"):
                head = links(SITE + f"/en/{city}/", SITE + f"/de/{city}/")
                head += f'<link rel="canonical" href="/{lang}/{city}/">'
                write(self.dir, f"{lang}/{city}", doc(lang, head))
        self.assertFalse([i for i in self.found("http://demo.example")
                          if i["code"] == "hreflang-no-return"])

    def test_alternates_on_other_domains_are_not_a_wrong_template(self):
        """Ссылки на соседние сайты — не другое написание своего адреса."""
        for city in ("a", "b", "c"):
            head = "".join(f'<link rel="alternate" hreflang="{c}" href="https://demo.{c}/{city}/">'
                           for c in ("de", "fr", "it"))
            head += f'<link rel="alternate" hreflang="en" href="{SITE}/{city}/">'
            head += f'<link rel="canonical" href="{SITE}/{city}/">'
            write(self.dir, city, doc("en", head))
        self.assertFalse([i for i in self.found() if i["level"] == "critical"])


class HreflangWithoutBodyTag(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-127b-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_links_after_content_are_in_body(self):
        for city in ("a", "b"):
            alt = links(SITE + f"/en/{city}/", SITE + f"/de/{city}/")
            write(self.dir, f"en/{city}", doc("en", alt))
            if city == "a":
                html = (f'<!doctype html><html lang="de"><meta charset="utf-8">'
                        f'<title>de page</title><main><nav>{alt}</nav>'
                        f'<h1>de</h1><p>text</p></main></html>')
            else:
                html = doc("de", alt)
            write(self.dir, f"de/{city}", html)
        report = run_check(self.dir, "--no-content")
        found = [i for i in report["issues"] if i["code"].startswith("hreflang")]
        self.assertEqual([i["url"] for i in found if i["code"] == "hreflang-in-body"],
                         [SITE + "/de/a/"])
        self.assertIn(SITE + "/en/a/", [i["url"] for i in found if i["code"] == "hreflang-no-return"])

    def test_head_without_tags_still_counts(self):
        """Опущенные <head> и <body>: ссылки до первого тега тела — в head."""
        alt = links(SITE + "/en/a/", SITE + "/de/a/")
        html = f'<!doctype html><html><meta charset="utf-8"><title>t</title>{alt}<h1>x</h1></html>'
        self.assertEqual(len(hreflang.read_alternates(SimpleNamespace(raw=html))), 2)
        noscript = (f'<html><head><noscript><img src="x.gif"></noscript>{alt}</head>'
                    f'<body><h1>x</h1></body></html>')
        self.assertEqual(len(hreflang.read_alternates(SimpleNamespace(raw=noscript))), 2)
        late = f'<html><title>t</title><div>x</div>{alt}</html>'
        self.assertEqual(hreflang.read_alternates(SimpleNamespace(raw=late)), [])


class RegionalNotDuplicateRisk(unittest.TestCase):
    def test_regional_versions_are_not_a_risk(self):
        folder = tempfile.mkdtemp(prefix="indexgap-127r-")
        self.addCleanup(shutil.rmtree, folder, True)
        vocab = [f"w{i}" for i in range(5000)]
        r = random.Random(7)
        shared = " ".join(r.choice(vocab) for _ in range(400))
        regions = ["en-us", "en-gb", "en-au", "en-ca", "en-ie", "en-nz"]
        alts = "".join(f'<link rel="alternate" hreflang="{g}" href="{SITE}/{g}/rent/berlin/">'
                       for g in regions)
        meta = '<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        for i, g in enumerate(regions):
            pick = random.Random(i)
            own = " ".join(pick.choice(vocab) for _ in range(60))
            write(folder, f"{g}/rent/berlin",
                  f'<!doctype html><html lang="{g}"><head>{meta}'
                  f'<title>Renting in Berlin guide for {g}</title>'
                  f'<meta name="description" content="Renting a flat in Berlin: what it costs '
                  f'and how it works, for readers in {g}.">{alts}</head><body><main>'
                  f'<h1>Renting in Berlin</h1><p>{shared}</p><p>{own}</p>'
                  f'<a href="/">Home</a></main></body></html>')
        home = " ".join(r.choice(vocab) for _ in range(300))
        write(folder, "", f'<!doctype html><html lang="en"><head>{meta}<title>Home of the rent '
              'guide demo</title><meta name="description" content="Home of a demo rental guide '
              f'with links to every regional page in it."></head><body><main><h1>Home</h1><p>{home}</p>'
              + "".join(f'<a href="/{g}/rent/berlin/">{g}</a> ' for g in regions)
              + '</main></body></html>')
        report = run_check(folder)
        codes = [i["code"] for i in report["issues"]]
        # Пары есть, и они региональные: сказано заметкой, а в «похожие пары»
        # они не идут (1.29) — заметка называет их не дублями.
        self.assertTrue(any("не попали в дубли" in n for n in report["notes"]), report["notes"])
        self.assertEqual(report["duplicates"], [])
        self.assertNotIn("duplicate-risk", codes)
        self.assertNotIn("near-duplicate", codes)


if __name__ == "__main__":
    unittest.main()
