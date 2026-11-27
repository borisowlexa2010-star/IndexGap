# -*- coding: utf-8 -*-
"""
1.29 (g25): чужие входные данные и инварианты.

Шаблоны robots.txt и `_headers` из `*` считаются за линейное время; индекс
sitemap с диска не ходит в сеть; DOCTYPE после длинного комментария
отклоняется; портфель, шарды sitemap и trend.html не затирают чужие файлы;
испорченный прогон в истории не роняет doctor; zip с таблицами ограничен
целиком; невидимые знаки и <wbr> не ломают сверку чисел; плоские адреса
клонов образуют раздел шаблона.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, cli, core, doctor, generate, history, publish, sources
from indexgap.core import SourceError

SITE = "https://example.com"
DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "examples", "demo-site")


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-g25-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, text, mode="w"):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
            fh.write(text)
        return path

    def page(self, rel, title="Главная страница", body=None):
        body = body or f"<p>{'слово ' * 80}</p>"
        return self.write(rel, f"<html><head><title>{title}</title></head><body><main>"
                               f"<h1>Заголовок</h1>{body}</main></body></html>")


class Wildcards(unittest.TestCase):
    """#399, #400: `*a*a*a…b` не подвешивает проверку."""

    EVIL = "/" + "*a" * 14 + "*b"

    def test_robots_rule_is_linear(self):
        robots = {"found": True, "rules": {"*": {"disallow": [self.EVIL], "allow": []}}}
        started = time.time()
        self.assertTrue(aeo.robots_allows(robots, "/" + "a" * 60 + "/"))
        self.assertLess(time.time() - started, 1.0)

    def test_robots_semantics_kept(self):
        cases = [("/private", "/private/x", True), ("/*.pdf$", "/a/b.pdf", True),
                 ("/*.pdf$", "/a/b.pdf?x", False), ("/a*b", "/axxb/c", True),
                 ("/a*b", "/ac", False), ("/x$", "/x", True), ("/x$", "/x/", False),
                 ("/*a*a", "/aa", True), ("/*ab$", "/abab", True)]
        for rule, path, blocked in cases:
            with self.subTest(rule=rule, path=path):
                self.assertEqual(bool(aeo._robots_pattern(rule).match(path)), blocked)

    def test_headers_route_is_linear(self):
        regex = core._route_regex(self.EVIL)
        started = time.time()
        self.assertFalse(regex.match("/" + "a" * 60 + "/"))
        self.assertLess(time.time() - started, 1.0)
        self.assertTrue(core._route_regex("/a*b").match("/axb"))
        self.assertFalse(core._route_regex("/a*b").match("/axbc"))
        self.assertFalse(core._route_regex("/a.b/x").match("/aXb/x"))


class LocalIndex(Temp):
    """#401: индекс с диска не посылает запросов в сеть."""

    def test_remote_child_of_a_local_index_is_not_fetched(self):
        path = self.write("sitemap.xml",
                          '<?xml version="1.0"?><sitemapindex '
                          'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap>'
                          '<loc>http://127.0.0.1:9/internal.xml</loc></sitemap></sitemapindex>')
        with mock.patch("urllib.request.urlopen") as net:
            result = doctor.read_sitemap(path)
        net.assert_not_called()
        self.assertEqual(result["urls"], [])
        self.assertIn("--sitemap", result["error"])

    def test_child_saved_next_to_the_index_is_still_read(self):
        self.write("en/sitemap.xml", '<?xml version="1.0"?><urlset '
                   'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                   '<url><loc>https://example.com/a/</loc></url></urlset>')
        path = self.write("sitemap.xml", '<?xml version="1.0"?><sitemapindex '
                          'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap>'
                          '<loc>https://example.com/en/sitemap.xml</loc></sitemap></sitemapindex>')
        self.assertEqual(doctor.read_sitemap(path)["urls"], ["https://example.com/a/"])


class Doctype(unittest.TestCase):
    """#404: DOCTYPE за длинным комментарием тоже отклоняется."""

    def test_doctype_after_a_long_comment(self):
        data = ('<?xml version="1.0"?><!--' + "x" * 70000 + '--><!DOCTYPE urlset '
                '[<!ENTITY h "https://example.com/">]><urlset><url><loc>&h;</loc></url></urlset>')
        with self.assertRaises(SourceError):
            core.parse_xml(data)

    def test_plain_xml_after_a_long_comment_is_read(self):
        data = '<?xml version="1.0"?><!--' + "x" * 70000 + '--><urlset><url/></urlset>'
        self.assertEqual(core.parse_xml(data).tag, "urlset")


class Portfolio(Temp):
    """#402: отчёт проекта не затирает чужой файл, имена в --reports не сталкиваются."""

    def setUp(self):
        super().setUp()
        self.page("site/index.html")

    def portfolio(self, projects):
        return self.write("cfg/pf.json", json.dumps({"projects": projects}))

    def test_foreign_out_is_refused(self):
        victim = self.write("victim.md", "заметки")
        cfg = self.portfolio([{"name": "alpha", "root": "../site", "site": SITE,
                               "out": "../victim.md"}])
        code, _ = run(["portfolio", cfg, "--out", os.path.join(self.dir, "pf.html")])
        self.assertNotEqual(code, 0)
        with open(victim, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "заметки")

    def test_colliding_names_get_distinct_files(self):
        cfg = self.portfolio([{"name": "beta/x", "root": "../site", "site": SITE},
                              {"name": "beta x", "root": "../site", "site": "https://shop.example"}])
        reports = os.path.join(self.dir, "reps")
        code, _ = run(["portfolio", cfg, "--reports", reports,
                       "--out", os.path.join(self.dir, "pf.html")])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(f for f in os.listdir(reports) if f.endswith(".html")),
                         ["beta-x-2.html", "beta-x.html"])


