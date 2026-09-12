# -*- coding: utf-8 -*-
"""Дубли в индексе: noindex и canonical-алиасы не конкурируют с основной страницей.

Технические находки остаются видимыми: фильтр сравнения не объявляет ошибочный
canonical или случайный noindex правильными. Независимые страницы стран и
похожие переводы без оговорённого регионального исключения проверяются как раньше.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import language  # noqa: F401 — фиксирует язык диагностик
from indexgap import checks, core, publish

SITE = "https://example.com"
BODY = " ".join(f"evidence{i}" for i in range(320))


class TestDuplicateIndexability(unittest.TestCase):
    def pages(self, specs):
        with tempfile.TemporaryDirectory(prefix="indexgap-duplicate-indexability-") as root:
            for path, lang, robots, canonical, alternates in specs:
                file = Path(root) / path.strip("/") / "index.html"
                file.parent.mkdir(parents=True, exist_ok=True)
                links = f'<link rel="canonical" href="{canonical}">' if canonical else ""
                links += "".join(f'<link rel="alternate" hreflang="{code}" href="{SITE}{url}">'
                                 for code, url in alternates)
                file.write_text(
                    f'<html lang="{lang}"><head><title>Singapore visa documents</title>'
                    '<meta name="description" content="The same checklist and official submission details.">'
                    f'<meta name="robots" content="{robots}">{links}</head>'
                    f'<body><main><h1>Singapore visa documents</h1><p>{BODY}</p></main></body></html>',
                    encoding="utf-8")
            return core.load_pages(root, SITE)[0]

    def codes(self, pages):
        return [issue[2] for issue in checks.run_all(pages, SITE + "/")["issues"]]

    def test_noindex_and_none_do_not_create_duplicate_findings(self):
        for robots in ("noindex, follow", "none"):
            with self.subTest(robots=robots):
                pages = self.pages([("/primary/", "en", "index, follow", "/primary/", []),
                                    ("/private/", "en", robots, "", [])])
                codes = self.codes(pages)
                self.assertIn("noindex", codes)
                for code in ("duplicate-title", "duplicate-description", "near-duplicate"):
                    self.assertNotIn(code, codes)
                self.assertEqual(checks.find_near_duplicates(pages)["pairs"], [])

    def test_canonical_alias_is_excluded_but_canonical_finding_remains(self):
        pages = self.pages([("/primary/", "en", "", "/primary/", []),
                            ("/alias/", "en", "", "/primary/", [])])
        result = checks.run_all(pages, SITE + "/")
        codes = [issue[2] for issue in result["issues"]]
        self.assertIn("canonical-elsewhere", codes)
        for code in ("duplicate-title", "duplicate-description", "near-duplicate"):
            self.assertNotIn(code, codes)
        self.assertEqual(result["duplicates"], [])
        self.assertTrue(any("1" in note and "noindex" in note and "canonical" in note
                            for note in result["notes"]))

    def test_indexable_country_pages_still_report_real_duplicates(self):
        pages = self.pages([("/en/visa/india/", "en", "", "/en/visa/india/", []),
                            ("/en/visa/pakistan/", "en", "", "/en/visa/pakistan/", []),
                            ("/private-copy/", "en", "noindex", "", [])])
        result = checks.run_all(pages, SITE + "/")
        for code in ("duplicate-title", "duplicate-description", "near-duplicate"):
            hits = [issue for issue in result["issues"] if issue[2] == code]
            self.assertEqual(len(hits), 2, code)
            self.assertTrue(all("/en/visa/" in hit[1] for hit in hits))
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0][2], 1.0)

    def test_relative_self_canonical_is_not_filtered(self):
        pages = self.pages([("/a/", "en", "", "/a/", []),
                            ("/b/", "en", "", "/b/", [])])
        self.assertTrue(all(publish.indexable(page) for page in pages))
        self.assertEqual(len(checks.find_near_duplicates(pages)["pairs"]), 1)
        self.assertEqual(self.codes(pages).count("duplicate-title"), 2)

    def test_existing_draft_indexability_policy_is_used(self):
        pages = self.pages([("/a/", "en", "", "", []),
                            ("/draft/", "en", "", "", [])])
        next(page for page in pages if page.url.endswith("/draft/")).meta["status"] = "draft"
        self.assertFalse(publish.indexable(pages[1]))
        self.assertEqual(checks.find_near_duplicates(pages)["pairs"], [])
        self.assertNotIn("duplicate-title", self.codes(pages))

    def test_language_alternates_do_not_silently_exempt_matching_content(self):
        alternates = [("id", "/id/"), ("ms", "/ms/")]
        pages = self.pages([("/id/", "id", "", "/id/", alternates),
                            ("/ms/", "ms", "", "/ms/", alternates)])
        codes = self.codes(pages)
        self.assertEqual(codes.count("duplicate-title"), 2)
        self.assertEqual(codes.count("near-duplicate"), 2)

    def test_existing_regional_hreflang_exception_is_unchanged(self):
        alternates = [("en-US", "/en-us/"), ("en-GB", "/en-gb/")]
        pages = self.pages([("/en-us/", "en-US", "", "/en-us/", alternates),
                            ("/en-gb/", "en-GB", "", "/en-gb/", alternates)])
        self.assertNotIn("near-duplicate", self.codes(pages))


if __name__ == "__main__":
    unittest.main(verbosity=2)
