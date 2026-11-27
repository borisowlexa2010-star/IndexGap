# -*- coding: utf-8 -*-
"""
1.27: команды, которые что-то порождают, — sitemap, init, plan.

* Манифест помнит, в какой каталог легли файлы: имя без каталога делало
  «своим» любой sitemap.xml и удаляло чужие sitemap-1.xml в другом --out-dir.
* Путь из самоссылающегося canonical кодируется, как путь из имени файла.
* Шард режется и по размеру; слишком длинный адрес и закрытый robots.txt
  раздел называются при сборке.
* Истёкшая страница (expiryDate, unavailable_after) в sitemap не идёт.
* plan: маршруты в разные стороны — разные строки; две строки с одним
  собственным slug не выдают вторую за «файл уже есть».
* init: путь сайта из canonical главной, колонка ключа — целым словом.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, core, generate, install, publish

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


def page_html(title, canonical="", robots="", body="Text about renting flats in a city."):
    head = f"<title>{title}</title>"
    if canonical:
        head += f'<link rel="canonical" href="{canonical}">'
    if robots:
        head += f'<meta name="robots" content="{robots}">'
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">{head}</head>"
            f"<body><main><h1>{title}</h1><p>{body}</p></main></body></html>")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def run(*argv):
    with mock.patch.object(sys, "stdout", io.StringIO()) as printed:
        code = cli.main(list(argv))
    return code, printed.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-127-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)


class OutputsPerDirectory(Base):
    """Свои файлы — это файлы в том каталоге, куда они записаны."""

    def setUp(self):
        super().setUp()
        self.site = self.path("site")
        shutil.copytree(DEMO, self.site)
        os.remove(os.path.join(self.site, "sitemap.xml"))
        self.manifest = self.path("manifest.json")

    def sitemap(self, out, *extra):
        return run("sitemap", self.site, "--site", SITE, "--out-dir", out,
                   "--manifest", self.manifest, *extra)

    def test_foreign_shards_in_another_out_dir_survive(self):
        a, b = self.path("pubA"), self.path("pubB")
        os.makedirs(b)
        for name in ("sitemap-1.xml", "sitemap-2.xml"):
            write(os.path.join(b, name), "foreign")
        saved = publish.MAX_URLS_PER_FILE
        publish.MAX_URLS_PER_FILE = 3
        self.addCleanup(setattr, publish, "MAX_URLS_PER_FILE", saved)
        self.sitemap(a)
        self.assertTrue(os.path.isfile(os.path.join(a, "sitemap-2.xml")))
        publish.MAX_URLS_PER_FILE = saved
        self.sitemap(b)
        for name in ("sitemap-1.xml", "sitemap-2.xml"):
            with open(os.path.join(b, name), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "foreign")

    def test_own_stale_shards_are_still_removed(self):
        a = self.path("pubA")
        saved = publish.MAX_URLS_PER_FILE
        publish.MAX_URLS_PER_FILE = 3
        self.addCleanup(setattr, publish, "MAX_URLS_PER_FILE", saved)
        self.sitemap(a)
        publish.MAX_URLS_PER_FILE = saved
        _, out = self.sitemap(a)
        self.assertFalse(os.path.exists(os.path.join(a, "sitemap-1.xml")))
        self.assertIn("sitemap-1.xml", out)

    def test_foreign_sitemap_stays_foreign_after_a_run_elsewhere(self):
        foreign = self.path("pub", "sitemap.xml")
        write(foreign, "<urlset>hand-made</urlset>")
        with mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertNotEqual(self.sitemap(self.path("pub"))[0], 0)
            self.assertEqual(self.sitemap(self.path("other"))[0], 0)
            self.assertNotEqual(self.sitemap(self.path("pub"))[0], 0)
        with open(foreign, encoding="utf-8") as fh:
            self.assertIn("hand-made", fh.read())

    def test_rebuild_into_the_same_directory_is_allowed(self):
        out = self.path("pub")
        self.sitemap(out)
        code, _ = self.sitemap(out)
        self.assertEqual(code, 0)

    def test_manifest_records_directory_relative_to_manifest(self):
        self.sitemap(self.path("pub"))
        with open(self.manifest, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["_outputs"], {"pub": ["sitemap.xml"]})

    def test_legacy_manifest_without_outputs_still_counts_as_own(self):
        out = self.path("pub")
        write(os.path.join(out, "sitemap.xml"), "<urlset/>")
        self.assertEqual(publish.foreign_sitemap(out, {"_shards": ["sitemap.xml"]}), "")


class CanonicalPathEncoded(Base):
    def test_raw_canonical_path_is_percent_encoded(self):
        site = self.path("site")
        write(os.path.join(site, "index.html"), page_html("Home"))
        write(os.path.join(site, "rent", "köln", "index.html"),
              page_html("Köln", canonical=f"{SITE}/rent/köln/"))
        write(os.path.join(site, "rent", "new york", "index.html"),
              page_html("New York", canonical="/rent/new york/"))
        write(os.path.join(site, "rent", "munich", "index.html"),
              page_html("Munich", canonical=f"{SITE}//rent//munich/"))
        pages = core.load_pages(site, SITE)[0]
        urls = sorted(p.url for p in pages)
        self.assertIn(f"{SITE}/rent/k%C3%B6ln/", urls)
        self.assertIn(f"{SITE}/rent/new%20york/", urls)
        self.assertIn(f"{SITE}/rent/munich/", urls)
        self.assertFalse(any(" " in u or "ö" in u or "//rent" in u for u in urls))

    def test_already_encoded_canonical_is_kept(self):
        site = self.path("site")
        write(os.path.join(site, "a.html"), page_html("A", canonical=f"{SITE}/a.html"))
        write(os.path.join(site, "k%C3%B6ln.html"),
              page_html("K", canonical=f"{SITE}/k%C3%B6ln.html"))
        urls = sorted(p.url for p in core.load_pages(site, SITE)[0])
        self.assertIn(f"{SITE}/a.html", urls)


class SitemapLimits(Base):
    def pages(self, n, segment="x"):
        site = self.path("site")
        for i in range(n):
            write(os.path.join(site, segment, f"p{i}", "index.html"), page_html(f"P{i}"))
        return core.load_pages(site, SITE)[0]

    def test_shard_by_size(self):
        pages = self.pages(6)
        saved = publish.MAX_BYTES_PER_FILE
        publish.MAX_BYTES_PER_FILE = 400
        self.addCleanup(setattr, publish, "MAX_BYTES_PER_FILE", saved)
        out = self.path("out")
        result = publish.build_sitemap(pages, out, SITE, today="2026-10-01")
        self.assertGreater(result["shards"], 1)
        for name in os.listdir(out):
            if name.startswith("sitemap-"):
                self.assertLessEqual(os.path.getsize(os.path.join(out, name)), 400)
        with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
            self.assertIn("<sitemapindex", fh.read())

    def test_small_site_stays_a_single_file(self):
        result = publish.build_sitemap(self.pages(3), self.path("out"), SITE)
        self.assertEqual(result["shards"], 0)
        self.assertEqual(result["too_long"], [])

    def test_too_long_address_is_named(self):
        site = self.path("site")
        # Длина набирается кодировкой, а не диском: путь macOS ограничен 1024
        # байтами, а «ж» в <loc> — это «%D0%B6», шесть символов на букву.
        deep = os.path.join(site, *(["ж" * 120] * 3))
        write(os.path.join(deep, "index.html"), page_html("Long"))
        write(os.path.join(site, "index.html"), page_html("Home"))
        manifest = self.path("m.json")
        _, out = run("sitemap", site, "--site", SITE, "--out-dir", self.path("out"),
                     "--manifest", manifest)
        self.assertIn("длиннее 2047 символов", out)


class RobotsBlockedWarning(Base):
    def test_sitemap_names_pages_closed_in_robots(self):
        site = self.path("site")
        write(os.path.join(site, "index.html"), page_html("Home"))
        write(os.path.join(site, "private", "x", "index.html"), page_html("X"))
        write(os.path.join(site, "robots.txt"), "User-agent: *\nDisallow: /private/\n")
        _, out = run("sitemap", site, "--site", SITE, "--out-dir", self.path("out"),
                     "--manifest", self.path("m.json"))
        self.assertIn("закрыты в", out)
        self.assertIn(f"{SITE}/private/x/", out)

    def test_no_warning_when_robots_allows(self):
        site = self.path("site")
        write(os.path.join(site, "index.html"), page_html("Home"))
        write(os.path.join(site, "robots.txt"), "User-agent: *\nDisallow:\n")
        _, out = run("sitemap", site, "--site", SITE, "--out-dir", self.path("out"),
                     "--manifest", self.path("m.json"))
        self.assertNotIn("закрыты в", out)


class ExpiredPages(Base):
    def test_hugo_expiry_and_unavailable_after(self):
        site, md = self.path("site"), self.path("md")
        write(os.path.join(md, "a.md"),
              "---\ntitle: \"Page a about renting\"\nexpiryDate: 2020-01-01\n---\n\nText.\n")
        write(os.path.join(md, "b.md"),
              "---\ntitle: \"Page b about renting\"\nexpiryDate: 2999-01-01\n---\n\nText.\n")
        write(os.path.join(site, "c", "index.html"),
              page_html("C", robots="unavailable_after: 2020-01-01"))
        write(os.path.join(site, "d", "index.html"),
              page_html("D", robots="unavailable_after: 25 Jun 2999 15:00:00 PST"))
        pages = {p.url.rstrip("/").rsplit("/", 1)[-1]: p
                 for folder in (site, md) for p in core.load_pages(folder, SITE)[0]}
        self.assertFalse(publish.indexable(pages["a"]))
        self.assertTrue(publish.indexable(pages["b"]))
        self.assertFalse(publish.indexable(pages["c"]))
        self.assertTrue(publish.indexable(pages["d"]))

    def test_today_is_not_expired(self):
        site = self.path("site")
        write(os.path.join(site, "a.md"),
              "---\ntitle: \"Page a\"\nexpiryDate: 2026-10-01\n---\n\nText.\n")
        page = core.load_pages(site, SITE)[0][0]
        self.assertFalse(publish.is_expired(page, today="2026-10-01"))
        self.assertTrue(publish.is_expired(page, today="2026-10-02"))


class PlanRoutesAndSlugs(Base):
    def audit(self, text):
        path = self.path("d.csv")
        write(path, text)
        data = generate.read_dataset(path)
        return generate.audit_dataset(data["rows"], data["fields"], "keyword")

    def test_opposite_routes_are_different_rows(self):
        audit = self.audit(
            "keyword,price\n"
            "flights london to paris,$89\nflights paris to london,$95\n"
            "билеты из москвы в казань,3500\nбилеты из казани в москву,3700\n")
        self.assertEqual(len(audit["keep"]), 4)
        self.assertEqual(audit["rejected"], [])

    def test_same_route_reworded_is_still_one_intent(self):
        audit = self.audit("keyword\nflights london to paris\nlondon to paris flights\n"
                           "виза в таиланд\nтаиланд виза\n")
        self.assertEqual(len(audit["keep"]), 2)
        self.assertEqual({r["code"] for r in audit["rejected"]}, {"same-intent"})

    def test_own_slug_collision_is_a_failure_not_a_skip(self):
        text = ("keyword,slug,city\nrent in berlin,berlin,Berlin\n"
                "cheap flats berlin,berlin,Berlin\nrent in munich,munich,Munich\n")
        # С 1.29 повтор собственного slug виден уже в разборе.
        audit = self.audit(text)
        self.assertEqual([(r["code"], r["keyword"]) for r in audit["rejected"]],
                         [("slug-collision", "cheap flats berlin")])
        # Если разбор его пропустил (шаблон с другой колонкой), запись — отказ.
        path = self.path("d.csv")
        data = generate.read_dataset(path)
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword",
                                       {"own_slug_is_path": False})
        self.assertEqual([s for _i, _k, s, _r in audit["keep"]],
                         ["berlin", "berlin", "munich"])
        out = self.path("out")
        result = generate.write_tasks(audit, out, "keyword")
        self.assertEqual(len(result["written"]), 2)
        self.assertEqual(result["skipped"], [])
        self.assertEqual([f["keyword"] for f in result["failed"]], ["cheap flats berlin"])

    def test_existing_file_is_still_skipped(self):
        audit = self.audit("keyword\nrent in berlin\n")
        out = self.path("out")
        write(os.path.join(out, "rent-in-berlin", "index.md"), "mine")
        result = generate.write_tasks(audit, out, "keyword")
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["failed"], [])


class InitDetection(Base):
    def test_site_keeps_the_path_the_home_page_declares(self):
        public = self.path("public")
        write(os.path.join(public, "index.html"), page_html("Docs", canonical=f"{SITE}/docs/"))
        self.assertEqual(install._declared_site(public), f"{SITE}/docs/")

    def test_root_and_locale_canonicals_stay_at_the_origin(self):
        for declared in (f"{SITE}/", f"{SITE}/index.html", f"{SITE}/en/", f"{SITE}/pt-br/"):
            with self.subTest(declared=declared):
                public = self.path("p" + str(abs(hash(declared))))
                write(os.path.join(public, "index.html"), page_html("Home", canonical=declared))
                self.assertEqual(install._declared_site(public), f"{SITE}/")

    def test_keyword_column_is_matched_as_a_word(self):
        write(self.path("x", "invoices.csv"), "invoice,customer,payment_terms,total\n1,a,30,5\n")
        write(self.path("data", "seo", "keywords.csv"), "keyword,city\nrent in berlin,Berlin\n")
        self.assertEqual(install.detect_dataset(self.dir),
                         os.path.join(".", "data", "seo", "keywords.csv"))

    def test_keyword_word_inside_a_column_name_still_counts(self):
        write(self.path("a", "q.csv"), "search_query,volume\nrent,10\n")
        self.assertEqual(install.detect_dataset(self.dir), os.path.join(".", "a", "q.csv"))


if __name__ == "__main__":
    unittest.main()
