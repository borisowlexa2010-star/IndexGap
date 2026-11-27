# -*- coding: utf-8 -*-
"""
1.30 (sitemap): хэш содержимого, вердикт поисковика и сравнение в HTML.

* хэш не видел знаков: $900 → €900, -5 → +5 и 1,500 → 1.500 не двигали
  `lastmod` и не ставили страницу в очередь IndexNow. Версия 2 знаки видит,
  а манифест со старыми хэшами переходит на неё молча — без нового `lastmod`
  и без отправки всего сайта;
* выгрузка, где поисковик называет все адреса не проиндексированными,
  убирала шаг индекса из воронки: отчёт зеленел, а --baseline молчал;
* HTML-отчёт doctor не показывал сравнения с прошлым прогоном.
"""

import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, doctor, publish, report

SITE = "https://example.com"
KEY = "0123456789abcdef0123456789abcdef"
TEXT = "Средняя аренда $900 в месяц, минимум -5 C, залог 1,500."


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def html_page(title, body):
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<title>{title}</title></head>'
            f'<body><main><h1>{title}</h1><p>{body}</p></main></body></html>')


def legacy_hash(page):
    """Хэш версии 1 — как его писали пакеты до 1.30."""
    payload = "\x00".join([(page.title or "").strip(), (page.description or "").strip(),
                           " ".join(re.findall(r"\w+", (page.text or "").lower()))])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run(*argv):
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, printed.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-130-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)


# ── #147: хэш содержимого версии 2 ─────────────────────────────────────────────

class TestHashSeesSigns(unittest.TestCase):
    def page(self, text):
        return core.Page(path="a.html", url=SITE + "/a/", text=text, title="Цена")

    def test_currency_sign_and_decimal_changes_change_the_hash(self):
        base = self.page(TEXT).content_hash
        for changed in (TEXT.replace("$900", "€900"), TEXT.replace("-5", "+5"),
                        TEXT.replace("1,500", "1.500")):
            self.assertNotEqual(self.page(changed).content_hash, base, changed)

    def test_hash_carries_its_version(self):
        self.assertTrue(self.page(TEXT).content_hash.startswith("v2:"))

    def test_invisible_characters_and_spacing_do_not_change_it(self):
        base = self.page(TEXT).content_hash
        self.assertEqual(self.page(TEXT.replace("аренда", "арен­да")).content_hash, base)
        self.assertEqual(self.page(TEXT.replace(" ", "  \n")).content_hash, base)

    def test_legacy_hash_is_the_old_algorithm(self):
        page = self.page(TEXT)
        self.assertEqual(page.legacy_content_hash, legacy_hash(page))