class Brief(Temp):
    """#403: ни имя колонки, ни `--!>` не закрывают комментарий задания."""

    def test_column_name_and_bang_form(self):
        self.assertNotIn("--!>", generate._brief_value("a--!><img>"))
        self.assertNotIn("-->", generate._brief_value("a--><b>"))
        ds = self.write("ds.csv", 'keyword,"note--><script>x</script>",price\n'
                                  'rent berlin,"a--!><img src=x>",$1\n')
        out = os.path.join(self.dir, "content")
        code, _ = run(["plan", ds, "--out-dir", out, "--write"])
        self.assertEqual(code, 0)
        texts = []
        for folder, _dirs, files in os.walk(out):
            for name in files:
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    texts.append(fh.read())
        self.assertTrue(texts)
        for text in texts:
            start = text.index("<!--")
            self.assertNotIn("-->", text[start + 4:text.rindex("-->")])
            self.assertNotIn("--!>", text)


class Shards(Temp):
    """#405: чужой sitemap-N.xml без --force не заменяется."""

    def test_foreign_shard_is_kept(self):
        for i in range(3):
            self.page(f"site/p{i}/index.html", title=f"Страница номер {i}")
        foreign = self.write("site/sitemap-1.xml", "ЧУЖОЙ")
        pages = core.load_pages(os.path.join(self.dir, "site"), SITE)[0]
        with mock.patch.object(publish, "MAX_URLS_PER_FILE", 1):
            with self.assertRaises(SourceError):
                publish.build_sitemap(pages, os.path.join(self.dir, "site"), SITE,
                                      manifest={}, force=False)
            with open(foreign, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "ЧУЖОЙ")
            self.assertFalse(os.path.exists(os.path.join(self.dir, "site", "sitemap.xml")))
            result = publish.build_sitemap(pages, os.path.join(self.dir, "site"), SITE,
                                           manifest={}, force=True)
            self.assertIn(os.path.normpath(foreign), [os.path.normpath(f) for f in result["files"]])
            # Свои шарды следующего прогона заменяются без --force.
            publish.build_sitemap(pages, os.path.join(self.dir, "site"), SITE,
                                  manifest=result["manifest"], force=False)


