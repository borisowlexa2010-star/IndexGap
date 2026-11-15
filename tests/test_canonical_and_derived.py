# -*- coding: utf-8 -*-
"""
1.24: два случая, когда отчёт был зеленее, чем сайт.

* canonical, собранный шаблоном из чужой переменной (`/rent/hamburg/` →
  `/rent/berlin/`), считался «вариантом страницы» — справкой, — и вместе со
  страницей из отчёта пропадали выдуманная цена, сирота и дубль;
* число, которое страница честно посчитала из своей строки ($1,450 × 3 =
  $4,350), было критичной находкой и роняло `--strict` на верной странице.
"""

import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, content, core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


def run_check(folder, dataset):
    out = os.path.join(folder, "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()):
        cli.main(["check", folder, "--site", SITE, "--dataset", dataset, "--out", out])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)["issues"]


class Demo(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="indexgap-124-"), "site")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir), True)
        shutil.copytree(DEMO, self.dir)
        self.dataset = os.path.join(self.dir, "cities.csv")

    def edit(self, slug, change):
        path = os.path.join(self.dir, "rent", slug, "index.html")
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(change(html))

    def slugs(self):
        return sorted(os.listdir(os.path.join(self.dir, "rent")))


class TestCanonicalToASibling(Demo):
    def point_all_at_berlin(self):
        tag = f'<link rel="canonical" href="{SITE}/rent/berlin/">'
        for slug in self.slugs():
            if slug != "berlin" and os.path.isdir(os.path.join(self.dir, "rent", slug)):
                self.edit(slug, lambda h: h.replace("</head>", tag + "</head>", 1))

    def test_a_template_canonical_is_critical_not_a_note(self):
        self.point_all_at_berlin()
        found = [i for i in run_check(self.dir, self.dataset) if i["code"] == "canonical-elsewhere"]
        self.assertTrue(found)
        self.assertEqual({i["level"] for i in found}, {"critical"})
        self.assertIn("ещё", found[0]["message"])

    def test_the_other_findings_of_such_pages_stay(self):
        """Выдуманная цена на странице с ошибочным canonical не пропадает."""
        before = {i["code"] for i in run_check(self.dir, self.dataset)}
        self.point_all_at_berlin()
        after = {i["code"] for i in run_check(self.dir, self.dataset)}
        self.assertIn("unsupported-number", before)
        self.assertIn("unsupported-number", after)
        self.assertIn("orphan", after)

    def page_at(self, source, url, canonical):
        twin = copy.copy(source)
        twin.url, twin.canonical = url, canonical
        return twin

    def test_a_print_copy_is_still_a_variant(self):
        pages, _ = core.load_pages(self.dir, SITE)
        berlin = next(p for p in pages if p.url.endswith("/rent/berlin/"))
        hamburg = next(p for p in pages if p.url.endswith("/rent/hamburg/"))
        printed = self.page_at(hamburg, berlin.url + "print/", berlin.url)
        self.assertTrue(checks._a_variant_of(printed, berlin))
        self.assertEqual(checks.misdirected([berlin, printed]), {})

    def test_the_same_name_in_another_version_is_a_variant(self):
        pages, _ = core.load_pages(self.dir, SITE)
        berlin = next(p for p in pages if p.url.endswith("/rent/berlin/"))
        hamburg = next(p for p in pages if p.url.endswith("/rent/hamburg/"))
        old = self.page_at(hamburg, SITE + "/v1/rent/berlin/", berlin.url)
        self.assertTrue(checks._a_variant_of(old, berlin))

    def test_the_same_text_at_another_name_is_a_variant(self):
        pages, _ = core.load_pages(self.dir, SITE)
        berlin = next(p for p in pages if p.url.endswith("/rent/berlin/"))
        second = self.page_at(berlin, SITE + "/rent/berlin-old/", berlin.url)
        self.assertTrue(checks._a_variant_of(second, berlin))

    def test_one_unrelated_canonical_is_a_warning(self):
        tag = f'<link rel="canonical" href="{SITE}/rent/berlin/">'
        other = next(s for s in self.slugs() if s not in ("berlin", "cologne")
                     and os.path.isdir(os.path.join(self.dir, "rent", s)))
        self.edit(other, lambda h: h.replace("</head>", tag + "</head>", 1))
        found = [i for i in run_check(self.dir, self.dataset)
                 if i["code"] == "canonical-elsewhere" and i["url"].endswith(f"/{other}/")]
        self.assertEqual([i["level"] for i in found], ["warning"])


class TestComputedFromTheRow(Demo):
    def add(self, sentence):
        self.edit("berlin", lambda h: h.replace("34 minutes.", "34 minutes. " + sentence, 1))

    def berlin(self):
        return {i["code"]: i for i in run_check(self.dir, self.dataset)
                if i["url"].endswith("/rent/berlin/")}

    def test_a_product_of_two_row_numbers_is_for_the_eye(self):
        self.add("Three months of rent upfront comes to $4,350.")
        found = self.berlin()
        self.assertNotIn("unsupported-number", found)
        self.assertIn("$4350", found["check-by-eye"]["message"])
        self.assertIn("1450", found["check-by-eye"]["message"])

    def test_an_invented_number_next_to_it_stays_critical(self):
        self.add("Three months of rent upfront comes to $4,350. A made-up fee is $777.")
        found = self.berlin()
        self.assertIn("$777", found["unsupported-number"]["message"])
        self.assertNotIn("4350", found["unsupported-number"]["message"])

    def test_derivations(self):
        self.assertEqual(content._derivation("4350", {"1450", "3"}), "3 × 1450")
        self.assertEqual(content._derivation("1305", {"1450", "10"}), "1450 − 10%")
        self.assertEqual(content._derivation("145", {"1450", "10"}), "10% × 1450")

    def test_what_is_never_forgiven(self):
        self.assertEqual(content._derivation("12", {"3", "4"}), "", "too small to tell")
        self.assertEqual(content._derivation("1453", {"1450", "3"}), "", "sums are not read")
        many = {str(n) for n in range(101, 101 + content.DERIVED_MAX_INPUTS + 1)}
        self.assertEqual(content._derivation(str(101 * 102), many), "", "row too long")


if __name__ == "__main__":
    unittest.main()
