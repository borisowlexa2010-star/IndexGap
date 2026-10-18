# -*- coding: utf-8 -*-
"""
Наряд для проекта-генератора: чинят источник, а не собранный файл.

Ревьюер прошёл весь цикл агентом на проекте, где `generate.py` стирает и
заново пишет `out/`. Наряды указывали `Файл: plumbing/dallas/index.html` —
путь от каталога страниц, которого из корня проекта не существует, — и ни
словом не говорили, что файл собранный: правка в нём живёт до следующей
сборки. Команда проверки в конце наряда теряла `--dataset`, и выдуманные
числа «исчезали». Групповой наряд советовал склеить canonical'ом
двадцать четыре настоящие городские страницы из разных строк датасета.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, repair

SITE = "https://example.com"


def html(title, body, lang="ru"):
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title>'
            f'<meta name="description" content="Описание страницы {title} для проверки длины '
            f'описания в выдаче поисковика"></head><body><main><h1>{title}</h1><p>{body}</p>'
            f'<a href="/">Главная</a></main></body></html>')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp(prefix="indexgap-gen-project-")
        self.addCleanup(shutil.rmtree, self.project, True)
        self.cwd = os.getcwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, self.cwd)

    def write(self, rel, text):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def pages(self):
        return core.load_pages(os.path.join(self.project, "out"), SITE)[0]


class PageBriefs(Fixture):
    def brief(self, **kw):
        self.write("out/index.html", html("Главная", "текст " * 300))
        self.write("out/plumbing/dallas/index.html", html("Сантехник в Далласе", "коротко"))
        pages = self.pages()
        issues = [("warning", SITE + "/plumbing/dallas/", "thin", "мало текста")]
        briefs = repair.build(pages, {"issues": issues, "duplicates": []},
                              root=os.path.join(self.project, "out"), **kw)
        return next(b for b in briefs if b["kind"] == "page")["body"]

    def test_the_file_path_is_from_the_project_root(self):
        self.assertIn("`out/plumbing/dallas/index.html`", self.brief())

    def test_a_built_file_says_to_fix_the_source(self):
        body = self.brief()
        self.assertIn("собранный файл", body)
        self.assertIn("пересобери", body)

    def test_the_verify_command_is_the_one_that_found_it(self):
        body = self.brief(verify="indexgap check out --site https://example.com "
                                 "--dataset data/pages.csv")
        self.assertIn("--dataset data/pages.csv", body)

    def test_thin_never_advises_closing_the_page(self):
        body = self.brief()
        self.assertNotIn("убери из индекса", body)
        self.assertIn("checks.thin_words", body)

    def test_an_unmatched_page_is_told_its_numbers_were_not_checked(self):
        body = self.brief(rows_by_key={SITE + "/other/": {"keyword": "x"}})
        self.assertIn("не сопоставлена", body)
        self.assertNotIn("ни одного числа, которого нет в строке датасета", body)


class GroupBriefs(Fixture):
    def group(self, rows=None, langs=("ru", "ru")):
        self.write("out/index.html", html("Главная", "текст " * 300))
        for name, lang in zip(("austin", "dallas"), langs):
            self.write(f"out/plumbing/{name}/index.html",
                       html(f"Сантехник {name}", "одинаковый текст шаблона " * 60, lang))
        pages = {p.url: p for p in self.pages()}
        a, b = pages[SITE + "/plumbing/austin/"], pages[SITE + "/plumbing/dallas/"]
        briefs = repair.build(list(pages.values()), {"issues": [], "duplicates": [(a, b, 0.96)]},
                              rows_by_key=rows, root=os.path.join(self.project, "out"))
        return next(x for x in briefs if x["kind"] == "group")["body"]

    def test_pages_from_different_rows_are_never_canonicalised_together(self):
        body = self.group(rows={SITE + "/plumbing/austin/": {"city": "Austin"},
                                SITE + "/plumbing/dallas/": {"city": "Dallas"}})
        self.assertIn("разных строк", body)
        self.assertNotIn("поставь canonical", body)

    def test_the_group_shows_how_alike_each_page_is(self):
        self.assertIn("96%", self.group())

    def test_sibling_links_are_kept(self):
        body = self.group()
        self.assertNotIn("Связывать их ссылками между собой нельзя", body)

    def test_language_versions_are_a_missing_translation(self):
        body = self.group(langs=("ru", "de"))
        self.assertIn("перевод", body)
        self.assertNotIn("поставь canonical", body)


class Cli(Fixture):
    def test_brief_writes_the_full_check_command(self):
        self.write("out/index.html", html("Главная", "текст " * 300))
        self.write("out/a/index.html", html("Страница А", "коротко"))
        self.write("data/pages.csv", "keyword,price\nстраница а,100\n")
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["brief", "out", "--site", SITE, "--dataset", "data/pages.csv",
                             "--write", "--out-dir", "briefs"])
        self.assertEqual(code, 0)
        text = open(os.path.join(self.project, "briefs", "a.md"), encoding="utf-8").read()
        self.assertIn("indexgap check out --site https://example.com/ --dataset data/pages.csv",
                      text)


if __name__ == "__main__":
    unittest.main()
