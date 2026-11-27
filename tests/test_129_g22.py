# -*- coding: utf-8 -*-
"""
1.29 (g22): отчёт HTML и JSON сходятся с консолью; чтение файлов в чужих
кодировках.

Отчёт молчал о находках, принятых через ignore, doctor отсылал к JSON без
находок, «Начни с этого» считал находки вместо страниц, diff не показывал
новые «внимание», таблица разделов обрезалась без слова. Имя каталога с
байтом не в UTF-8 роняло прогон; карточка `/product/401/` пропадала как
страница ошибки. Кракозябры cp1251 и заглавные умлауты в cp1252 не ловились,
title не проверялся; UTF-8 с подвалом в cp1251 читался целиком как cp1251;
противоречие объявленной кодировки и байтов не называлось; UTF-16 с лишним
байтом выпадал как «кусок шаблона»; Metadata.csv в UTF-16 терял «не в индексе».
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, content, core, report, sources

SITE = "https://shop.example"
WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
         "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
         "xray yankee zulu ") * 12
RU = ("Квартира в центре города стоит дороже, чем на окраине, зато дорога до работы "
      "занимает меньше времени. Залог обычно равен месячной плате. ") * 10


def html(title, body, head='<meta charset="utf-8">', lang="en"):
    return (f'<!doctype html><html lang="{lang}"><head>{head}<title>{title}</title>'
            f'<meta name="viewport" content="width=device-width"></head>'
            f'<body><main><h1>{title}</h1><p>{body}</p></main></body></html>')


class Tmp(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-129g22-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, data):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def cli(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(list(argv))
        return code, out.getvalue()


class Decoding(Tmp):
    def test_utf8_page_with_a_cp1251_footer_stays_utf8(self):
        page = html("Аренда квартиры в городе", RU, lang="ru")
        data = page.encode().replace(b"</main>", b"</main><footer>"
                                     + "© ООО Ромашка, все права".encode("cp1251")
                                     + b"</footer>")
        text, encoding = core.read_text(self.write("a/index.html", data))
        self.assertEqual(encoding, "utf-8")
        self.assertIn("<title>Аренда квартиры в городе</title>", text)

    def test_whole_cp1251_page_declaring_utf8_is_named(self):
        page = html("Аренда квартиры в городе", RU, lang="ru").encode("cp1251")
        path = self.write("a/index.html", page)
        self.assertEqual(core.read_text(path)[1], "cp1251")
        notes = core.load_page(path, self.root, SITE).notes
        self.assertTrue(any("объявлен UTF-8" in n for n in notes), notes)

    def test_correct_cp1251_declaration_keeps_the_plain_note(self):
        page = html("Аренда квартиры в городе", RU, lang="ru",
                    head='<meta charset="windows-1251">').encode("cp1251")
        notes = core.load_page(self.write("a/index.html", page), self.root, SITE).notes
        self.assertEqual(notes, ["файл прочитан как cp1251, а не UTF-8"])

    def test_stale_legacy_declaration_on_utf8_is_named(self):
        page = html("Аренда квартиры в городе", RU, lang="ru",
                    head='<meta charset="windows-1251">')
        notes = core.load_page(self.write("a/index.html", page), self.root, SITE).notes
        self.assertTrue(any("windows-1251" in n and "файл в UTF-8" in n for n in notes), notes)

    def test_ascii_page_with_latin1_declaration_is_quiet(self):
        page = html("Plain page title", WORDS, head='<meta charset="iso-8859-1">')
        self.assertEqual(core.load_page(self.write("a/index.html", page), self.root,
                                        SITE).notes, [])

    def test_utf16_with_a_trailing_odd_byte_is_still_a_page(self):
        page = html("Plain page title", WORDS).encode("utf-16") + b"\n"
        self.write("index.html", html("Home page title", WORDS + ' <a href="/a/">a</a>'))
        self.write("a/index.html", page)
        text, encoding = core.read_text(os.path.join(self.root, "a", "index.html"))
        self.assertEqual(encoding, "utf-16")
        self.assertIn("<title>Plain page title</title>", text)
        pages, problems = core.load_pages(self.root, SITE)
        self.assertEqual(sorted(p.url for p in pages), [SITE + "/", SITE + "/a/"])

    def test_non_utf8_byte_in_a_directory_name(self):
        if sys.platform in ("darwin", "win32"):
            self.skipTest("файловая система не хранит такие имена")
        folder = os.path.join(os.fsencode(self.root), b"caf\xe9")
        try:
            os.makedirs(folder)
        except OSError:
            self.skipTest("файловая система не хранит такие имена")
        with open(os.path.join(folder, b"index.html"), "w", encoding="utf-8") as fh:
            fh.write(html("Cafe page title here", WORDS))
        pages, _ = core.load_pages(self.root, SITE)
        self.assertEqual([p.url for p in pages], [SITE + "/caf%E9/"])


class Mojibake(unittest.TestCase):
    def kinds(self, text):
        return [k for k, _ in core.find_slots(text)]

    def test_utf8_read_as_cp1251(self):
        moj = "Аренда квартиры в Казани".encode("utf-8").decode("cp1251")
        self.assertIn("mojibake", self.kinds(moj))

    def test_ordinary_russian_is_clean(self):
        for text in (RU, "Агентство ТАСС» сообщило", "ВСЁ СРАЗУ", "СССР — страна",
                     "Р. С. Иванов", "ООО «РС»"):
            self.assertNotIn("mojibake", self.kinds(text), text)

    def test_capital_umlauts_and_ligatures_in_cp1252(self):
        for word in ("Ärzte", "Übersicht", "Öffnungszeiten", "Étudiants", "œuvre",
                     "ESPAÑA"):
            moj = ("Text about " + word).encode("utf-8").decode("cp1252")
            self.assertIn("mojibake", self.kinds(moj), moj)

    def test_portuguese_capitals_are_clean(self):
        for text in ("SÃO PAULO", "a palavra “AMANHÔ é curta", "MAÇÃ…", "IRMÃ’s"):
            self.assertNotIn("mojibake", self.kinds(text), text)

    def test_mojibake_in_the_title_only(self):
        page = core.Page(path="a.html", url=SITE + "/a/", title="CafÃ© ZÃ¼rich: hours",
                         description="", text="clean text", raw="<p>clean text</p>")
        found = [i[2] for i in content.check_slots([page])]
        self.assertEqual(found, ["mojibake"])


class Reports(Tmp):
    def test_first_things_counts_pages_not_findings(self):
        issues = [("critical", SITE + "/en/", "hreflang-no-return", f"to {x}")
                  for x in ("de", "fr", "es", "it")]
        block = report._first_things(issues, {}, [])
        self.assertIn("— 1 стр.", block)

    def test_accepted_findings_and_orphan_card(self):
        out = os.path.join(self.root, "r.html")
        analysis = {"pages": [], "issues": [], "graph": {"orphans": [SITE + "/a/"]},
                    "duplicates": [],
                    "accepted": [("critical", SITE + "/a/", "orphan", "сирота")]}
        report.build(analysis, out_path=out)
        with open(out, encoding="utf-8") as fh:
            doc = fh.read()
        self.assertIn("Принято намеренно (ignore в indexgap.json): 1", doc)
        self.assertIn('<div class="n bad">0</div><div class="l">сирот', doc)

    def test_segment_table_says_it_is_cut(self):
        rows = [{"segment": f"/s{i}/", "pages": 3, "lost": 1, "coverage": 0.6,
                 "missing_from_sitemap": 0, "not_indexed": 1} for i in range(41)]
        block = report._segments_html({"rows": rows, "highlighted": [],
                                       "site": {"coverage": 0.6}})
        self.assertIn("Показано разделов: 30 из 41", block)
        short = report._segments_html({"rows": rows[:5], "highlighted": [],
                                       "site": {"coverage": 0.6}})
        self.assertNotIn("Показано разделов", short)

    def test_doctor_json_holds_the_findings(self):
        self.write("index.html", html("Home page title", WORDS))
        self.write("lost/index.html", html("Lost page title", WORDS))
        idx = self.write("idx.txt", SITE + "/\n")
        out = os.path.join(self.root, "out", "r.html")
        self.cli("doctor", self.root, "--site", SITE, "--indexed", "google=" + idx,
                 "--out", out)
        with open(os.path.join(self.root, "out", "r.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn(("orphan", SITE + "/lost/"),
                      {(i["code"], i["url"]) for i in data["issues"]})

    def test_diff_counts_new_warnings(self):
        old, new = os.path.join(self.root, "old"), os.path.join(self.root, "new")
        for build in (old, new):
            body = WORDS + ' <a href="/b/">b</a>'
            for rel, title in (("index.html", "Home page title here"),
                               ("b/index.html", "Second page title here")):
                path = os.path.join(build, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(html(title, body))
        with open(os.path.join(new, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html("Home page title here", WORDS + ' <a href="/b/">b</a> '
                          '<a href="/gone/">gone</a>'))
        out = os.path.join(self.root, "d", "r.html")
        self.cli("diff", old, new, "--site", SITE, "--out", out)
        with open(os.path.join(self.root, "d", "r.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        warned = [i for i in data["items"] if i["level"] == "warning"
                  and i["code"] == "new-finding"]
        self.assertTrue(any("broken-link" in i["message"] for i in warned), data["items"])
        self.assertEqual(data["summary"]["warning"], len(warned))
        self.assertEqual(data["findings"]["new_warning"], len(warned))


class Discovery(Tmp):
    def test_numbered_catalogue_page_is_not_an_error_page(self):
        self.write("index.html", html("Home page title", WORDS))
        self.write("product/401/index.html", html("Product number one", WORDS))
        self.write("product/402/index.html", html("Product number two", WORDS))
        pages, _ = core.load_pages(self.root, SITE)
        self.assertIn(SITE + "/product/401/", {p.url for p in pages})
        result = checks.run_all(pages, SITE + "/")
        orphans = {i[1] for i in result["issues"] if i[2] == "orphan"}
        self.assertEqual(orphans, {SITE + "/product/401/", SITE + "/product/402/"})

    def test_unlinked_deep_error_page_is_still_dropped(self):
        self.write("index.html", html("Home page title", WORDS))
        self.write("errors/404/index.html", html("Not found", "nothing here"))
        self.write("errors/500/index.html", html("Server error", "nothing here"))
        pages, _ = core.load_pages(self.root, SITE)
        self.assertEqual([p.url for p in pages], [SITE + "/"])


class ZipIssue(Tmp):
    def test_metadata_in_utf16_and_cp1251(self):
        meta = 'Проблема,"Страница просканирована, но пока не проиндексирована"\n'
        for codec in ("utf-16", "cp1251"):
            path = os.path.join(self.root, f"gsc-{codec}.zip")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("Таблица.csv", "URL,Обновлено\nhttps://shop.example/a/,2026-01-01\n")
                z.writestr("Метаданные.csv", meta.encode(codec))
            self.assertEqual(sources.zip_issue(path),
                             "Страница просканирована, но пока не проиндексирована", codec)


if __name__ == "__main__":
    unittest.main()
