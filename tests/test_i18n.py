# -*- coding: utf-8 -*-
"""
Английский вывод.

Здесь не проверяются формулировки — их проверяют русские тесты. Здесь
проверяется свойство, которое человеку важнее любой отдельной фразы:
**в английском режиме не остаётся русского текста**. Наполовину переведённый
отчёт хуже честно русского: он выглядит сломанным.

Ловушка, ради которой файл и написан: кодмод, размечавший строки, обернул
заодно языковые ДАННЫЕ — стоп-слова, окончания, счётные обороты, подсказки
заголовков в выгрузках. Их перевод молча сломал бы проверки русских сайтов:
стоп-слова нужны русскому тексту независимо от того, на каком языке напечатан
отчёт. Поэтому ниже отдельно закреплено, что эти списки остались русскими.
"""

import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexgap import cli, i18n, settings, generate, sources
from indexgap.locale import en

CYRILLIC = re.compile(r"[А-Яа-яЁё]")
SITE = "https://example.com"


def english():
    os.environ["INDEXGAP_LANG"] = "en"
    i18n.set_lang("en")


def russian():
    os.environ["INDEXGAP_LANG"] = "ru"
    i18n.set_lang("ru")


class TestCatalogue(unittest.TestCase):
    def tearDown(self):
        russian()

    def test_every_marked_string_has_an_english_translation(self):
        """
        Ключи собираются из исходников, а не из списка: список устаревает молча.
        """
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent / "indexgap"
        keys = set()
        for path in sorted(root.glob("*.py")):
            for m in re.finditer(r'tr\("((?:[^"\\]|\\.)*)"',
                                 path.read_text(encoding="utf-8")):
                keys.add(eval('"' + m.group(1) + '"'))
        missing = sorted(k for k in keys if k not in en.MESSAGES)
        self.assertEqual(missing, [], f"без перевода осталось {len(missing)}")

    def test_the_catalogue_has_no_leftovers(self):
        """Ключ, которого больше нет в коде, — мусор: его никто не увидит."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent / "indexgap"
        source = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
        stale = [k for k in en.MESSAGES
                 if 'tr("' + k.replace("\\", "\\\\").replace('"', '\\"')
                 .replace("\n", "\\n").replace("\t", "\\t") + '"' not in source]
        self.assertEqual(stale, [])

    def test_translations_keep_their_placeholders(self):
        """
        Потерянная подстановка — это отчёт без числа. Лишняя — KeyError
        на ровном месте. И то и другое видно только в бою, если не проверить.
        """
        holder = re.compile(r"\{(a\d+|[a-z_]+)[^}]*\}")
        for source, target in en.MESSAGES.items():
            self.assertEqual(sorted(set(holder.findall(source))),
                             sorted(set(holder.findall(target))),
                             f"подстановки разошлись: {source[:60]!r}")

    def test_no_translation_is_left_in_russian(self):
        for source, target in en.MESSAGES.items():
            self.assertFalse(CYRILLIC.search(target),
                             f"перевод остался русским: {source[:60]!r}")


class TestLanguageChoice(unittest.TestCase):
    def tearDown(self):
        russian()

    def test_flag_wins_over_environment(self):
        os.environ["INDEXGAP_LANG"] = "ru"
        self.assertEqual(cli.preset_language(["check", "--lang", "en"]), "en")
        self.assertEqual(cli.preset_language(["--lang=ru", "check"]), "ru")

    def test_environment_is_used_when_there_is_no_flag(self):
        os.environ["INDEXGAP_LANG"] = "ru"
        self.assertEqual(cli.preset_language(["check"]), "ru")

    def test_unknown_locale_falls_back_to_english(self):
        for value in ("fr_FR.UTF-8", "de", "pt_BR"):
            os.environ["INDEXGAP_LANG"] = value
            self.assertEqual(i18n.set_lang(), "en", value)

    def test_post_soviet_locales_get_russian(self):
        """Своих переводов для них нет, и русский им ближе английского."""
        for value in ("uk_UA.UTF-8", "kk", "uz_UZ"):
            os.environ["INDEXGAP_LANG"] = value
            self.assertEqual(i18n.set_lang(), "ru", value)

    def test_a_missing_key_falls_back_to_russian_instead_of_crashing(self):
        english()
        self.assertEqual(i18n.tr("такой строки в словаре нет"),
                         "такой строки в словаре нет")

    def test_a_broken_template_in_the_catalogue_does_not_crash(self):
        english()
        with mock.patch.dict(i18n._catalog, {"{a0} страниц": "pages {nope}"}):
            self.assertIn("7", i18n.tr("{a0} страниц", a0=7))


class TestNothingRussianLeaks(unittest.TestCase):
    """Полный прогон на английском: в выводе не должно остаться кириллицы."""

    def setUp(self):
        english()
        self.dir = tempfile.mkdtemp(prefix="indexgap-en-")
        for i in range(9):
            path = os.path.join(self.dir, "content", f"p{i}", "index.md")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"---\ntitle: Visa guide for country {i} in 2026\n"
                         f"description: {'a detailed description of the page ' * 4}\n"
                         f"---\n\n# Visa {i}\n\n"
                         + "shared wording " * 200 + f" country{i}\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        russian()

    def run_cli(self, argv):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            code = cli.main(argv)
        return code, out.getvalue()

    def assertNoRussian(self, text, where):
        found = CYRILLIC.findall(text)
        self.assertEqual(found, [], f"{where}: в английском выводе кириллица "
                                    f"— {text[:400]!r}")

    def test_check_prints_english_only(self):
        code, out = self.run_cli(
            ["check", os.path.join(self.dir, "content"), "--site", SITE,
             "--lang", "en", "--out", os.path.join(self.dir, "r.html")])
        self.assertEqual(code, 0)
        self.assertNoRussian(out, "check")

    def test_the_html_report_is_english_only(self):
        path = os.path.join(self.dir, "r.html")
        self.run_cli(["check", os.path.join(self.dir, "content"), "--site", SITE,
                      "--lang", "en", "--out", path])
        html = open(path, encoding="utf-8").read()
        self.assertNoRussian(html, "html")
        self.assertIn('lang="en"', html)

    def test_profiles_command_is_english_only(self):
        code, out = self.run_cli(["profiles", "--lang", "en"])
        self.assertEqual(code, 0)
        self.assertNoRussian(out, "profiles")

    def test_help_is_english_only(self):
        cli.preset_language(["--lang", "en"])
        parser = cli.build_parser()
        self.assertNoRussian(parser.format_help(), "help")
        for name, sub in parser._subparsers_map.items():
            self.assertNoRussian(sub.format_help(), f"help {name}")

    def test_an_error_is_english_only(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            code = cli.main(["check", os.path.join(self.dir, "nope"),
                             "--site", SITE, "--lang", "en"])
        self.assertEqual(code, 2)
        self.assertNoRussian(err.getvalue(), "error")

    def test_doctor_is_english_only(self):
        sitemap = os.path.join(self.dir, "sitemap.xml")
        with open(sitemap, "w", encoding="utf-8") as fh:
            fh.write("<urlset>" + "".join(
                f"<url><loc>{SITE}/p{i}/</loc></url>" for i in range(9)) + "</urlset>")
        indexed = os.path.join(self.dir, "gsc-pages.csv")
        with open(indexed, "w", encoding="utf-8") as fh:
            fh.write("Top pages,Clicks\n" + f"{SITE}/p1/,3\n")
        code, out = self.run_cli(
            ["doctor", os.path.join(self.dir, "content"), "--site", SITE,
             "--lang", "en", "--sitemap", sitemap, "--indexed", indexed,
             "--out", os.path.join(self.dir, "d.html")])
        self.assertEqual(code, 0)
        self.assertNoRussian(out, "doctor")
        self.assertNoRussian(open(os.path.join(self.dir, "d.html"),
                                  encoding="utf-8").read(), "doctor html")

    def test_sitemap_and_notify_are_english_only(self):
        out_dir = os.path.join(self.dir, "public")
        code, out = self.run_cli(
            ["sitemap", os.path.join(self.dir, "content"), "--site", SITE,
             "--lang", "en", "--out-dir", out_dir])
        self.assertEqual(code, 0)
        self.assertNoRussian(out, "sitemap")
        code, out = self.run_cli(
            ["notify", os.path.join(self.dir, "content"), "--site", SITE,
             "--lang", "en", "--key", "a" * 32, "--offline"])
        self.assertEqual(code, 0)
        self.assertNoRussian(out, "notify")

    def test_init_installs_the_english_skills(self):
        """Скилл на чужом языке агент прочитает, но человек — нет."""
        from indexgap import install
        english()
        result = install.run(self.dir)
        text = open(os.path.join(self.dir, result["skills"][0]),
                    encoding="utf-8").read()
        self.assertNotRegex(text, CYRILLIC.pattern)

    def test_init_installs_the_russian_skills_in_russian(self):
        from indexgap import install
        russian()
        result = install.run(self.dir, force=True)
        joined = "\n".join(open(os.path.join(self.dir, rel), encoding="utf-8").read()
                            for rel in result["skills"])
        self.assertRegex(joined, CYRILLIC.pattern)

    def test_plan_is_english_only(self):
        path = os.path.join(self.dir, "k.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("keyword,city\nvisa to singapore,SG\nsingapore visa,SG\n")
        code, out = self.run_cli(["plan", path, "--lang", "en"])
        self.assertEqual(code, 0)
        self.assertNoRussian(out, "plan")


class TestLanguageDataStaysRussian(unittest.TestCase):
    """
    Стоп-слова, окончания и подсказки заголовков — это данные о русском языке
    и о русских выгрузках. Перевести их значит сломать проверки русских сайтов
    для тех, кто читает отчёт по-английски. Такую поломку не видно в выводе,
    поэтому она закреплена тестом.
    """

    def setUp(self):
        english()

    def tearDown(self):
        russian()

    def test_stopwords_are_still_russian(self):
        for word in ("и", "или", "для", "при"):
            self.assertIn(word, generate.STOPWORDS)

    def test_counting_words_after_a_number_are_still_russian(self):
        """Без этого списка «работаем с 2010 года» становилось выдуманным фактом."""
        for word in ("года", "году", "гг"):
            self.assertIn(word, settings.NOT_A_UNIT)

    def test_vague_anchor_list_is_still_russian(self):
        anchors = settings.PROJECT_DEFAULTS["vague_anchors"]
        self.assertIn("здесь", anchors)
        self.assertIn("подробнее", anchors)
        # И английские никуда не делись: список покрывает оба языка сразу.
        self.assertIn("read more", anchors)

    def test_export_header_hints_are_still_russian(self):
        self.assertIn("адрес", sources.URL_COLUMN_HINTS)
        self.assertIn("запрос", sources.KEYWORD_COLUMN_HINTS)

    def test_intent_matching_still_works_for_russian_in_english_mode(self):
        """Главная проверка: смысл `plan` не зависит от языка отчёта."""
        rows = [{"keyword": "отели сочи"}, {"keyword": "сочи отели"}]
        audit = generate.audit_dataset(rows, ["keyword"], "keyword")
        self.assertEqual(len(audit["keep"]), 1, "одинаковый интент не схлопнулся")


if __name__ == "__main__":
    unittest.main(verbosity=2)
