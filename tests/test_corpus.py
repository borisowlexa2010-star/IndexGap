# -*- coding: utf-8 -*-
"""
Чужие сайты: то, что нашёл прогон по двенадцати открытым проектам.

До этого пакет видел три сайта своего автора и примеры, составленные под
известные находки. Здесь — собранные сайты из веток `gh-pages`: mdBook и just
(mdBook), MkDocs и httpx (MkDocs), Zola, Jekyll, Immer (Docusaurus), Gin
(Astro Starlight), NetworkX (Sphinx), руководства по стилю Google (исходники
Jekyll). Падений не было ни одного. Ложных видов находок — пять, и каждый
повторялся бы на любом сайте того же генератора.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

SITE = "https://example.com"
TEXT = "<p>" + "слово " * 150 + "</p>"


def html(title, body=TEXT, head="", lang="ru", links=()):
    anchors = "".join(f'<a href="{h}">ссылка</a>' for h in links)
    return (f'<!doctype html><html lang="{lang}"><head><title>{title} — страница сайта</title>'
            f"{head}</head><body><main><h1>{title}</h1>{body}{anchors}</main></body></html>")


class Fixture(unittest.TestCase):
    def site(self, files, home="/"):
        root = tempfile.mkdtemp(prefix="indexgap-corpus-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        pages, problems = core.load_pages(root, SITE)
        self.problems = problems
        return pages, checks.run_all(pages, SITE + home)

    def found(self, result, *codes):
        return sorted((i[1].replace(SITE, ""), i[2]) for i in result["issues"] if i[2] in codes)


class TestLanguageVersionsAreLinked(Fixture):
    """
    Gin (Astro Starlight): переключатель языков — `<select>`, ссылок `<a>` между
    версиями нет вовсе. Связаны они через hreflang. Пакет объявил недостижимыми
    1 122 страницы из 1 225 — все одиннадцать переводов целиком.
    """

    def cluster(self, path):
        return "".join(f'<link rel="alternate" hreflang="{l}" href="{SITE}/{l}/{path}">'
                       for l in ("en", "de", "ja"))

    def site_of(self, with_hreflang=True):
        files = {}
        for lang in ("en", "de", "ja"):
            for path, links in (("", [f"/{lang}/docs/"]), ("docs/", [f"/{lang}/"])):
                files[f"{lang}/{path}index.html"] = html(
                    f"Страница {lang} {path}", lang=lang, links=links,
                    head=self.cluster(path) if with_hreflang else "")
        return self.site(files, home="/en/")

    def test_versions_joined_by_hreflang_are_reachable(self):
        _, result = self.site_of()
        self.assertEqual(self.found(result, "unreachable", "orphan"), [])
        self.assertTrue(any("hreflang" in n and "4" in n for n in result["notes"]), result["notes"])

    def test_without_hreflang_they_really_are_cut_off(self):
        _, result = self.site_of(with_hreflang=False)
        self.assertEqual(len(self.found(result, "unreachable", "orphan")), 4)


class TestAShortPageIsNotAShell(Fixture):
    """
    just и NetworkX: страница-раздел из одного заголовка, страница галереи из
    картинок, заготовка «TO WRITE» в документации Jekyll. Текста мало, скриптов
    темы много — и пакет заявлял, что текст «рисует JavaScript». Это неправда:
    страницы статичны, они просто короткие.
    """

    SCRIPTS = "".join(f'<script src="/s{i}.js"></script>' for i in range(8))
    CHROME = "<nav>" + " ".join(f"раздел{i}" for i in range(40)) + "</nav>"

    def test_a_heading_only_page_is_thin_not_a_shell(self):
        _, result = self.site({
            "index.html": html("Главная", links=["/chapter/"]),
            "chapter/index.html": ('<!doctype html><html lang="ru"><head><title>Командная строка — '
                                   f"раздел</title>{self.SCRIPTS}</head><body>{self.CHROME}<main>"
                                   '<h2>Командная строка</h2></main><a href="/">домой</a></body></html>'),
        })
        self.assertEqual(self.found(result, "js-shell"), [])
        self.assertIn(("/chapter/", "thin"), self.found(result, "thin"))

    def test_a_real_shell_is_still_a_shell(self):
        _, result = self.site({
            "index.html": ('<!doctype html><html><head><title>App</title></head><body>'
                           f'<div id="root"></div>{self.SCRIPTS}</body></html>')})
        self.assertEqual(self.found(result, "js-shell"), [("/", "js-shell")])


class TestFragmentsAreNotPages(Fixture):
    """
    httpx, NetworkX, руководства Google: в собранный сайт попадают заготовки
    шаблонов — `overrides/partials/nav.html`, `_static/webpack-macros.html`,
    `_includes/head-custom.html`. У них нет ни <html>, ни <head>, ни <title>:
    это куски страниц. Каждая получала «сироту» и «нет title».
    """

    def test_a_template_partial_is_skipped_and_named(self):
        pages, result = self.site({
            "index.html": html("Главная"),
            "overrides/partials/nav.html": ('{% import "partials/nav-item.html" as item %}\n'
                                            '<nav class="md-nav">{{ item.render() }}</nav>'),
            "_static/webpack-macros.html": "<!-- AUTO-GENERATED -->\n{% macro head() %}"
                                           '<link href="x.css" rel="stylesheet">{% endmacro %}',
            "_includes/head-custom.html": '<link rel="shortcut icon" href="/favicon.ico">',
        })
        self.assertEqual([p.url.replace(SITE, "") for p in pages], ["/"])
        self.assertTrue(any("nav.html" in p for p in self.problems), self.problems)

    def test_a_page_that_omits_optional_tags_is_still_a_page(self):
        """HTML5 разрешает не писать <html>, <head> и <body>."""
        pages, _ = self.site({"index.html": "<!doctype html><title>Страница без лишних тегов</title>"
                                            f"<h1>Заголовок</h1>{TEXT}"})
        self.assertEqual(len(pages), 1)


class TestJekyllSource(Fixture):
    """
    Руководства по стилю Google — исходники для GitHub Pages: `_config.yml`,
    рядом `.html` и `.md` без шапки. GitHub Pages такие `.md` собирает в
    страницы, а `README.md` делает главной. Пакет выбросил 23 страницы как
    «сырые файлы», не нашёл главной и объявил сиротами то, на что она ссылается.
    """

    def test_markdown_without_front_matter_is_a_page_in_a_jekyll_source(self):
        pages, result = self.site({
            "_config.yml": "title: Style guides\n",
            "README.md": "# Руководства\n\n" + "слово " * 150 + "\n\n[C++](cppguide.html) и [R](Rguide.md)\n",
            "Rguide.md": "# Руководство по R\n\n" + "слово " * 150 + "\n\n[домой](README.md)\n",
            "cppguide.html": html("Руководство по C++", links=["README.md"]),
            "_includes/head-custom.html": '<link rel="icon" href="/favicon.ico">',
        })
        self.assertEqual(sorted(p.url.replace(SITE, "") for p in pages),
                         ["/", "/Rguide/", "/cppguide/"])
        self.assertEqual(self.found(result, "orphan", "unreachable"), [])

    def test_without_a_jekyll_config_a_raw_markdown_file_stays_a_file(self):
        pages, _ = self.site({"index.html": html("Главная"),
                              "auth.md": "# Auth.md\n\nAgent authentication."})
        self.assertEqual([p.url.replace(SITE, "") for p in pages], ["/"])


class TestClosedPagesAreNotJudgedAsContent(Fixture):
    """
    mdBook кладёт в каждый сайт `print.html` и `toc.html` с noindex — служебные
    страницы. Обе получали «нет title», «тонкая», «нет description». Закрытая
    от индекса страница в выдаче не появится: её заголовок никто не увидит.
    """

    def test_a_noindex_page_keeps_only_the_noindex_finding(self):
        _, result = self.site({
            "index.html": html("Главная", links=["/toc.html"]),
            "toc.html": ('<!doctype html><html><head><meta name="robots" content="noindex">'
                         '</head><body><ol><li><a href="/">Глава</a></li></ol></body></html>'),
        })
        on_toc = [i[2] for i in checks.drop_closed_noise(result["issues"], result["pages"])
                  if "/toc" in i[1]]
        self.assertEqual(on_toc, ["noindex"])


class TestMarkdownLinks(Fixture):
    """
    README руководств Google ссылается на всё через сноски: `[C++ Style Guide][cpp]`
    и `[cpp]: cppguide.html` внизу. Такие ссылки не читались, и тринадцать
    страниц, перечисленных на главной, оказались сиротами.
    """

    def test_reference_autolink_and_html_links_count(self):
        body = "\n\n" + "слово " * 150 + "\n"
        _, result = self.site({
            "_config.yml": "title: x\n",
            "README.md": ("# Главная" + body +
                          "* [По сноске][cpp]\n* [Свёрнутая][]\n* [короткая]\n"
                          "* <https://example.com/auto/>\n"
                          '* <a href="inline.html">в HTML</a>\n'
                          "* [со скобками](wiki/Foo_(bar).md)\n\n"
                          "[cpp]: cppguide.md\n[Свёрнутая]: collapsed.md \"Заголовок\"\n"
                          "[короткая]: <short.md>\n"),
            "cppguide.md": "# C++" + body, "collapsed.md": "# Свёрнутая" + body,
            "short.md": "# Короткая" + body, "auto.md": "# Авто" + body,
            "inline.md": "# В HTML" + body, "wiki/Foo_(bar).md": "# Со скобками" + body,
        })
        self.assertEqual(self.found(result, "orphan", "unreachable"), [])

    def test_a_link_inside_inline_code_is_not_a_link(self):
        body = "\n\n" + "слово " * 150 + "\n"
        _, result = self.site({
            "_config.yml": "title: x\n",
            "README.md": "# Главная" + body + "Пишите так: `[текст](hidden.md)`\n",
            "hidden.md": "# Спрятанная" + body,
        })
        self.assertEqual(self.found(result, "orphan"), [("/hidden/", "orphan")])


class TestTodoInProse(Fixture):
    """
    Руководство по стилю описывает, как писать комментарии `TODO:` — и получало
    критичную находку «страница не дописана». Слово в тексте — не метка
    заготовки. Критичной остаётся только заготовка самого пакета.
    """

    def levels(self, text):
        from indexgap import content
        pages, _ = self.site({"index.html": html("Главная", body=f"<p>{text}</p>{TEXT}")})
        return [i[0] for i in content.check_brief(pages) if i[2] == "brief-left"]

    def test_todo_in_text_is_a_warning(self):
        self.assertEqual(self.levels("Use TODO: comments for code that is temporary."), ["warning"])

    def test_the_package_brief_is_still_critical(self):
        self.assertEqual(self.levels("BRIEF FOR THE AGENT: write the page."), ["critical"])


class TestTinyPagesAreNotCompared(Fixture):
    """Страница из одного заголовка — тонкая. Сравнивать её с другой такой же
    и сообщать «100% дубль» и «0% уникального» — та же находка ещё дважды."""

    def test_heading_only_pages_get_thin_and_nothing_else(self):
        files = {"index.html": html("Главная", links=[f"/c{i}/" for i in range(10)])}
        for i in range(10):
            files[f"c{i}/index.html"] = ('<!doctype html><html lang="ru"><head><title>Раздел справки '
                                         f'номер {i}</title></head><body><main><h2>Раздел</h2></main>'
                                         '<a href="/">домой</a></body></html>')
        _, result = self.site(files)
        self.assertEqual(self.found(result, "near-duplicate", "low-uniqueness", "similar"), [])
        self.assertEqual(len(self.found(result, "thin")), 11)


class TestTemplateSyntax(Fixture):
    def test_a_jinja_macro_file_with_a_body_tag_is_still_a_fragment(self):
        pages, _ = self.site({
            "index.html": html("Главная"),
            "_static/webpack-macros.html": ("<!-- AUTO-GENERATED -->\n{% macro head() %}\n"
                                            '<link href="x.css" rel="stylesheet">\n{% endmacro %}\n'
                                            "{% macro body_post() %}\n<body class=\"x\">{% endmacro %}"),
        })
        self.assertEqual([p.url.replace(SITE, "") for p in pages], ["/"])


if __name__ == "__main__":
    unittest.main()
