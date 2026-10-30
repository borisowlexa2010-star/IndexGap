# -*- coding: utf-8 -*-
"""
`doctor` под враждебной батареей: десять находок.

Выгрузка показов рядом с настоящими списками индекса читалась как индекс
Google, и страницы без показов объявлялись «нет только в Google». Список
«у первой страницы выдачи» не узнавал заголовков половины языков панели,
брал «Среднюю позицию показа» за показы, читал `3,000` как три, советовал
дорабатывать закрытые страницы, смешивал Bing с Google без подписи и не
складывал строки одной страницы. В консоль попадали ключи вместо адресов,
тонкие страницы всё ещё советовали убрать из индекса, а у причин и способа
поиска дублей в JSON не было стабильных кодов.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, core, doctor

SITE = "https://example.com"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-battery-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def site(self, names="abcde", closed=(), words=300):
        root = os.path.join(self.dir, "site")
        for name in names:
            os.makedirs(os.path.join(root, name), exist_ok=True)
            links = "".join(f'<a href="/{o}/">{o}</a>' for o in names if o != name)
            robots = '<meta name="robots" content="noindex">' if name in closed else ""
            with open(os.path.join(root, name, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f"<html><head><title>Страница {name} сайта</title>{robots}</head>"
                         f"<body><main><h1>{name}</h1><p>{'слово ' * words}</p>{links}"
                         "</main></body></html>")
        return root

    def pages(self, **kwargs):
        return core.load_pages(self.site(**kwargs), SITE)[0]

    def near(self, csv_text, pages=None, label="google", notes=None):
        path = self.write(f"{label}-perf.csv", csv_text)
        return doctor.near_page_one([f"{label}={path}"], pages or self.pages(), SITE,
                                    notes=notes)


PERFORMANCE = ("Top pages,Clicks,Impressions,CTR,Position\n"
               f"{SITE}/a/,3,40,7.5%,8\n")


class TestPerformanceExportIsNeverAnIndexList(Fixture):
    """Показы рядом со списками Bing и Яндекса — всё ещё показы."""

    def sources(self):
        google = self.write("google.csv", PERFORMANCE)
        bing = self.write("bing.csv", f"URL\n{SITE}/a/\n{SITE}/b/\n{SITE}/c/\n")
        yandex = self.write("yandex.csv", f"URL\n{SITE}/a/\n{SITE}/b/\n{SITE}/c/\n")
        return doctor.read_sources([f"google={google}", f"bing={bing}", f"yandex={yandex}"])

    def test_it_is_marked_as_impressions_next_to_index_lists(self):
        self.assertEqual(self.sources()["impressions"], ["google"])

    def test_cross_engine_does_not_judge_google_by_impressions(self):
        got = self.sources()
        funnel = doctor.funnel(self.pages(names="abc"), by_engine=got["by_engine"],
                               impressions=got["impressions"])
        cross = doctor.cross_engine(funnel, self.pages(names="abc"))
        self.assertFalse([c for c in cross if c.get("engine") == "google"], cross)
        everywhere = next(c for c in cross if c["id"] == "everywhere")
        self.assertEqual(everywhere["count"], 3)
        self.assertNotIn("google", funnel["panel_keys"])

    def test_two_engines_one_of_them_impressions_are_not_compared(self):
        bing = [f"{SITE}/a/", f"{SITE}/b/"]
        funnel = doctor.funnel(self.pages(names="abc"),
                               by_engine={"google": [f"{SITE}/a/"], "bing": bing},
                               impressions=["google"])
        self.assertEqual(doctor.cross_engine(funnel, self.pages(names="abc")), [])
        self.assertTrue(any("google" in n and "показ" in n for n in funnel["foreign"]),
                        funnel["foreign"])

    def test_the_per_source_step_is_about_impressions(self):
        funnel = doctor.funnel(self.pages(names="abc"),
                               by_engine={"google": [f"{SITE}/a/"],
                                          "bing": [f"{SITE}/a/", f"{SITE}/b/"]},
                               impressions=["google"])
        step = next(s for s in funnel["steps"] if s.get("engine") == "google")
        self.assertEqual(step.get("measure"), "impressions")
        self.assertIn("показ", step["name"])
        self.assertIn("показов", step["why"])
        bing = next(s for s in funnel["steps"] if s.get("engine") == "bing")
        self.assertNotEqual(bing.get("measure"), "impressions")

    def test_doctor_json_has_no_google_quality_judgement(self):
        root = self.site(names="abc")
        google = self.write("google.csv", PERFORMANCE)
        bing = self.write("bing.csv", f"URL\n{SITE}/a/\n{SITE}/b/\n{SITE}/c/\n")
        yandex = self.write("yandex.csv", f"URL\n{SITE}/a/\n{SITE}/b/\n{SITE}/c/\n")
        out = os.path.join(self.dir, "doc.json")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cli.main(["doctor", root, "--site", SITE, "--out", out,
                      "--indexed", f"google={google}", "--indexed", f"bing={bing}",
                      "--indexed", f"yandex={yandex}"])
        data = json.load(open(out, encoding="utf-8"))
        self.assertFalse([c for c in data["cross_engine"] if c.get("engine") == "google"],
                         data["cross_engine"])


class TestPositionHeadersInMoreLanguages(Fixture):
    HEADERS = {
        "pt": "Páginas principais,Cliques,Impressões,CTR,Posição",
        "id": "Halaman teratas,Klik,Tayangan,CTR,Posisi",
        "tr": "En çok tıklanan sayfalar,Tıklamalar,Gösterimler,TO,Konum",
        "tr2": "En çok tıklanan sayfalar,Tıklamalar,Gösterimler,TO,Sıralama",
        "vi": "Trang hàng đầu,Lượt nhấp,Số lần hiển thị,CTR,Vị trí",
        "uk": "Найпопулярніші сторінки,Кліки,Покази,CTR,Позиція",
    }

    def test_every_language_gives_its_page(self):
        pages = self.pages(names="a")
        for lang, header in self.HEADERS.items():
            near = self.near(f"{header}\n{SITE}/a/,4,900,0.4%,11.0\n", pages)
            self.assertEqual([(r["url"], r["impressions"], r["position"]) for r in near],
                             [(SITE + "/a/", 900, 11.0)], lang)

    def test_they_are_read_as_impressions_exports(self):
        for lang in ("id", "vi"):
            path = self.write("p.csv", f"{self.HEADERS[lang]}\n{SITE}/a/,4,900,0.4%,11\n")
            self.assertEqual(doctor.read_sources([f"google={path}"])["impressions"],
                             ["google"], lang)

    def test_no_position_column_is_said_out_loud(self):
        notes = []
        near = self.near(f"Top pages,Clicks,Impressions,Средний ранг\n{SITE}/a/,4,900,11\n",
                         self.pages(names="a"), notes=notes)
        self.assertEqual(near, [])
        self.assertTrue(any("google-perf.csv" in n and "позици" in n for n in notes), notes)

    def test_an_index_list_is_still_silent(self):
        notes = []
        self.near(f"URL,Last crawled\n{SITE}/a/,2026-10-01\n", self.pages(names="a"),
                  notes=notes)
        self.assertEqual(notes, [])


class TestColumnsAreMatchedWhole(Fixture):
    def test_average_impression_position_is_not_impressions(self):
        near = self.near("Страница,Средняя позиция показа,Показы,Клики\n"
                         f"{SITE}/a/,9.4,3000,40\n", self.pages(names="a"))
        self.assertEqual([(r["impressions"], r["position"]) for r in near], [(3000, 9.4)])

    def test_bing_click_position_is_not_clicks(self):
        near = self.near("URL,Avg. Click Position,Clicks,Impressions\n"
                         f"{SITE}/a/,12.0,7,900\n", self.pages(names="a"), label="bing")
        self.assertEqual([(r["clicks"], r["impressions"], r["position"]) for r in near],
                         [(7, 900, 12.0)])


class TestThousands(Fixture):
    def test_integer_counts_read_their_thousands(self):
        for raw in ("3,000", "3.000", "3 000", "3 000", "3 000", "3000"):
            self.assertEqual(doctor._number(raw, integer=True), 3000, raw)
        self.assertEqual(doctor._number("1.234.567", integer=True), 1234567)

    def test_a_position_keeps_its_decimal_comma(self):
        self.assertEqual(doctor._number("9,4"), 9.4)
        self.assertEqual(doctor._number("9.4"), 9.4)

    def test_quoted_thousands_in_an_export(self):
        near = self.near('Top pages,Clicks,Impressions,CTR,Position\n'
                         f'{SITE}/a/,40,"3,000",1.3%,"9,4"\n'
                         f'{SITE}/b/,4,"1.234",0.3%,12\n', self.pages(names="ab"))
        self.assertEqual([(r["url"], r["impressions"], r["position"]) for r in near],
                         [(SITE + "/a/", 3000, 9.4), (SITE + "/b/", 1234, 12.0)])


class TestClosedPagesAreNotCheapWins(Fixture):
    def test_noindex_page_is_not_listed(self):
        pages = self.pages(names="ab", closed="b")
        near = self.near("Top pages,Clicks,Impressions,CTR,Position\n"
                         f"{SITE}/a/,4,900,0.4%,11\n{SITE}/b/,4,5000,0.1%,10\n", pages)
        self.assertEqual([r["url"] for r in near], [SITE + "/a/"])


class TestEnginesAreNamed(Fixture):
    def test_each_row_names_its_engine_and_the_other_position(self):
        pages = self.pages(names="a")
        google = self.write("g.csv", "Top pages,Clicks,Impressions,CTR,Position\n"
                                     f"{SITE}/a/,0,700,0%,35\n")
        bing = self.write("b.csv", "URL,Clicks,Impressions,Avg. Click Position\n"
                                   f"{SITE}/a/,3,400,10\n")
        near = doctor.near_page_one([f"google={google}", f"bing={bing}"], pages, SITE)
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0]["engine"], "bing")
        self.assertEqual(near[0]["elsewhere"], {"google": 35.0})

    def test_doctor_prints_the_engine(self):
        root = self.site(names="a")
        bing = self.write("b.csv", "URL,Clicks,Impressions,Avg. Click Position\n"
                                   f"{SITE}/a/,3,400,10\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["doctor", root, "--site", SITE, "--indexed", f"bing={bing}",
                      "--out", os.path.join(self.dir, "doc.json")])
        line = next(l for l in buf.getvalue().splitlines() if l.rstrip().endswith("/a/"))
        self.assertIn("bing", line)


class TestSplitRowsAreSummed(Fixture):
    def test_fragments_and_schemes_are_one_page(self):
        near = self.near("Top pages,Clicks,Impressions,CTR,Position\n"
                         f"{SITE}/a/,10,30,0%,6\n"
                         f"{SITE}/a/#prices,5,30,0%,12\n"
                         f"http://example.com/a/,1,40,0%,15\n", self.pages(names="a"))
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0]["impressions"], 100)
        self.assertEqual(near[0]["clicks"], 16)
        # (6·30 + 12·30 + 15·40) / 100
        self.assertEqual(near[0]["position"], 11.4)

    def test_tracking_parameters_fold_into_the_clean_url(self):
        near = self.near("Top pages,Clicks,Impressions,CTR,Position\n"
                         f"{SITE}/a/,1,30,0%,10\n"
                         f"{SITE}/a/?utm_source=newsletter&utm_medium=email,1,30,0%,10\n",
                         self.pages(names="a"))
        self.assertEqual([(r["url"], r["impressions"]) for r in near], [(SITE + "/a/", 60)])


class TestForeignAddressesAreUrls(Fixture):
    def test_foreign_lists_hold_exported_urls(self):
        funnel = doctor.funnel(self.pages(names="a"), by_engine={"google": [
            f"{SITE}/a/", "https://www.example.com/rent/nowhere/",
            "https://stage.example.com/login"]})
        foreign = doctor.foreign_urls(funnel, SITE)
        self.assertEqual(foreign["missing"], ["https://www.example.com/rent/nowhere/"])
        self.assertEqual(foreign["other_hosts"], ["https://stage.example.com/login"])

    def test_doctor_prints_and_stores_urls(self):
        root = self.site(names="a")
        index = self.write("google.csv", f"URL,Last crawled\n{SITE}/a/,2026-10-01\n"
                                         f"{SITE}/rent/nowhere/,2026-10-01\n")
        out = os.path.join(self.dir, "doc.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["doctor", root, "--site", SITE, "--indexed", f"google={index}",
                      "--out", out])
        self.assertIn(f"{SITE}/rent/nowhere/", buf.getvalue())
        self.assertNotIn(" //example.com/rent/nowhere", buf.getvalue())
        data = json.load(open(out, encoding="utf-8"))
        self.assertEqual(data["foreign"]["missing"], [f"{SITE}/rent/nowhere/"])


class TestCauses(Fixture):
    def analysis_and_funnel(self):
        pages = self.pages(names="abc", words=20)
        analysis = checks.run_all(pages, SITE + "/a/")
        funnel = doctor.funnel(pages, by_engine={"google": [f"{SITE}/a/"],
                                                 "bing": [f"{SITE}/a/"]})
        return analysis, funnel

    def test_thin_pages_are_not_told_to_leave_the_index(self):
        causes = doctor.explain(*reversed(self.analysis_and_funnel()))
        thin = next(c for c in causes if c.get("id") == "thin")
        self.assertNotIn("из индекса", thin["fix"])
        self.assertNotIn("noindex", thin["fix"])
        self.assertIn("объедин", thin["fix"])

    def test_every_cause_has_a_stable_id(self):
        causes = doctor.explain(*reversed(self.analysis_and_funnel()))
        self.assertTrue(causes)
        for cause in causes:
            self.assertRegex(cause.get("id", ""), r"^[a-z]+(-[a-z]+)*$", cause)

    def test_every_kind_of_cause_has_its_own_id(self):
        known = {"orphans", "near-duplicates", "thin", "too-deep", "no-title",
                 "no-impressions", "unexplained"}
        analysis, funnel = self.analysis_and_funnel()
        ids = {c["id"] for c in doctor.explain(funnel, analysis)}
        self.assertTrue(ids <= known, ids)
        funnel["impressions_only"] = True
        analysis["pages"] = []
        ids = {c["id"] for c in doctor.explain(funnel, analysis)}
        self.assertIn("no-impressions", ids)


class TestDuplicateMethodIsACode(Fixture):
    def test_check_json_has_a_code_and_a_label(self):
        root = self.site(names="abc")
        out = os.path.join(self.dir, "check.json")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cli.main(["check", root, "--site", SITE, "--out", out])
        data = json.load(open(out, encoding="utf-8"))
        self.assertEqual(data["duplicate_method"], "pairwise")
        self.assertEqual(data["duplicate_method_label"], "попарное сравнение")

    def test_find_near_duplicates_gives_the_code(self):
        pages = self.pages(names="ab")
        self.assertEqual(checks.find_near_duplicates(pages)["method_id"], "pairwise")
        self.assertEqual(checks.find_near_duplicates(pages[:1])["method_id"], "none")


if __name__ == "__main__":
    unittest.main()


class ExportCap(Fixture):
    """Выгрузка из интерфейса Search Console обрезана на 1000 строк."""

    def test_exactly_a_thousand_rows_is_said_out_loud(self):
        rows = "".join(f"{SITE}/p{i}/\n" for i in range(1000))
        path = self.write("g.csv", "URL\n" + rows)
        result = doctor.read_sources([f"google={path}"])
        self.assertTrue(any("1000" in n for n in result["notes"]), result["notes"])

    def test_a_shorter_list_is_silent(self):
        rows = "".join(f"{SITE}/p{i}/\n" for i in range(999))
        path = self.write("g.csv", "URL\n" + rows)
        result = doctor.read_sources([f"google={path}"])
        self.assertFalse(any("1000" in n for n in result["notes"]), result["notes"])
