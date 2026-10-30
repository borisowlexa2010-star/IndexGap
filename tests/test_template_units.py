# -*- coding: utf-8 -*-
"""
Шаблон как единица.

Правило «чинить один раз в шаблоне» раньше требовало, чтобы находка стояла
на 90% *всех* страниц. На программном сайте шаблонов несколько: 170 страниц
`/plumbing/<город>/` живут рядом с 30 записями блога. Дефект городского
шаблона покрывает 85% сайта и 100% своего шаблона — и сворачиваться должен
по шаблону, а не по сайту. При этом запись блога с той же находкой — своя
беда страницы и в наряд шаблона не уходит.
"""

import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import checks, core, repair

SITE = "https://example.com"
CITIES = [f"city{i}" for i in range(170)]
POSTS = [f"post{i}" for i in range(30)]


def fake_pages():
    return ([SimpleNamespace(url=f"{SITE}/plumbing/{c}/", lang="en") for c in CITIES]
            + [SimpleNamespace(url=f"{SITE}/blog/{p}/", lang="en") for p in POSTS])


class Clusters(unittest.TestCase):
    def test_a_defect_of_one_template_is_one_note(self):
        pages = fake_pages()
        issues = [("info", f"{SITE}/plumbing/{c}/", "no-question-headings", "x")
                  for c in CITIES]
        notes = checks.template_wide(issues, len(pages), pages=pages)
        self.assertEqual(len(notes), 1)
        self.assertIn("no-question-headings", notes[0])
        self.assertIn("/plumbing/*/", notes[0])
        self.assertEqual(len(notes[0].urls), 170)

    def test_scattered_findings_are_not_a_template(self):
        pages = fake_pages()
        issues = [("info", f"{SITE}/plumbing/{c}/", "no-question-headings", "x")
                  for c in CITIES[:100]]
        self.assertEqual(checks.template_wide(issues, len(pages), pages=pages), [])

    def test_a_small_group_is_not_a_template(self):
        pages = ([SimpleNamespace(url=f"{SITE}/tools/t{i}/", lang="") for i in range(10)]
                 + [SimpleNamespace(url=f"{SITE}/p{i}/", lang="") for i in range(30)])
        issues = [("info", f"{SITE}/tools/t{i}/", "no-faq", "x") for i in range(10)]
        self.assertEqual(checks.template_wide(issues, len(pages), pages=pages), [])

    def test_site_wide_is_said_once(self):
        pages = fake_pages()
        issues = [("info", p.url, "vague-anchor", "x") for p in pages]
        notes = checks.template_wide(issues, len(pages), pages=pages)
        self.assertEqual(len(notes), 1)
        self.assertNotIn("/*/", notes[0])


def html(title):
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            '<meta name="description" content="a description long enough for the check">'
            f'</head><body><main><h1>{title}</h1><p>{"word " * 60}</p>'
            '<a href="/">Home</a></main></body></html>')


class Briefs(unittest.TestCase):
    def test_only_the_template_pages_are_collapsed(self):
        root = tempfile.mkdtemp(prefix="indexgap-units-")
        self.addCleanup(shutil.rmtree, root, True)
        files = {f"plumbing/{c}/index.html": html(f"Plumbers {c}") for c in CITIES[:25]}
        files.update({f"blog/{p}/index.html": html(f"Post {p}") for p in POSTS[:5]})
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        pages, _ = core.load_pages(root, SITE)
        issues = [("info", p.url, "no-question-headings", "нет вопросов")
                  for p in pages if "/plumbing/" in p.url]
        blog = next(p.url for p in pages if "/blog/" in p.url)
        issues.append(("info", blog, "no-question-headings", "нет вопросов"))
        notes = checks.template_wide(issues, len(pages), pages=pages)
        self.assertEqual(len(notes), 1)
        briefs = repair.build(pages, {"issues": issues}, template_notes=notes)
        kinds = sorted(b["kind"] for b in briefs)
        self.assertEqual(kinds, ["page", "template"])
        page = next(b for b in briefs if b["kind"] == "page")
        self.assertIn("no-question-headings", page["body"])


if __name__ == "__main__":
    unittest.main()
