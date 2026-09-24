# -*- coding: utf-8 -*-
"""
Две ошибки, найденные прогоном по живому каталогу виз (4 573 страницы).

Первая: корень сайта на Next.js — не главная, а заглушка-редирект на `/en`.
Инструмент брал её за главную, не находил из неё ни одной ссылки и объявлял
недостижимыми около трёх тысяч страниц.

Вторая: сайт сознательно закрыл переводы — `noindex` и canonical на английскую
версию. Одно правило шаблона давало семь разных находок на каждую из 1 408
страниц, 9 722 строки — девять десятых всего отчёта. Сигнал «переводы
запаркованы» тонул в собственных следствиях.

Тесты ниже закрепляют исправление обеих и, отдельно, то, что исправление
не прячет настоящие беды: одинокий `noindex` и открытый перевод с чужим
canonical должны сообщаться как раньше.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

SITE = "https://example.com"


def html(title, body="", head="", links=()):
    anchors = "".join(f'<a href="{href}">ссылка {i}</a>' for i, href in enumerate(links))
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            f'<meta name="description" content="{"описание страницы " * 6}">'
            f'{head}</head><body><main><h1>{title}</h1>'
            f'<p>{body or "Текст страницы " * 60}</p>{anchors}</main></body></html>')


class Fixture(unittest.TestCase):
    def pages(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-closed-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        loaded, _ = core.load_pages(root, SITE)
        return loaded

    def key(self, url):
        return core.url_key(url)


# ── главная-заглушка ──────────────────────────────────────────────────────────

REDIRECT_SHELL = ('<!doctype html><html><head><title>x</title></head><body>'
                  '<script>self.__next_f.push([1,"NEXT_REDIRECT;replace;/en;307;"])'
                  '</script></body></html>')


class TestRedirectHome(Fixture):
    def site(self, root_html):
        return self.pages({
            "index.html": root_html,
            "en/index.html": html("Home", links=["/en/a/", "/en/b/"]),
            "en/a/index.html": html("A", links=["/en/"]),
            "en/b/index.html": html("B", links=["/en/"]),
        })

    def test_next_redirect_shell_is_followed_to_the_real_home(self):
        graph = checks.link_graph(self.site(REDIRECT_SHELL), SITE + "/")
        self.assertEqual(self.key(graph["home"]), self.key(SITE + "/en/"))
        self.assertEqual(graph["unreachable"], [])
        self.assertEqual(self.key(graph["home_redirected_from"]), self.key(SITE + "/"))

    def test_meta_refresh_is_followed_too(self):
        refresh = ('<!doctype html><html><head><title>x</title>'
                   '<meta http-equiv="refresh" content="0; url=/en/"></head>'
                   '<body></body></html>')
        graph = checks.link_graph(self.site(refresh), SITE + "/")
        self.assertEqual(self.key(graph["home"]), self.key(SITE + "/en/"))
        self.assertEqual(graph["unreachable"], [])

    def test_a_real_home_is_left_alone(self):
        pages = self.site(html("Root", links=["/en/"]))
        graph = checks.link_graph(pages, SITE + "/")
        self.assertEqual(self.key(graph["home"]), self.key(SITE + "/"))
        self.assertFalse(graph.get("home_redirected_from"))

    def test_the_redirect_is_said_out_loud(self):
        result = checks.run_all(self.site(REDIRECT_SHELL), SITE + "/")
        self.assertTrue(any("/en" in n and "редирект" in n for n in result["notes"]),
                        result["notes"])


# ── запаркованные переводы ────────────────────────────────────────────────────

LANGS = ["ar", "ru", "zh", "hi", "fa", "id"]


def cluster(path):
    """Все версии страницы объявляют друг друга — как делает шаблон."""
    head = f'<link rel="alternate" hreflang="en" href="{SITE}/en/{path}/">'
    head += "".join(f'<link rel="alternate" hreflang="{l}" href="{SITE}/{l}/{path}/">'
                    for l in LANGS)
    return head


class TestParkedTranslations(Fixture):
    def site(self, extra=None):
        files = {
            "en/index.html": html("Home", links=["/en/apply/"]),
            "en/apply/index.html": html(
                "Apply", head=cluster("apply") + f'<link rel="canonical" href="{SITE}/en/apply/">',
                links=["/en/"]),
        }
        for lang in LANGS:
            files[f"{lang}/apply/index.html"] = html(
                f"Apply {lang}",
                head=cluster("apply")
                + f'<link rel="canonical" href="{SITE}/en/apply/">'
                + '<meta name="robots" content="noindex, follow">')
        files.update(extra or {})
        return self.pages(files)

    def findings(self, extra=None):
        result = checks.run_all(self.site(extra), SITE + "/en/")
        return result, [(i[1], i[2]) for i in result["issues"]]

    def test_one_rule_is_reported_once(self):
        result, found = self.findings()
        parked = [f for f in found if f[1] == "translations-parked"]
        self.assertEqual(len(parked), 1, found)
        message = next(i[3] for i in result["issues"] if i[2] == "translations-parked")
        self.assertIn(str(len(LANGS)), message)

    def test_its_consequences_are_not_repeated_per_page(self):
        _, found = self.findings()
        echoes = {"noindex", "canonical-elsewhere", "orphan", "unreachable", "deep",
                  "hreflang-no-self", "hreflang-canonical-conflict",
                  "hreflang-no-return", "hreflang-target-blocked"}
        on_parked = [f for f in found
                     if any(f"/{l}/apply" in f[0] for l in LANGS) and f[1] in echoes]
        self.assertEqual(on_parked, [])

    def test_a_lone_noindex_is_still_reported(self):
        """Сворачивается правило, а не любая закрытая страница."""
        _, found = self.findings({
            "en/contact/index.html": html(
                "Contact", head='<meta name="robots" content="noindex">', links=["/en/"]),
        })
        on_contact = {f[1] for f in found if "/en/contact" in f[0]}
        self.assertIn("noindex", on_contact, found)
        # Но не «сирота» и не «недостижима»: ссылки нужны странице, чтобы её
        # нашли и проиндексировали, а эта от индекса закрыта сознательно.
        self.assertFalse(on_contact & {"orphan", "unreachable", "deep"}, on_contact)

    def test_an_open_translation_with_a_foreign_canonical_still_counts(self):
        """Открытый перевод с canonical на английский — настоящая беда: он
        хочет ранжироваться и сам себя из индекса выводит. Прятать нельзя."""
        _, found = self.findings({
            "ms/apply/index.html": html(
                "Apply ms",
                head=cluster("apply") + f'<link rel="canonical" href="{SITE}/en/apply/">'),
        })
        on_ms = {f[1] for f in found if "/ms/apply" in f[0]}
        self.assertTrue(on_ms & {"canonical-elsewhere", "hreflang-canonical-conflict"},
                        on_ms)



# ── порядок починки ───────────────────────────────────────────────────────────

class TestFixOrder(unittest.TestCase):
    """«Чинить в этом порядке» считал только количество.

    Находка уровня сайта — одна правка с самым большим радиусом, но по числу
    она всегда равна единице. robots.txt, закрывший сайт целиком, уступал место
    пятидесяти тонким страницам и в список не попадал вовсе.
    """

    def first_lines(self, issues):
        import contextlib, io
        from indexgap import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli._print_first_things(issues)
        return [l for l in buf.getvalue().splitlines() if l.startswith("  ")]

    def test_a_site_level_finding_comes_first_however_small_its_count(self):
        issues = [("critical", f"{SITE}/p{i}/", "thin", "x") for i in range(50)]
        issues += [("critical", f"{SITE}/q{i}/", "no-title", "x") for i in range(30)]
        issues += [("critical", f"{SITE}/r{i}/", "orphan", "x") for i in range(20)]
        issues.append(("critical", "robots.txt", "robots-blocks-all", "x"))
        lines = self.first_lines(issues)
        self.assertIn("robots-blocks-all", lines[0])

    def test_parked_translations_are_not_buried(self):
        issues = [("critical", f"{SITE}/p{i}/", "near-duplicate", "x") for i in range(500)]
        issues.append(("critical", "hreflang", "translations-parked", "x"))
        self.assertIn("translations-parked", self.first_lines(issues)[0])

    def test_without_site_level_findings_the_order_is_by_count(self):
        issues = [("critical", f"{SITE}/p{i}/", "thin", "x") for i in range(5)]
        issues += [("critical", f"{SITE}/q{i}/", "no-title", "x") for i in range(9)]
        self.assertIn("no-title", self.first_lines(issues)[0])


if __name__ == "__main__":
    unittest.main()
