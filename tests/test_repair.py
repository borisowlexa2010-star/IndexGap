# -*- coding: utf-8 -*-
"""
Наряды на починку.

Отчёт отвечает на вопрос «что со мной не так». Наряд — на вопрос «что мне
сделать». Между ними на живом каталоге из 2 970 страниц разница в две тысячи
строк, и вся она — в трёх правилах раскладки, которые здесь и закрепляются:

  * свойство шаблона — один наряд, а не три тысячи;
  * дубли чинятся группой: наряд на одну страницу из группы бесполезен,
    в одиночку её не починить;
  * свойства сайта живут отдельно от страниц.

И главное обещание, ради которого команда вообще написана так, а не иначе:
**пакет не пишет текст**. Он формулирует задачу и перечисляет данные, из
которых её решают. Если бы числа на страницу подставлял сам пакет, главная
его проверка — сверка чисел со строкой датасета — проверяла бы себя саму
и всегда была бы зелёной.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import cli, core, repair
from indexgap.core import SourceError

SITE = "https://example.com"


def html(title, body, description="описание страницы для проверки длины " * 3):
    return (f'<!doctype html><html lang="ru"><head><title>{title}</title>'
            f'<meta name="description" content="{description}">'
            f'</head><body><main><h1>{title}</h1><p>{body}</p>'
            f'<a href="/">Главная</a></main></body></html>')


class Fixture(unittest.TestCase):
    def pages(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-repair-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        loaded, _ = core.load_pages(root, SITE)
        self.root = root
        return loaded

    def outdir(self):
        out = tempfile.mkdtemp(prefix="indexgap-briefs-")
        self.addCleanup(shutil.rmtree, out, True)
        return out

    def kinds(self, briefs):
        return sorted(b["kind"] for b in briefs)

    def named(self, briefs, name):
        for brief in briefs:
            if brief["name"] == name:
                return brief
        self.fail(f"нет наряда {name}: есть {[b['name'] for b in briefs]}")


# ── раскладка ─────────────────────────────────────────────────────────────────

class TestPlacement(Fixture):
    def test_a_template_wide_finding_becomes_one_brief_not_three_thousand(self):
        """
        На живом каталоге `no-question-headings` сработал на 2 919 страницах
        из 2 970. Наряд на каждую — это 2 919 заданий переписать один шаблон.
        """
        pages = self.pages({f"p{i}/index.html": html(f"Стр {i}", "текст " * 50)
                            for i in range(5)})
        issues = [("info", p.url, "no-question-headings", "нет вопросов")
                  for p in pages]
        notes = ["`no-question-headings` — на 5 страницах из 5 (100%)"]
        briefs = repair.build(pages, {"issues": issues}, template_notes=notes)

        self.assertEqual(self.kinds(briefs), ["template"])
        body = self.named(briefs, "_template.md")["body"]
        self.assertIn("no-question-headings", body)
        self.assertIn("подзаголовков как вопросы", body)

    def test_a_page_keeps_its_own_findings_when_the_template_is_also_broken(self):
        """Свой дефект страницы не должен исчезать вместе с дефектом шаблона."""
        pages = self.pages({f"p{i}/index.html": html(f"Стр {i}", "текст " * 50)
                            for i in range(3)})
        issues = ([("info", p.url, "no-question-headings", "нет вопросов")
                   for p in pages]
                  + [("critical", pages[0].url, "orphan", "нет входящих ссылок")])
        briefs = repair.build(pages, {"issues": issues},
                              template_notes=["`no-question-headings` — на 3 из 3"])
        page_briefs = [b for b in briefs if b["kind"] == "page"]
        self.assertEqual(len(page_briefs), 1)
        self.assertIn("orphan", page_briefs[0]["body"])
        # …но повтор находки шаблона в персональный наряд не просачивается.
        self.assertNotIn("no-question-headings", page_briefs[0]["body"])

    def test_duplicates_get_one_brief_per_group_not_per_page(self):
        """
        588 почти-дублей живого каталога — это 72 группы. Наряд выписывается
        на группу: одну страницу из группы починить нельзя в принципе.
        """
        pages = self.pages({f"p{i}/index.html": html("Виза", "текст " * 50)
                            for i in range(4)})
        by_url = {p.url: p for p in pages}
        near = [(by_url[pages[0].url], by_url[pages[1].url], 0.95),
                (by_url[pages[1].url], by_url[pages[2].url], 0.93)]
        issues = [("warning", pages[0].url, "near-duplicate", "почти дубль")]
        briefs = repair.build(pages, {"issues": issues, "duplicates": near})

        groups = [b for b in briefs if b["kind"] == "group"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 3)          # p0, p1, p2 — один кластер
        self.assertNotIn("page", self.kinds(briefs))

    def test_the_group_brief_forbids_linking_the_duplicates_to_each_other(self):
        """Совет «свяжи их ссылками» превращает дубли в кластер дублей."""
        pages = self.pages({f"p{i}/index.html": html("Виза", "текст " * 50)
                            for i in range(2)})
        briefs = repair.build(pages, {"issues": [], "duplicates":
                                      [(pages[0], pages[1], 0.99)]})
        self.assertIn("Связывать их ссылками между собой нельзя",
                      briefs[0]["body"])

    def test_site_level_findings_do_not_land_on_pages(self):
        pages = self.pages({"p/index.html": html("Стр", "текст " * 50)})
        issues = [("critical", "", "robots-blocks-all", "сайт закрыт"),
                  ("warning", "", "ai-crawler-blocked", "GPTBot закрыт")]
        briefs = repair.build(pages, {"issues": issues})
        self.assertEqual(self.kinds(briefs), ["site"])
        self.assertEqual(self.named(briefs, "_site.md")["count"], 2)

    def test_a_weak_similarity_does_not_make_a_group(self):
        """Порог группы — тот же, по которому выписана находка."""
        pages = self.pages({f"p{i}/index.html": html("Виза", "текст " * 50)
                            for i in range(2)})
        briefs = repair.build(pages, {"issues": [], "duplicates":
                                      [(pages[0], pages[1], 0.5)]})
        self.assertEqual(briefs, [])


# ── содержание наряда ─────────────────────────────────────────────────────────

class TestWhatTheBriefSays(Fixture):
    def brief_for(self, code, message="что-то не так", **kw):
        pages = self.pages({"p/index.html": html("Стр", "текст " * 50)})
        briefs = repair.build(pages, {"issues": [("critical", pages[0].url,
                                                  code, message)]}, **kw)
        return self.named(briefs, "p.md")

    def test_every_finding_carries_an_imperative_what_to_do(self):
        """
        Описание кода объясняет, что случилось. Наряд обязан сказать,
        что с этим сделать, — иначе это тот же отчёт другими словами.
        """
        for code in sorted(repair.FIX):
            self.assertTrue(repair._fix(code).strip(), code)

    def test_the_dataset_row_is_quoted_as_the_only_source_of_numbers(self):
        """
        Ради этого абзаца команда и написана без генерации: числа берутся
        из строки данных, а не выдумываются тем, кто пишет текст.
        """
        pages = self.pages({"p/index.html": html("Стр", "текст " * 50)})
        rows = {pages[0].url: {"keyword": "виза в сингапур",
                               "срок": "30 дней", "пусто": "  "}}
        briefs = repair.build(pages, {"issues": [
            ("critical", pages[0].url, "unsupported-number", "числа 45 нет")]},
            rows_by_key=rows)
        body = self.named(briefs, "p.md")["body"]
        self.assertIn("срок: 30 дней", body)
        self.assertIn("единственный источник чисел", body)
        self.assertNotIn("пусто", body)           # пустые колонки — шум

    def test_without_a_dataset_it_does_not_demand_checking_numbers_against_it(self):
        """Непроверяемое требование хуже отсутствующего."""
        body = self.brief_for("thin")["body"]
        self.assertNotIn("нет в строке датасета", body)

    def test_the_thresholds_are_the_ones_the_finding_was_written_by(self):
        """
        «Почини до 250 слов» там, где проверка требует 400, — это наряд,
        который не закроется никогда.
        """
        body = self.brief_for("thin", cfg={"thin_words": 400})["body"]
        self.assertIn("400", body)
        self.assertNotIn("250", body)

    def test_the_file_path_is_relative_to_the_project(self):
        pages = self.pages({"deep/p/index.html": html("Стр", "текст " * 50)})
        briefs = repair.build(pages, {"issues": [
            ("critical", pages[0].url, "orphan", "нет ссылок")]}, root=self.root)
        self.assertIn("Файл: `deep/p/index.html`", briefs[0]["body"])
        self.assertNotIn(self.root, briefs[0]["body"])

    def test_an_unknown_code_still_gets_a_brief(self):
        """
        Новый код проверки не должен молча выпадать из нарядов: находка
        без «что делать» — всё ещё находка, которую надо увидеть.
        """
        brief = self.brief_for("совершенно-новый-код", "новая находка")
        self.assertIn("новая находка", brief["body"])


# ── раскладка по файлам ───────────────────────────────────────────────────────

class TestWriting(Fixture):
    def make(self, count):
        pages = self.pages({f"p{i}/index.html": html(f"Стр {i}", "текст " * 50)
                            for i in range(count)})
        levels = ["info", "warning", "critical"]
        issues = [(levels[i % 3], p.url, "no-h1", "нет H1")
                  for i, p in enumerate(pages)]
        return repair.build(pages, {"issues": issues})

    def test_the_limit_keeps_the_heaviest(self):
        """
        892 наряда — это не список задач, это второй отчёт. Предел режет
        по тяжести, а не по алфавиту, иначе первым чинят info.
        """
        briefs = self.make(9)
        out = self.outdir()
        result = repair.write(briefs, out, limit=3)
        self.assertEqual(len(result["written"]), 3)
        self.assertEqual(result["skipped"], 6)
        for name in result["written"]:
            with open(os.path.join(out, name), encoding="utf-8") as fh:
                self.assertIn("critical", fh.read())

    def test_shared_briefs_are_never_cut_by_the_limit(self):
        """Наряд на шаблон — самый ценный: он один заменяет тысячи."""
        pages = self.pages({f"p{i}/index.html": html(f"Стр {i}", "текст " * 50)
                            for i in range(3)})
        issues = [("critical", p.url, "no-h1", "нет H1") for p in pages]
        briefs = repair.build(pages, {"issues": issues},
                              template_notes=["`no-title` — на 3 из 3"])
        out = self.outdir()
        result = repair.write(briefs, out, limit=1)
        self.assertIn("_template.md", result["written"])
        self.assertEqual(len(result["written"]), 2)

    def test_a_brief_is_a_report_and_gets_overwritten(self):
        """
        Правки человека живут в страницах. Если бы наряды дописывались,
        второй прогон складывал бы устаревшие задания поверх новых.
        """
        out = self.outdir()
        repair.write(self.make(1), out, limit=0)
        path = os.path.join(out, "p0.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\nя тут поработал\n")
        repair.write(self.make(1), out, limit=0)
        with open(path, encoding="utf-8") as fh:
            self.assertNotIn("я тут поработал", fh.read())

    def test_the_file_says_it_is_generated(self):
        out = self.outdir()
        repair.write(self.make(1), out, limit=0)
        with open(os.path.join(out, "p0.md"), encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith(repair.HEADER))

    def test_no_directory_is_an_explained_error(self):
        with self.assertRaises(SourceError):
            repair.write(self.make(1), "", limit=0)


# ── команда ───────────────────────────────────────────────────────────────────

class TestCommand(Fixture):
    def run_cli(self, argv):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            code = cli.main(argv)
        return code, out.getvalue()

    def site(self):
        root = self.pages({f"p{i}/index.html": html(f"Стр {i}", "текст " * 50)
                           for i in range(3)}) and self.root
        return root

    def test_a_dry_run_writes_nothing(self):
        """
        Как и `notify`, и `cite`: команда, создающая файлы, по умолчанию
        показывает, что сделает, и не делает.
        """
        root, out = self.site(), self.outdir()
        code, printed = self.run_cli(["brief", root, "--site", SITE,
                                      "--out-dir", out, "--lang", "ru"])
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(out), [])
        self.assertIn("пробный прогон", printed)

    def test_write_lays_the_briefs_out(self):
        root, out = self.site(), self.outdir()
        code, printed = self.run_cli(["brief", root, "--site", SITE,
                                      "--out-dir", out, "--write", "--lang", "ru"])
        self.assertEqual(code, 0)
        self.assertTrue(os.listdir(out))
        self.assertIn("Записано", printed)

    def test_the_briefs_repeat_the_findings_of_check(self):
        """
        Наряды выписываются по тем же находкам, что попадают в отчёт.
        Считай их `brief` сам — он бы со временем разошёлся с `check`.
        """
        root, out = self.site(), self.outdir()
        self.run_cli(["brief", root, "--site", SITE, "--out-dir", out,
                      "--write", "--limit", "0", "--lang", "ru"])
        written = []
        for base, _dirs, files in os.walk(out):
            written += [os.path.join(base, f) for f in files]
        text = "".join(open(p, encoding="utf-8").read() for p in written)

        report_dir = self.outdir()
        self.run_cli(["check", root, "--site", SITE, "--lang", "ru",
                      "--out", os.path.join(report_dir, "r.html")])
        import json
        with open(os.path.join(report_dir, "r.json"), encoding="utf-8") as fh:
            issues = json.load(fh)["issues"]
        for issue in issues:
            self.assertIn(issue["code"], text, issue["code"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
