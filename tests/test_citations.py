# -*- coding: utf-8 -*-
"""
Цитирование в ИИ-ответах: выгрузка Bing Webmaster Tools → AI Performance.

Формат снят с живого кабинета, а не придуман: два экспорта, оба CSV с
кавычками вокруг каждого поля и концом строки `\\r\\n`.

    Pages:            "Page","Citations"
    Grounding Query:  "Grounding Query","Intent","Topic","Citations","Citation Share"

Главное, что здесь закреплено, — цитирование не вливается в шаг «в индексе».
Bing отдаёт выборку: на живом каталоге виз это 93 страницы из тысячи с лишним
проиндексированных. Слитые в индекс, они объявили бы непроиндексированным всё
остальное — самый дорогой вид уверенной неправды. Цитирование — отдельный шаг
после индекса, и молчание в нём ничего не доказывает.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import core, doctor, sources

SITE = "https://example.com"

PAGES_CSV = ('"Page","Citations"\r\n'
             f'"{SITE}/en/a","120"\r\n'
             f'"{SITE}/en/b/","30"\r\n'
             f'"{SITE}/en/closed","7"\r\n')

QUERIES_CSV = ('"Grounding Query","Intent","Topic","Citations","Citation Share"\r\n'
               '"form 14a","Informational","Visas & Entry Requirements","764","24.49%"\r\n')


def page(title, head=""):
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            f'<meta name="description" content="{"описание страницы " * 6}">{head}'
            f'</head><body><main><h1>{title}</h1><p>{"Текст " * 80}</p></main></body></html>')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-cite-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def site(self):
        root = os.path.join(self.dir, "site")
        for rel, text in {
            "en/a/index.html": page("A"),
            "en/b/index.html": page("B"),
            "en/c/index.html": page("C"),
            "en/closed/index.html": page("Closed", '<meta name="robots" content="noindex">'),
        }.items():
            self.write(os.path.join("site", rel), text)
        pages, _ = core.load_pages(root, SITE)
        return pages


class TestRecognition(Fixture):
    def test_the_pages_export_is_recognised_by_its_header(self):
        path = self.write("export.csv", PAGES_CSV)
        name, kind, confident = sources.identify(path, doctor.read_indexed_header(path))
        self.assertEqual((name, kind), ("copilot", sources.CITATION))
        self.assertTrue(confident)

    def test_and_by_the_name_bing_gives_it(self):
        path = self.write("AIPerformance_Pages.csv", PAGES_CSV)
        name, kind, _ = sources.identify(path, doctor.read_indexed_header(path))
        self.assertEqual(kind, sources.CITATION)

    def test_the_queries_export_is_refused_with_a_way_out(self):
        """В выгрузке запросов нет адресов. Молча прочитать её как пустой список
        страниц — значит сказать «ничего не цитируется»."""
        path = self.write("queries.csv", QUERIES_CSV)
        with self.assertRaises(core.SourceError) as caught:
            doctor.read_citations(path, SITE)
        self.assertIn("Pages", str(caught.exception))


class TestCounts(Fixture):
    def test_counts_are_kept_per_page(self):
        cited = doctor.read_citations(self.write("p.csv", PAGES_CSV), SITE)
        by_key = {core.url_key(u): n for u, n in cited.items()}
        self.assertEqual(by_key[core.url_key(SITE + "/en/a/")], 120)
        # хвостовой слэш в выгрузке — та же страница
        self.assertEqual(by_key[core.url_key(SITE + "/en/b")], 30)


class TestFunnel(Fixture):
    def run_funnel(self, index):
        pages = self.site()
        cited = doctor.read_citations(self.write("p.csv", PAGES_CSV), SITE)
        return doctor.funnel(pages, by_engine={"google": index} if index else None,
                             cited={"copilot": cited})

    def test_citations_do_not_shrink_the_index_step(self):
        result = self.run_funnel([SITE + "/en/a/", SITE + "/en/b/", SITE + "/en/c/"])
        step = next(s for s in result["steps"] if s["name"].strip().startswith(
            ("Хотя бы", "Известно", "Есть хотя")))
        self.assertEqual(step["count"], 3)

    def test_citation_is_its_own_step_after_the_index(self):
        result = self.run_funnel([SITE + "/en/a/", SITE + "/en/b/", SITE + "/en/c/"])
        names = [s["name"] for s in result["steps"]]
        cited = [s for s in result["steps"] if s.get("kind") == sources.CITATION]
        self.assertEqual(len(cited), 1, names)
        self.assertEqual(cited[0]["count"], 2)          # a и b; closed не пригодна
        self.assertGreater(names.index(cited[0]["name"]),
                           max(i for i, s in enumerate(result["steps"])
                               if s.get("kind") != sources.CITATION))

    def test_a_cited_page_you_closed_is_named(self):
        """ИИ продолжает цитировать страницу, которую сайт закрыл от индекса.
        Для закрытого по политике платёжной системы это вопрос не трафика."""
        result = self.run_funnel([SITE + "/en/a/"])
        closed = [core.url_key(u) for u in result["cited_closed"]]
        self.assertEqual(closed, [core.url_key(SITE + "/en/closed/")])

    def test_a_cited_page_missing_from_the_sitemap_is_counted_and_named(self):
        """ИИ нашёл и использует страницу, которой нет в sitemap. Отбросить её
        из шага — значит спрятать ровно то, о чём стоит знать."""
        pages = self.site()
        cited = doctor.read_citations(self.write("p.csv", PAGES_CSV), SITE)
        result = doctor.funnel(pages, sitemap_urls=[SITE + "/en/a/"],
                               cited={"copilot": cited})
        step = next(s for s in result["steps"] if s.get("kind") == sources.CITATION)
        self.assertEqual(step["count"], 2)                # a и b, а не только a
        missing = [core.url_key(u) for u in result["cited_not_in_sitemap"]]
        self.assertEqual(missing, [core.url_key(SITE + "/en/b/")])

    def test_a_redirect_stub_is_not_reported_as_missing_from_the_sitemap(self):
        """Корень-заглушку ИИ цитирует охотно: люди ссылаются на домен. Но
        редиректу в sitemap не место, и первым пунктом списка он только сбивал."""
        stub = ('<!doctype html><html><head><title>x</title></head><body><script>'
                'self.__next_f.push([1,"NEXT_REDIRECT;replace;/en/a;307;"])</script></body></html>')
        self.write("site/index.html", stub)
        pages = self.site()
        csv = PAGES_CSV + f'"{SITE}/","91"\r\n'
        cited = doctor.read_citations(self.write("p.csv", csv), SITE)
        result = doctor.funnel(pages, sitemap_urls=[SITE + "/en/a/"],
                               cited={"copilot": cited})
        missing = [core.url_key(u) for u in result["cited_not_in_sitemap"]]
        self.assertNotIn(core.url_key(SITE + "/"), missing)

    def test_the_citation_step_reports_no_loss(self):
        """Отсутствие цитирований — не потеря: данные выборка. Слово «потеряно»
        рядом с оговоркой «ничего не доказывает» противоречило бы ей."""
        result = self.run_funnel([SITE + "/en/a/", SITE + "/en/b/", SITE + "/en/c/"])
        step = next(s for s in result["steps"] if s.get("kind") == sources.CITATION)
        self.assertFalse(step.get("lost"))

    def test_without_a_panel_citation_still_says_only_what_it_proves(self):
        result = self.run_funnel(None)
        self.assertFalse(result["has_index"])
        self.assertTrue(any(s.get("kind") == sources.CITATION for s in result["steps"]))


if __name__ == "__main__":
    unittest.main()
