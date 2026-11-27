# -*- coding: utf-8 -*-
"""
1.30 (media): картинки, которых нет в сборке, и тяжёлые data:-картинки.

* broken-image: src, srcset, <picture><source>, poster и <link rel=icon>,
  которых нет в сборке, — одна находка на страницу;
* адрес считается как у ссылок: <base href>, %-кодирование, query;
* чужой хост, data:, blob:, шаблоны и обработчики без расширения не в счёт;
* /_next/image?url=… — проверяется исходник из параметра;
* сборка без картинок сайта (.next/server/app) — без находок;
* встроенные data:-картинки больше 1 МБ — в heavy-images, с адресом и весом.
"""

import base64
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, core, signals
from indexgap.core import load_pages

SITE = "https://demo.example"
WORDS = " ".join(f"word{i} item{i} note{i}" for i in range(120))


def html(body="", head="", title="Harbour guide"):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title}</title>"
            f"{head}</head><body><main><h1>{title}</h1>{body}<p>{WORDS}</p></main></body></html>")


class Site(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-130media-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.root = self.dir

    def write(self, rel, text, mode="w", root=None):
        path = os.path.join(root or self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
            fh.write(text)

    def image(self, rel, root=None):
        self.write(rel, b"\x89PNG\r\n\x1a\n" + b"\0" * 64, "wb", root)

    def load(self, root=None, site=SITE):
        return load_pages(root or self.root, site)

    def broken(self, root=None, site=SITE):
        pages, _ = self.load(root, site)
        return {i[1].replace(site, ""): i for i in checks.broken_image_issues(pages)}


class BrokenImage(Site):
    def test_every_image_attribute_is_checked(self):
        self.image("img/logo.png")
        self.write("index.html", html('<img src="/img/logo.png" alt="Logo">'))
        self.write("a/index.html", html(
            '<img src="/img/missing-hero.jpg" srcset="/img/missing-800.jpg 800w, '
            '/img/logo.png 1600w" alt="Harbour at dawn">'
            '<picture><source srcset="/img/gone.avif 1x, /img/gone2.avif 2x" '
            'type="image/avif"><img src="/img/logo.png" alt="Logo"></picture>'
            '<video poster="/img/poster.jpg"></video>',
            head='<link rel="icon" href="/favicon-gone.ico">'))
        found = self.broken()
        self.assertEqual(sorted(found), ["/a/"])
        level, _url, code, message = found["/a/"]
        self.assertEqual((level, code), ("warning", "broken-image"))
        self.assertEqual(set(message.subject), {
            "/img/missing-hero.jpg", "/img/missing-800.jpg", "/img/gone.avif",
            "/img/gone2.avif", "/img/poster.jpg", "/favicon-gone.ico"})
        self.assertIn("/img/missing-hero.jpg", message)
        self.assertIn("ещё 3", message)
        self.assertNotIn("/img/logo.png", message)

    def test_resolved_like_links(self):
        self.image("img/my photo.jpg")
        self.image("img/a.jpg")
        self.image("sub/pic.png")
        self.write("index.html", html(
            '<img src="/img/my%20photo.jpg" alt="x"><img src="/img/a.jpg?v=3#top" alt="x">'
            '<img src="//demo.example/img/a.jpg" alt="x">'))
        self.write("blog/post/index.html", html('<img src="../../img/a.jpg" alt="x">'
                                                '<img src="../../img/nope.jpg" alt="x">'))
        self.write("b/index.html", html('<img src="pic.png" alt="x">',
                                        head='<base href="/sub/">'))
        found = self.broken()
        self.assertEqual(sorted(found), ["/blog/post/"])
        self.assertEqual(found["/blog/post/"][3].subject, ("/img/nope.jpg",))

    def test_foreign_inline_and_templates_are_not_judged(self):
        self.image("img/a.jpg")
        self.write("index.html", html(
            '<img src="https://cdn.other.example/a.jpg" alt="x">'
            '<img src="//cdn.other.example/b.jpg" alt="x">'
            '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="x">'
            '<img src="blob:https://demo.example/123" alt="x">'
            '<img src="/img/{{ city }}.jpg" alt="x">'
            '<img src="/api/og?title=Harbour" alt="x">'
            '<img src="/img/gone.jpg" alt="x">'))
        found = self.broken()
        self.assertEqual(found["/"][3].subject, ("/img/gone.jpg",))

    def test_next_image_checks_its_source(self):
        self.image("img/a.jpg")
        self.write("index.html", html(
            '<img src="/_next/image?url=%2Fimg%2Fa.jpg&w=640&q=75" alt="x">'
            '<img srcset="/_next/image?url=%2Fimg%2Fa.jpg&w=640 1x, '
            '/_next/image?url=%2Fimg%2Fa.jpg&w=1080 2x" alt="x">'
            '<img src="/_next/image?url=https%3A%2F%2Fcdn.other.example%2Fx.jpg&w=640" alt="x">'
            '<img src="/_next/image?w=640" alt="x">'))
        self.write("b/index.html", html(
            '<img src="/_next/image?url=%2Fimg%2Fgone.jpg&w=640&q=75" alt="x">'))
        found = self.broken()
        self.assertEqual(sorted(found), ["/b/"])
        self.assertEqual(found["/b/"][3].subject, ("/img/gone.jpg",))

    def test_next_server_build_is_skipped(self):
        body = html('<img src="/img/hero.jpg" alt="x"><img src="/_next/static/media/a.png" alt="x">')
        # Та же страница в обычной сборке — находка есть.
        static = os.path.join(self.dir, "out")
        self.image("img/logo.png", static)
        self.write("index.html", body, root=static)
        self.assertIn("/", self.broken(static))
        # В `.next/server/app` картинок из public/ нет и не должно быть.
        server = os.path.join(self.dir, "proj", ".next", "server", "app")
        self.image("logo.png", server)
        self.write("index.html", body, root=server)
        self.write("about.html", body, root=server)
        pages, problems = self.load(server)
        self.assertTrue(pages)
        self.assertEqual(checks.broken_image_issues(pages), [])
        self.assertFalse([p for p in problems if "картин" in p])
        # Скопированная куда-то: рядом со страницами их .rsc и .meta.
        copied = os.path.join(self.dir, "copied")
        self.image("logo.png", copied)
        self.write("index.html", body, root=copied)
        self.write("index.rsc", "1:I[]", root=copied)
        self.write("index.meta", "{}", root=copied)
        self.assertEqual(self.broken(copied), {})

    def test_html_only_build_gives_one_note(self):
        self.write("index.html", html('<img src="/img/a.jpg" alt="x">'))
        self.write("b/index.html", html('<img src="/img/b.jpg" alt="x">'))
        pages, problems = self.load()
        self.assertEqual(checks.broken_image_issues(pages), [])
        note = [p for p in problems if "/img/a.jpg" in p]
        self.assertEqual(len(note), 1)
        self.assertIn("/img/b.jpg", note[0])
        # Стоит картинке появиться — пропавшие отмечаются по страницам.
        self.image("img/a.jpg")
        self.assertEqual(sorted(self.broken()), ["/b/"])

    def test_outside_site_path_and_redirect_rules(self):
        self.image("img/a.jpg")
        self.write("_redirects", "/docs/media/* https://cdn.demo.example/:splat 301\n")
        self.write("index.html", html('<img src="/docs/media/x.jpg" alt="x">'
                                      '<img src="/other/x.jpg" alt="x">'
                                      '<img src="/docs/img/gone.jpg" alt="x">'))
        found = self.broken(site=SITE + "/docs/")
        self.assertEqual([i[3].subject for i in found.values()], [("/docs/img/gone.jpg",)])

    def test_reported_by_run_all_with_baseline_subject(self):
        self.image("img/a.jpg")
        self.write("index.html", html('<a href="/a/">a</a>'))
        self.write("a/index.html", html('<a href="/">home</a><img src="/img/gone.jpg" alt="x">'))
        pages, _ = self.load()
        issues = checks.run_all(pages, SITE + "/")["issues"]
        mine = [i for i in issues if i[2] == "broken-image"]
        self.assertEqual([(i[0], i[1]) for i in mine], [("warning", SITE + "/a/")])
        self.assertIn("broken-image", checks.CODE_WEIGHT)
        old = [{"level": l, "url": u, "code": c, "message": str(m),
                "subject": list(getattr(m, "subject", ()))} for l, u, c, m in mine]
        self.assertEqual(cli.compare_baseline(mine, old)["new"], [])


class InlineImages(Site):
    @staticmethod
    def data(kib, kind="jpeg"):
        return f"data:image/{kind};base64," + base64.b64encode(os.urandom(kib * 1024)).decode()

    def test_decoded_size(self):
        raw = os.urandom(1000)
        uri = "data:image/png;base64," + base64.b64encode(raw).decode()
        self.assertEqual(core.data_uri_bytes(uri), 1000)
        self.assertEqual(core.data_uri_bytes("data:image/svg+xml,%3Csvg%3E%3C/svg%3E"), 11)
        self.assertEqual(core.data_uri_bytes("data:text/plain;base64,QUJD"), 0)

    def test_heavy_inline_hero_is_named_with_its_size(self):
        self.write("index.html", html('<img src="/img/a.png" alt="x">'))
        self.write("hero/index.html", html(f'<img src="{self.data(1400)}" alt="Lake">'))
        # Иконки и спрайты по мелочи — тишина, даже если их много.
        icons = "".join(f'<img src="{self.data(8, "png")}" alt="">' for _ in range(40))
        self.write("icons/index.html", html(
            icons + '<svg><use href="#i"></use></svg>'
            '<img src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E" alt="">'))
        found = signals.heavy_images(list(self.load()[0]))
        self.assertEqual(len(found), 1)
        level, url, code, message = found[0]
        self.assertEqual((level, url, code), ("info", "", "heavy-images"))
        self.assertIn("/hero/ (1.4 MB)", message)
        self.assertNotIn("/icons/", message)
        self.assertIn("/hero/", message.subject)

    def test_srcset_picture_and_style_backgrounds_add_up(self):
        self.write("index.html", html(
            f'<picture><source srcset="{self.data(400, "webp")} 1x"><img src="{self.data(300)}" '
            f'srcset="{self.data(200)} 2x" alt="x"></picture>'
            f'<div style="background-image: url(\'{self.data(300)}\')">x</div>'))
        found = signals.heavy_images(list(self.load()[0]))
        self.assertEqual(len(found), 1)
        self.assertIn("/ (1.2 MB)", found[0][3])

    def test_files_and_inline_in_one_finding(self):
        self.write("img/big.jpg", b"\0" * (1100 * 1024), "wb")
        self.write("index.html", html('<img src="/img/big.jpg" alt="x">'))
        self.write("hero/index.html", html(f'<img src="{self.data(1200)}" alt="x">'))
        found = signals.heavy_images(list(self.load()[0]))
        self.assertEqual(len(found), 1)
        self.assertIn("img/big.jpg (1.1 MB)", found[0][3])
        self.assertIn("/hero/ (1.2 MB)", found[0][3])
        self.assertEqual(set(found[0][3].subject), {"img/big.jpg", "/hero/"})


if __name__ == "__main__":
    unittest.main()