class TestManifestUpgrade(Base):
    def pages(self, text):
        write(self.path("site", "index.html"), html_page("Главная", "Обычный текст главной."))
        write(self.path("site", "price", "index.html"), html_page("Цена", text))
        pages, _ = core.load_pages(self.path("site"), SITE)
        return pages

    def old_manifest(self, pages):
        """Манифест пакета до 1.30: хэши без версии, всё отправлено."""
        return {p.url: {"hash": legacy_hash(p), "lastmod": "2025-01-01",
                        "notified": legacy_hash(p)} for p in pages}

    def test_old_manifest_keeps_lastmod_and_queues_nothing(self):
        pages = self.pages(TEXT)
        manifest = self.old_manifest(pages)
        result = publish.build_sitemap(pages, self.path("out"), SITE, manifest=manifest,
                                       today="2026-11-27")
        with open(self.path("out", "sitemap.xml"), encoding="utf-8") as fh:
            xml = fh.read()
        self.assertNotIn("2026-11-27", xml)
        self.assertEqual(xml.count("<lastmod>2025-01-01</lastmod>"), 2)
        for p in pages:
            entry = result["manifest"][p.url]
            # Тихо переведено на новый хэш — и отметка об отправке тоже.
            self.assertEqual(entry["hash"], p.content_hash)
            self.assertEqual(entry["notified"], p.content_hash)
            self.assertEqual(entry["lastmod"], "2025-01-01")
        diff = publish.diff_changed(pages, manifest)
        self.assertEqual((diff["new"], diff["changed"]), ([], []))
        diff = publish.diff_changed(pages, result["manifest"])
        self.assertEqual((diff["new"], diff["changed"]), ([], []))

        # После перехода смена знака — уже изменение.
        changed = self.pages(TEXT.replace("$900", "€900"))
        again = publish.build_sitemap(changed, self.path("out"), SITE,
                                      manifest=result["manifest"], today="2026-11-28")
        price = SITE + "/price/"
        self.assertEqual(again["manifest"][price]["lastmod"], "2026-11-28")
        self.assertEqual(again["manifest"][SITE + "/"]["lastmod"], "2025-01-01")
        self.assertEqual(publish.diff_changed(changed, again["manifest"])["changed"], [price])

    def test_old_hash_that_no_longer_matches_is_a_real_change(self):
        pages = self.pages(TEXT)
        manifest = self.old_manifest(pages)
        price = SITE + "/price/"
        reworded = self.pages(TEXT.replace("Средняя аренда", "Обычная аренда"))
        result = publish.build_sitemap(reworded, self.path("out"), SITE, manifest=manifest,
                                       today="2026-11-27")
        self.assertEqual(result["manifest"][price]["lastmod"], "2026-11-27")
        self.assertTrue(result["manifest"][price]["hash"].startswith("v2:"))
        # Отметка об отправке не переписана: страница ещё не отправлена.
        self.assertEqual(result["manifest"][price]["notified"], manifest[price]["notified"])
        self.assertEqual(publish.diff_changed(reworded, result["manifest"])["changed"], [price])

    def test_mark_notified_upgrades_matching_entries(self):
        pages = self.pages(TEXT)
        manifest = self.old_manifest(pages)
        out = publish.mark_notified(manifest, pages, [SITE + "/price/"])
        for p in pages:
            self.assertEqual(out[p.url]["notified"], p.content_hash)
            self.assertTrue(out[p.url]["notified"].startswith("v2:"))

    def test_cli_sitemap_and_notify_on_an_old_manifest(self):
        pages = self.pages(TEXT)
        manifest_path = self.path("manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(self.old_manifest(pages), fh)
        site = self.path("site")
        code, out = run("sitemap", site, "--site", SITE, "--manifest", manifest_path)
        self.assertEqual(code, 0, out)
        with open(os.path.join(site, "sitemap.xml"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("2025-01-01"), 2)
        code, out = run("notify", site, "--site", SITE, "--key", KEY,
                        "--manifest", manifest_path)
        self.assertIn("Отправлять нечего", out)
        self.pages(TEXT.replace("-5", "+5"))
        code, out = run("notify", site, "--site", SITE, "--key", KEY,
                        "--manifest", manifest_path)
        self.assertIn(SITE + "/price/", out)
        self.assertIn("Изменённых: 1", out)

    def test_notify_send_with_nothing_to_send_saves_the_upgrade(self):
        pages = self.pages(TEXT)
        manifest_path = self.path("manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(self.old_manifest(pages), fh)
        code, out = run("notify", self.path("site"), "--site", SITE, "--key", KEY,
                        "--manifest", manifest_path, "--send")
        self.assertEqual(code, 0, out)
        with open(manifest_path, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertTrue(all(saved[p.url]["notified"].startswith("v2:") for p in pages))


# ── #270: вердикт поисковика «не в индексе» ────────────────────────────────────

def page(slug):
    return core.Page(path=f"{slug}.html", url=f"{SITE}/{slug}/", text="текст " * 50,
                     title=slug)


REASON = "Crawled - currently not indexed"


class TestRejectedFunnel(unittest.TestCase):
    def setUp(self):
        self.pages = [page(s) for s in "abcdefg"]
        self.sitemap = [p.url for p in self.pages]

    def test_rejection_only_export_keeps_the_index_step(self):
        rejected = {"google": {f"{SITE}/{s}/": REASON for s in "abcd"}}
        f = doctor.funnel(self.pages, self.sitemap, rejected=rejected)
        step = [s for s in f["steps"] if s["id"] == "indexed"]
        self.assertEqual(len(step), 1)
        self.assertEqual((step[0]["lost"], step[0]["count"]), (4, 3))
        self.assertTrue(step[0]["partial"])
        self.assertTrue(f["has_index"])
        # Неназванные страницы потерянными не считаются.
        self.assertEqual(f["not_indexed"], [f"{SITE}/{s}/" for s in "abcd"])
        self.assertEqual(f["not_indexed_reasons"], {f"{SITE}/{s}/": REASON for s in "abcd"})
        self.assertTrue(any("ничего не говорит" in n for n in f["foreign"]), f["foreign"])

    def test_mixed_export_attaches_reasons_to_lost_pages(self):
        f = doctor.funnel(self.pages, self.sitemap, by_engine={"google": [f"{SITE}/a/"]},
                          rejected={"google": {f"{SITE}/b/": REASON}})
        self.assertEqual(f["not_indexed_reasons"], {f"{SITE}/b/": REASON})
        self.assertFalse(f["index_partial"])
        self.assertEqual(len(f["not_indexed"]), 6)

    def test_page_indexed_elsewhere_is_not_lost(self):
        f = doctor.funnel(self.pages, self.sitemap, by_engine={"bing": [f"{SITE}/a/"]},
                          rejected={"google": {f"{SITE}/a/": REASON}})
        self.assertNotIn(f"{SITE}/a/", f["not_indexed"])
        self.assertEqual(f["not_indexed_reasons"], {})

    def test_baseline_reports_the_rejected_pages_as_dropped(self):
        before = doctor.funnel(self.pages, self.sitemap,
                               by_engine={"google": [f"{SITE}/{s}/" for s in "abcd"]})
        after = doctor.funnel(self.pages, self.sitemap,
                              rejected={"google": {f"{SITE}/{s}/": REASON for s in "abcd"}})
        trend = doctor.compare_runs({"funnel": after}, {"funnel": before})
        self.assertEqual(trend["newly_not_indexed"], [f"{SITE}/{s}/" for s in "abcd"])
        self.assertEqual(trend["not_compared"], [])
        self.assertIsNone(trend["index_sources"])
        # «Не отклонено» и «в индексе» — разные счёты, их разница не движение.
        self.assertNotIn("indexed", [s["id"] for s in trend["steps"]])
        self.assertTrue(doctor.valid_run({"funnel": after}))

    def test_two_rejection_only_runs_do_not_invent_drops(self):
        one = doctor.funnel(self.pages, self.sitemap,
                            rejected={"google": {f"{SITE}/a/": REASON}})
        two = doctor.funnel(self.pages, self.sitemap,
                            rejected={"google": {f"{SITE}/{s}/": REASON for s in "ab"}})
        trend = doctor.compare_runs({"funnel": two}, {"funnel": one})
        self.assertEqual(trend["newly_not_indexed"], [])
        self.assertEqual(trend["recovered"], [])


class TestRejectedDoctor(Base):
    def setUp(self):
        super().setUp()
        for s in ("", "a", "b", "c", "d", "e"):
            write(self.path("site", s, "index.html"),
                  html_page(f"Страница {s or 'главная'}", "Текст страницы. " * 40))
        urls = [f"{SITE}/{s}/" if s else f"{SITE}/" for s in ("", "a", "b", "c", "d", "e")]
        write(self.path("sitemap.xml"),
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
        self.listed = urls[1:5]
        write(self.path("run1.csv"), "URL,Coverage\n" + "".join(
            f"{u},Submitted and indexed\n" for u in self.listed))
        self.zip = self.path("example.com-Coverage-Drilldown-2026-11-10.zip")
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("Table.csv", "URL,Last crawled\n" + "".join(
                f"{u},2026-11-01\n" for u in self.listed))
            archive.writestr("Metadata.csv", f"Property,Value\nIssue,{REASON}\n")

    def doctor(self, gsc, out, *extra):
        return run("doctor", self.path("site"), "--site", SITE, "--sitemap",
                   self.path("sitemap.xml"), "--gsc", gsc, "--out", out, *extra)

    def test_everything_rejected_is_lost_and_dropped(self):
        code, out = self.doctor(self.path("run1.csv"), self.path("r1.html"))
        self.assertEqual(code, 0, out)
        code, out = self.doctor(self.zip, self.path("r2.html"),
                                "--baseline", self.path("r1.json"))
        self.assertEqual(code, 0, out)
        self.assertIn("Выпали из индекса (4)", out)
        with open(self.path("r2.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        step = [s for s in data["funnel"]["steps"] if s["id"] == "indexed"][0]
        self.assertEqual(step["lost"], 4)
        self.assertEqual(sorted(data["funnel"]["not_indexed_reasons"]), sorted(self.listed))
        self.assertEqual(sorted(data["baseline"]["newly_not_indexed"]), sorted(self.listed))
        with open(self.path("r2.html"), encoding="utf-8") as fh:
            page_html = fh.read()
        self.assertIn(REASON, page_html)
        self.assertIn("Не отклонено поисковиком", page_html)


# ── #298: сравнение с прошлым прогоном в HTML ──────────────────────────────────

class TestTrendInHtml(Base):
    def test_doctor_html_shows_the_comparison(self):
        site = self.path("site")
        for s in ("", "a", "b"):
            write(os.path.join(site, s, "index.html"), html_page(f"Страница {s}", "Текст. " * 40))
        full = [f"{SITE}/", f"{SITE}/a/", f"{SITE}/b/"]
        for name, urls in (("sm1.xml", full), ("sm2.xml", full[:2])):
            write(self.path(name), '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                  + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
        code, out = run("doctor", site, "--site", SITE, "--sitemap", self.path("sm1.xml"),
                        "--out", self.path("r1.html"))
        self.assertEqual(code, 0, out)
        code, out = run("doctor", site, "--site", SITE, "--sitemap", self.path("sm2.xml"),
                        "--baseline", self.path("r1.json"), "--out", self.path("r2.html"))
        self.assertEqual(code, 0, out)
        with open(self.path("r2.html"), encoding="utf-8") as fh:
            page_html = fh.read()
        self.assertIn("С прошлого прогона", page_html)
        self.assertIn("Выпали из sitemap (1)", page_html)
        self.assertIn(f"{SITE}/b/", page_html.split("С прошлого прогона", 1)[1])

    def test_lists_are_capped_and_notes_shown(self):
        urls = [f"{SITE}/p{i}/" for i in range(25)]
        trend = {"steps": [{"id": "in-sitemap", "name": "В sitemap", "before": 30,
                            "after": 5, "delta": -25}],
                 "newly_not_indexed": [], "recovered": [], "newly_off_sitemap": urls,
                 "back_in_sitemap": [f"{SITE}/x/"], "not_compared": ["index"],
                 "segments": {}, "ai_segments": {}, "bots": {}}
        got = report._trend_html(trend, "r1.json")
        self.assertIn("Выпали из sitemap (25)", got)
        self.assertIn("… и ещё 5", got)
        self.assertIn(f"{SITE}/p19/", got)
        self.assertNotIn(f"{SITE}/p20/", got)
        self.assertIn("Вернулись в sitemap (1)", got)
        self.assertIn("только в одном из прогонов", got)
        self.assertIn("-25", got)

    def test_quiet_trend_says_so(self):
        trend = {"steps": [], "not_compared": [], "segments": {}, "ai_segments": {},
                 "bots": {}}
        self.assertIn("Ничего не изменилось", report._trend_html(trend))


if __name__ == "__main__":
    unittest.main()
