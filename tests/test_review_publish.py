# -*- coding: utf-8 -*-
"""
Публикация: находки ревью десяти агентов перед публичным запуском.

В sitemap и в очередь IndexNow попадало то, что страницей не является:
`404.html`, заглушка-редирект, черновик Hugo с `draft: true`, запись Jekyll
с `published: false`. Поисковику отправлялся адрес, по которому либо ничего
нет, либо лежит недописанное.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core, publish

SITE = "https://example.com"
TEXT = "<p>" + "слово " * 150 + "</p>"


def html(title, links=("/",)):
    anchors = "".join(f'<a href="{h}">ссылка</a>' for h in links)
    return (f"<html><head><title>{title} — страница сайта</title></head><body><main>"
            f"<h1>{title}</h1>{TEXT}{anchors}</main></body></html>")


def md(title, extra=""):
    return f"---\ntitle: {title}\n{extra}---\n\n# {title}\n\n" + "слово " * 150 + "\n"


class Fixture(unittest.TestCase):
    def pages(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-pub-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.root = root
        return core.load_pages(root, SITE)[0]

    def sitemap(self, pages):
        out = tempfile.mkdtemp(prefix="indexgap-out-")
        self.addCleanup(shutil.rmtree, out, True)
        publish.build_sitemap(pages, out, SITE, today="2026-10-01")
        text = open(os.path.join(out, "sitemap.xml"), encoding="utf-8").read()
        return sorted(u.replace(SITE, "") for u in
                      __import__("re").findall(r"<loc>([^<]+)</loc>", text))


class TestNotPages(Fixture):
    def test_error_page_404_html_is_not_a_page(self):
        pages = self.pages({
            "index.html": html("Главная", ["/a/"]),
            "a/index.html": html("Страница"),
            "404.html": html("Не найдено"),
            "500.html": html("Ошибка"),
            "_not-found.html": html("Не найдено"),
            "404/index.html": html("Не найдено"),
        })
        self.assertEqual(sorted(p.url.replace(SITE, "") for p in pages), ["/", "/a/"])
        result = checks.run_all(pages, SITE + "/")
        self.assertEqual([i for i in result["issues"] if i[2] == "orphan"], [])

    def test_a_page_about_error_404_is_still_a_page(self):
        pages = self.pages({"index.html": html("Главная", ["/blog/404-errors/"]),
                            "blog/404-errors/index.html": html("Про ошибку 404")})
        self.assertEqual(len(pages), 2)

    def test_sitemap_excludes_stubs_and_ssg_drafts(self):
        stub = ('<html><head><title>/a/</title><meta http-equiv="refresh" '
                'content="0; url=/a/"></head></html>')
        pages = self.pages({
            "index.md": md("Главная"),
            "a.md": md("Готовая"),
            "hugo-draft.md": md("Черновик Hugo", "draft: true\n"),
            "jekyll-off.md": md("Снято в Jekyll", "published: false\n"),
            "later.md": md("Отложенная", "publishDate: 2099-01-01\n"),
            "status-draft.md": md("Черновик по статусу", "status: draft\n"),
            "event.md": md("Будущее событие", "date: 2099-01-01\n"),
        })
        self.assertEqual(self.sitemap(pages), ["/", "/a/", "/event/"])
        queue = publish.diff_changed(pages, {})
        self.assertEqual(sorted(u.replace(SITE, "") for u in queue["new"]), ["/", "/a/", "/event/"])

        stubbed = self.pages({"index.html": html("Главная", ["/a/"]),
                              "a/index.html": html("Страница"), "old/index.html": stub})
        self.assertEqual(self.sitemap(stubbed), ["/", "/a/"])


class Cli(Fixture):
    def run_cli(self, argv, cwd=None):
        import contextlib, io
        from indexgap import cli
        out = io.StringIO()
        here = os.getcwd()
        os.chdir(cwd or here)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    code = cli.main(argv)
                except SystemExit as exc:
                    code = exc.code
        finally:
            os.chdir(here)
        return code, out.getvalue()

    def project(self):
        self.pages({"indexgap.json": '{"site": "https://example.com", "pages": "./content"}',
                    "content/index.md": md("Главная"), "content/a.md": md("Страница")})
        return self.root


class TestSitemapCommand(Cli):
    def test_a_foreign_sitemap_is_not_overwritten(self):
        """Все остальные команды записи по умолчанию ничего не пишут; `sitemap`
        молча заменял sitemap.xml, который написал не он."""
        root = self.project()
        mine = os.path.join(root, "content", "sitemap.xml")
        with open(mine, "w", encoding="utf-8") as fh:
            fh.write("<urlset><url><loc>https://example.com/hand-written.html</loc></url></urlset>")
        code, out = self.run_cli(["sitemap"], cwd=root)
        self.assertEqual(code, 2)
        self.assertIn("hand-written", open(mine, encoding="utf-8").read())
        self.assertIn("--force", out)
        code, _ = self.run_cli(["sitemap", "--force"], cwd=root)
        self.assertEqual(code, 0)
        self.assertNotIn("hand-written", open(mine, encoding="utf-8").read())
        # Свой файл переписывается без вопросов.
        self.assertEqual(self.run_cli(["sitemap"], cwd=root)[0], 0)

    def test_fresh_checkout_keeps_lastmod_and_queue(self):
        """Манифест лежит рядом с indexgap.json и не прячется от git: сборка в CI
        начинает с чистого каталога, и без манифеста каждая страница была бы
        «новой» при каждом деплое."""
        root = self.project()
        self.assertEqual(self.run_cli(["sitemap"], cwd=root)[0], 0)
        self.assertTrue(os.path.isfile(os.path.join(root, ".indexgap-manifest.json")))
        self.assertFalse(os.path.exists(os.path.join(root, "content", ".indexgap-manifest.json")))
        from indexgap import install
        self.assertNotIn(".indexgap-manifest.json", install.GITIGNORE_LINES)

    def test_a_missing_manifest_is_said_out_loud(self):
        root = self.project()
        _, out = self.run_cli(["sitemap"], cwd=root)
        self.assertIn("первый прогон", out)
        _, again = self.run_cli(["sitemap"], cwd=root)
        self.assertNotIn("первый прогон", again)

    def test_send_without_a_manifest_needs_a_word(self):
        from unittest import mock
        root = self.project()
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("сеть")), \
                mock.patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("сеть")):
            code, out = self.run_cli(["notify", "--key", "k" * 32, "--send", "--offline"], cwd=root)
        self.assertEqual(code, 2)
        self.assertIn("--first", out)

    def test_an_old_manifest_beside_the_pages_is_still_found(self):
        root = self.project()
        old = os.path.join(root, "content", ".indexgap-manifest.json")
        with open(old, "w", encoding="utf-8") as fh:
            fh.write('{"_shards": ["sitemap.xml"]}')
        self.assertEqual(self.run_cli(["sitemap"], cwd=root)[0], 0)
        self.assertFalse(os.path.exists(os.path.join(root, ".indexgap-manifest.json")))


class TestFlatUrls(Fixture):
    def test_sitemap_uses_declared_html_url_for_flat_files(self):
        """`/about/` для `about.html` — 404 на GitHub Pages, S3 и обычном nginx."""
        pages = self.pages({
            "index.html": html("Главная", ["about.html"]),
            "about.html": html("О нас", ["index.html"]).replace(
                "<head>", '<head><link rel="canonical" href="https://example.com/about.html">'),
            "team.html": html("Команда", ["index.html"]),
        })
        self.assertEqual(self.sitemap(pages), ["/", "/about.html", "/team/"])
        self.assertEqual([i for i in checks.run_all(pages, SITE + "/")["issues"]
                          if i[2] == "canonical-elsewhere"], [])


class TestIndexNowAnswers(unittest.TestCase):
    def submit(self, status=200, location=None):
        import urllib.error
        from unittest import mock

        class Opener:
            def open(self, request, timeout=None):
                if status >= 300:
                    raise urllib.error.HTTPError(request.full_url, status, "x",
                                                 {"Location": location or ""}, None)
                response = mock.MagicMock()
                response.status = status
                response.__enter__.return_value = response
                return response

        with mock.patch("urllib.request.build_opener", lambda *a: Opener()), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("редирект пройден")):
            return publish.submit_indexnow([SITE + "/a/"], SITE, "k" * 32, dry_run=False)

    def test_redirected_post_is_not_acceptance(self):
        outcome = self.submit(302, "https://elsewhere.example/")
        self.assertEqual(outcome["accepted"], [])

    def test_202_is_accepted_and_called_pending(self):
        outcome = self.submit(202)
        self.assertEqual(outcome["accepted"], [SITE + "/a/"])
        self.assertTrue(outcome.get("pending"))

    def test_http_403_marks_nothing(self):
        self.assertEqual(self.submit(403)["accepted"], [])


if __name__ == "__main__":
    unittest.main()
