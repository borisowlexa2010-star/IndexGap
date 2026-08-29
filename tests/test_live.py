# -*- coding: utf-8 -*-
"""
Регрессии, найденные на живых проектах, а не на фикстурах.

Прогон на шести настоящих сайтах (7 149 адресов из sitemap) дал одну находку,
которую нельзя было получить на выдуманных данных: каталог недвижимости
из 1 099 страниц целиком отдавался пустой JS-оболочкой. Пакет честно нашёл
1 099 `js-shell` — и вместе с ними 1 099 `low-uniqueness` и 1 098 `orphan`.

Это не три беды, а одна. В HTML без текста нечего мерить и не по чему ходить,
поэтому зависимые проверки на таких страницах не считаются, а вместо них
пакет говорит вслух, сколько страниц оказались оболочками.

Второй урок того же прогона: 1 099 страниц объявляли `canonical` на главную.
Эта находка остаётся постраничной — она настоящая на каждой странице,
и в сводке «чинить в этом порядке» и так схлопывается в одну строку.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexgap import aeo, checks, core

SITE = "https://example.com"


def shell_html(canonical=None, title="Каталог"):
    """Ровно то, чем оказался живой сайт: head есть, тела нет, скрипты есть."""
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            f'<meta name="description" content="{"о" * 100}">{link}</head>'
            '<body><div id="root"></div>'
            '<script src="/a.js"></script><script src="/b.js"></script>'
            '<script src="/c.js"></script></body></html>')


def real_html(n, extra=""):
    body = " ".join(f"слово{n}{i}" for i in range(400))
    return (f'<!doctype html><html lang="ru"><head><title>Страница {n} про визы</title>'
            f'<meta name="description" content="{"описание страницы " * 5}">'
            f'</head><body><main><h1>Страница {n}</h1><p>{body}</p>{extra}</main>'
            '</body></html>')


class Fixture(unittest.TestCase):
    def pages(self, files):
        import shutil
        import tempfile
        root = tempfile.mkdtemp(prefix="indexgap-live-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        pages, _ = core.load_pages(root, SITE)
        return pages

    def codes(self, result):
        return [i[2] for i in result["issues"]]


class TestShellCascade(Fixture):
    def test_shell_is_recognised(self):
        pages = self.pages({"a/index.html": shell_html()})
        self.assertTrue(checks.is_shell(pages[0]))

    def test_a_real_page_is_not_a_shell(self):
        pages = self.pages({"a/index.html": real_html(1)})
        self.assertFalse(checks.is_shell(pages[0]))

    def test_shell_is_reported_even_without_aeo(self):
        """Раньше `js-shell` жил только в aeo, и `check --no-aeo` о нём молчал."""
        pages = self.pages({f"p{i}/index.html": shell_html() for i in range(12)})
        result = checks.run_all(pages, home_url=SITE + "/")
        self.assertEqual(self.codes(result).count("js-shell"), 12)

    def test_dependent_findings_are_not_repeated_on_shells(self):
        pages = self.pages({f"p{i}/index.html": shell_html() for i in range(12)})
        codes = self.codes(checks.run_all(pages, home_url=SITE + "/"))
        for dependent in ("low-uniqueness", "orphan", "unreachable", "thin",
                          "near-duplicate", "similar", "no-h1", "deep"):
            self.assertNotIn(dependent, codes, dependent)

    def test_the_report_says_out_loud_how_many_shells_there_were(self):
        pages = self.pages({f"p{i}/index.html": shell_html() for i in range(12)})
        result = checks.run_all(pages, home_url=SITE + "/")
        self.assertTrue(any("каркас" in n for n in result["notes"]), result["notes"])

    def test_real_pages_keep_their_findings_next_to_shells(self):
        files = {f"s{i}/index.html": shell_html() for i in range(6)}
        files["real/index.html"] = real_html(1)
        files["index.html"] = real_html(0, '<a href="/real/">дальше</a>')
        pages = self.pages(files)
        codes = self.codes(checks.run_all(pages, home_url=SITE + "/"))
        self.assertIn("js-shell", codes)
        # Живая страница по-прежнему проверяется полностью.
        self.assertTrue(any(c not in ("js-shell", "source-note") for c in codes))

    def test_aeo_does_not_grade_an_empty_page(self):
        """Оболочку нельзя ругать за отсутствие прямого ответа: ответа нет нигде."""
        pages = self.pages({"a/index.html": shell_html()})
        codes = [i[2] for i in aeo.run(pages)["issues"]]
        self.assertNotIn("no-answer", codes)
        self.assertNotIn("preamble", codes)

    def test_amp_is_not_a_shell(self):
        page = self.pages({"a/index.html": shell_html().replace(
            '<html lang="en">', '<html amp lang="en">')})[0]
        self.assertFalse(checks.is_shell(page))


class TestCanonicalCollapse(Fixture):
    def test_canonical_to_the_home_page_is_reported_on_every_page(self):
        """
        1 098 страниц живого каталога указывали canonical на главную.
        Находка настоящая на каждой из них — схлопывать её нельзя,
        иначе исчезнет список того, что чинить.
        """
        files = {f"p{i}/index.html": real_html(i) for i in range(5)}
        files = {rel: text.replace("</head>",
                                   f'<link rel="canonical" href="{SITE}/"></head>')
                 for rel, text in files.items()}
        pages = self.pages(files)
        codes = self.codes(checks.run_all(pages, home_url=SITE + "/"))
        self.assertEqual(codes.count("canonical-elsewhere"), 5)


class TestDuplicateGroups(Fixture):
    """
    588 страниц с кодом `near-duplicate` на живом каталоге оказались 72 группами,
    в самой большой 24 страницы. «Переписать 588 страниц» — приговор,
    «развести 72 темы» — задача. Счёт групп должен звучать.
    """

    def test_clusters_join_pages_through_a_common_partner(self):
        groups = checks._clusters([("a", "b"), ("b", "c"), ("x", "y")])
        self.assertEqual([len(g) for g in groups], [3, 2])
        self.assertIn(["a", "b", "c"], groups)

    def test_group_count_is_said_out_loud(self):
        body = " ".join(f"общее{i}" for i in range(300))
        files = {}
        for i in range(6):
            files[f"p{i}/index.html"] = (
                f'<!doctype html><html lang="ru"><head><title>Виза в страну {i} — '
                f'полный разбор</title><meta name="description" content="'
                f'{"описание страницы про визу " * 4}"></head><body><main>'
                f'<h1>Виза {i}</h1><p>{body} страна{i}</p></main></body></html>')
        pages = self.pages(files)
        result = checks.run_all(pages, home_url=SITE + "/")
        self.assertTrue(any("групп" in n for n in result["notes"]), result["notes"])


class TestAnchorsThatOnlyLookVague(Fixture):
    """
    На живом сайте виз `vague-anchor` сработал на 2 970 страницах из 2 970.
    Виноваты были переключатель языков («中文») и ссылка на соцсеть («VK»):
    короткие по знакам и совершенно информативные.
    """

    def test_cjk_anchor_is_not_vague(self):
        from indexgap import content
        page = self.pages({"a/index.html": real_html(
            1, '<a href="/zh/">中文</a>')})[0]
        codes = [i[2] for i in content.check_brief([page])]
        self.assertNotIn("vague-anchor", codes)

    def test_known_short_anchor_is_not_vague(self):
        from indexgap import content
        page = self.pages({"a/index.html": real_html(
            1, '<a href="/vk/">VK</a>')})[0]
        self.assertNotIn("vague-anchor", [i[2] for i in content.check_brief([page])])

    def test_a_really_vague_anchor_is_still_caught(self):
        from indexgap import content
        page = self.pages({"a/index.html": real_html(
            1, '<a href="/x/">тут</a>')})[0]
        self.assertIn("vague-anchor", [i[2] for i in content.check_brief([page])])


class TestTemplateWide(Fixture):
    def test_a_finding_on_every_page_is_named_a_template_property(self):
        issues = [("info", f"{SITE}/p{i}/", "no-question-headings", "…")
                  for i in range(40)]
        notes = checks.template_wide(issues, 40)
        self.assertTrue(notes and "шаблон" in notes[0], notes)

    def test_duplicates_are_never_called_a_template_property(self):
        issues = [("critical", f"{SITE}/p{i}/", "near-duplicate", "…")
                  for i in range(40)]
        self.assertEqual(checks.template_wide(issues, 40), [])

    def test_a_small_site_is_left_alone(self):
        issues = [("info", f"{SITE}/p{i}/", "no-date", "…") for i in range(8)]
        self.assertEqual(checks.template_wide(issues, 8), [])


class TestLiveDistributions(unittest.TestCase):
    """
    Пороги профилей проверялись на шести живых сайтах. Здесь закреплено то,
    что из этого следует для значений по умолчанию, чтобы правка их не сдвинула
    молча.
    """

    def test_thin_threshold_is_below_what_real_catalogues_write(self):
        from indexgap.profiles import PROFILES
        # На живом каталоге виз пятый перцентиль длины основного текста — 464
        # слова. Порог 250 стоит ниже: он ловит настоящий провал, а не норму.
        self.assertLess(PROFILES["catalog"]["checks"]["thin_words"], 464)

    def test_duplicate_threshold_is_above_the_bulk_of_real_pairs(self):
        from indexgap.profiles import PROFILES
        # На том же каталоге 99-й перцентиль похожести пар — 0,42,
        # а максимум 0,92. Порог 0,80 отделяет хвост от нормы.
        self.assertGreater(PROFILES["catalog"]["checks"]["near_duplicate"], 0.42)
        self.assertLess(PROFILES["catalog"]["checks"]["near_duplicate"], 0.92)


if __name__ == "__main__":
    unittest.main(verbosity=2)