class History(Temp):
    """#406, #407: испорченный прогон и чужой trend.html."""

    def test_series_skips_damaged_runs(self):
        self.write("h/runs/2026-11-01T10-00-00.json", "[1, 2]")
        self.write("h/runs/2026-11-02T10-00-00.json",
                   json.dumps({"funnel": {"steps": [{"id": "generated", "count": "7"}, 5]}}))
        data = history.series(os.path.join(self.dir, "h"))
        # Оба прогона повреждены: в графике их нет, и он всё равно строится.
        self.assertEqual(list(data["lines"].values()), [])
        self.assertTrue(history.render(os.path.join(self.dir, "h")).endswith("trend.html"))

    def test_own_trend_is_recognised_and_foreign_is_not(self):
        root = os.path.join(self.dir, "h")
        os.makedirs(root)
        self.assertEqual(history.foreign_trend(root), "")
        history.render(root)
        self.assertEqual(history.foreign_trend(root), "")
        self.write("h/trend.html", "<html>свой график</html>")
        self.assertTrue(history.foreign_trend(root))

    def test_doctor_refuses_a_foreign_trend_and_survives_a_bad_baseline(self):
        self.page("site/index.html")
        sm = self.write("s.xml", '<?xml version="1.0"?><urlset '
                        'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        '<url><loc>https://example.com/</loc></url></urlset>')
        trend = self.write("h/trend.html", "<html>свой график</html>")
        code, text = run(["doctor", os.path.join(self.dir, "site"), "--site", SITE,
                          "--sitemap", sm, "--history", os.path.join(self.dir, "h"),
                          "--out", os.path.join(self.dir, "d.html")])
        self.assertNotEqual(code, 0)
        self.assertIn("trend.html", text)
        with open(trend, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "<html>свой график</html>")
        base = self.write("bl.json", json.dumps(
            {"funnel": {"steps": [{"id": "generated", "count": "7"}]}}))
        code, text = run(["doctor", os.path.join(self.dir, "site"), "--site", SITE,
                          "--sitemap", sm, "--baseline", base, "--out", os.path.join(self.dir, "d2.html")])
        # Повреждённая база — понятная ошибка, а не трассировка.
        self.assertEqual(code, 2, text)
        self.assertNotIn("Traceback", text)
        self.assertIn("поврежден", text)


class ZipTotal(Temp):
    """#408: потолок — на все таблицы архива вместе."""

    def test_total_size_is_capped(self):
        path = os.path.join(self.dir, "export.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for i in range(3):
                archive.writestr(f"Table{i}.csv", "https://example.com/a,1\n" * 100)
        with mock.patch.object(core, "MAX_INPUT_BYTES", 5000):
            with self.assertRaises(SourceError):
                sources._read_zip_tables(path)
        self.assertTrue(sources._read_zip_tables(path))


class Numbers(Temp):
    """#410, #413: невидимые знаки и <wbr> рядом с ценой."""

    def check(self, replacement):
        site = os.path.join(self.dir, "site")
        shutil.rmtree(site, True)
        shutil.copytree(DEMO, site)
        page = os.path.join(site, "rent", "hamburg", "index.html")
        with open(page, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("$1,900", text)
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(text.replace("$1,900", replacement))
        out = os.path.join(self.dir, "out", "r.html")
        run(["check", site, "--site", "https://demo.example",
             "--dataset", os.path.join(site, "cities.csv"), "--out", out])
        with open(os.path.join(self.dir, "out", "r.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return [i["message"] for i in data["issues"]
                if "hamburg" in i["url"] and i["code"] == "unsupported-number"]

    def test_zero_width_does_not_hide_a_wrong_price(self):
        for mark in ("&#8203;", "⁠", "﻿"):
            with self.subTest(mark=repr(mark)):
                self.assertTrue(self.check("$" + mark + "1,900"))

    def test_split_correct_price_is_not_invented(self):
        for form in ("$1,<wbr>600", "$1<wbr>,600", "$1,6&shy;00"):
            with self.subTest(form=form):
                self.assertEqual(self.check(form), [])

    def test_zero_width_in_title_is_still_a_duplicate(self):
        self.page("s/a/index.html", title="Аренда в Берлине: цены")
        self.page("s/b/index.html", title="Аренда в Берлине​: цены")
        pages = core.load_pages(os.path.join(self.dir, "s"), SITE)[0]
        codes = [i[2] for i in checks.technical_issues(pages)]
        self.assertEqual(codes.count("duplicate-title"), 2)


class FlatClones(Temp):
    """#409: клоны `/rent-<город>/` — раздел шаблона, как `/rent/<город>/`."""

    TEMPLATE = ("Finding a flat here follows the same routine as in every large city. "
                "Bring a credit report, three payslips and a copy of your passport to "
                "every viewing. Group viewings are normal and the agent collects folders "
                "at the door. Deposits are paid into a separate account and returned "
                "with interest when you leave. Most leases are open ended. ") * 2
    CITIES = ["berlin", "munich", "hamburg", "cologne", "bremen", "essen", "bonn",
              "kiel", "mainz"]

    def shares(self, flat):
        site = os.path.join(self.dir, "flat" if flat else "nest")
        for c in self.CITIES:
            rel = f"rent-{c}" if flat else f"rent/{c}"
            self.write(os.path.join(site, rel, "index.html"),
                       f'<html lang="en"><head><title>Renting in {c}</title></head><body>'
                       f'<main><h1>Renting in {c}</h1><p>Renting in {c}.</p>'
                       f'<p>{self.TEMPLATE}</p></main></body></html>')
        for k, word in enumerate(["orange planet bridge", "silver forest candle",
                                  "thunder pebble falcon"]):
            self.write(os.path.join(site, f"about{k}", "index.html"),
                       f'<html lang="en"><head><title>About {k}</title></head><body><main>'
                       f'<h1>About {k}</h1><p>{(word + " velvet tulip anchor ") * 40} {k}</p>'
                       '</main></body></html>')
        pages = core.load_pages(site, SITE)[0]
        shares = checks.boilerplate_profile(pages)["shares"]
        return [v for u, v in shares.items() if "rent" in u]

    def test_flat_and_nested_agree(self):
        flat, nested = self.shares(True), self.shares(False)
        self.assertEqual(len(flat), len(self.CITIES))
        self.assertLess(max(nested), 0.2)
        self.assertLess(max(flat), 0.2)


if __name__ == "__main__":
    unittest.main()
