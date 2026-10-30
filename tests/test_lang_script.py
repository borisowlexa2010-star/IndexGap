# -*- coding: utf-8 -*-
"""
`lang` против письма текста.

На прогоне по корпусу китайские страницы xitu объявляли `<html lang="en">`,
а корейский блог — `en-US`. Поисковик и экранный диктор доверяют `lang`;
hreflang и языковые пороги пакета тоже держатся за него. Когда текст почти
целиком написан другим письмом, `lang` врёт — и об этом говорится.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core, signals

SITE = "https://example.com"
ZH = "这个页面介绍如何在项目中使用组件，以及常见问题的解决方法。我们会一步一步说明配置过程。" * 6
KO = "이 글에서는 프로젝트에서 컴포넌트를 사용하는 방법과 자주 묻는 질문을 설명합니다. " * 6
JA = "このページでは、プロジェクトでコンポーネントを使う方法と、よくある質問を説明します。" * 6
RU = "На этой странице рассказано, как подключить компонент к проекту и что делать с ошибками. " * 4
EN = "This page explains how to add the component to a project and what to do about errors. " * 4


def html(text, lang="en", head="", main_extra="", nav=""):
    attr = f' lang="{lang}"' if lang is not None else ""
    return (f"<!doctype html><html{attr}><head><title>Страница</title>{head}</head><body>"
            f"<nav>{nav}</nav><main><h1>Заголовок</h1><p>{text}</p>{main_extra}</main>"
            "</body></html>")


class LangScript(unittest.TestCase):
    def pages(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-lang-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return core.load_pages(root, SITE)[0]

    def found(self, text, **kw):
        pages = self.pages({"index.html": html(text, **kw)})
        return [i for i in signals.lang_script(pages) if i[2] == "lang-script-mismatch"]

    def test_chinese_text_declared_english(self):
        found = self.found(ZH, lang="en")
        self.assertEqual(len(found), 1)
        level, url, _, message = found[0]
        self.assertEqual((level, url), ("warning", SITE + "/"))
        self.assertIn("«en»", message)
        self.assertIn("иероглиф", message)

    def test_korean_text_declared_en_us(self):
        found = self.found(KO, lang="en-US")
        self.assertEqual(len(found), 1)
        self.assertIn("«en-US»", found[0][3])
        self.assertIn("хангыль", found[0][3])

    def test_cyrillic_text_declared_english(self):
        self.assertEqual(len(self.found(RU, lang="en")), 1)
        self.assertEqual(len(self.found(EN, lang="ru")), 1)

    def test_matching_lang_is_silent(self):
        self.assertEqual(self.found(ZH, lang="zh-CN"), [])
        self.assertEqual(self.found(KO, lang="ko"), [])
        self.assertEqual(self.found(JA, lang="ja"), [])
        self.assertEqual(self.found(RU, lang="ru"), [])
        self.assertEqual(self.found(EN, lang="en_GB"), [])

    def test_no_lang_is_not_judged(self):
        self.assertEqual(self.found(ZH, lang=None), [])
        self.assertEqual(self.found(ZH, lang=""), [])

    def test_a_language_with_two_scripts_is_not_judged(self):
        # Сербский пишут и кириллицей, и латиницей.
        self.assertEqual(self.found(EN, lang="sr"), [])
        self.assertEqual(self.found(RU, lang="sr"), [])
        # Явный подтег письма решает сам.
        self.assertEqual(len(self.found(RU, lang="sr-Latn")), 1)
        self.assertEqual(self.found(RU, lang="sr-Cyrl"), [])

    def test_bilingual_page_is_silent(self):
        self.assertEqual(self.found(RU + " " + EN, lang="en"), [])
        self.assertEqual(self.found(ZH[:120] + " " + EN, lang="en"), [])
        # Две половины подряд: длинный китайский текст, за ним английский.
        self.assertEqual(self.found(ZH * 20 + " " + EN * 20, lang="en"), [])
        self.assertEqual(len(self.found(ZH * 20, lang="en")), 1)

    def test_short_text_is_silent(self):
        self.assertEqual(self.found("这个页面介绍组件。", lang="en"), [])

    def test_code_samples_and_menu_do_not_count(self):
        code = "<pre><code>" + "const value = await fetchComponentList(options);\n" * 40 + "</code></pre>"
        menu = "".join(f'<a href="/p{i}/">Getting started with the component guide {i}</a>'
                       for i in range(40))
        self.assertEqual(self.found(RU, lang="ru", main_extra=code, nav=menu), [])
        self.assertEqual(self.found(ZH, lang="zh", main_extra=code, nav=menu), [])
        # Английский текст рядом с кодом на странице lang="zh" — не повод:
        # без прозы абзацами становится сам код.
        self.assertEqual(self.found("", lang="zh", main_extra=code), [])

    def test_reported_through_run_all_and_collapsible_as_template(self):
        files = {f"p{i}/index.html": html(ZH + str(i), lang="en") for i in range(3)}
        pages = self.pages(files)
        issues = checks.run_all(pages, SITE + "/")["issues"]
        self.assertEqual(sum(1 for i in issues if i[2] == "lang-script-mismatch"), 3)
        self.assertNotIn("lang-script-mismatch", checks.NOT_TEMPLATE_WIDE)
        self.assertIn("lang-script-mismatch", checks.CODE_WEIGHT)


if __name__ == "__main__":
    unittest.main()
