# -*- coding: utf-8 -*-
"""
Регрессии второй волны аудита — и, отдельно, регрессии, которые внесла
починка первой волны.

Урок, ради которого этот файл существует: два теста первой волны прошли мимо
собственных находок, потому что проверяли соседний вариант. Тест на хеш
страницы проверял `<main>`, а сломалось на `role="main"`. Тест на пропавшую
главную дёргал функцию напрямую и не заметил, что через CLI починка выключена.
Поэтому здесь проверяются оба варианта и, где это важно, весь путь целиком.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexgap import aeo, checks, cli, content, core, doctor, engines, generate, publish
from indexgap.core import SourceError

SITE = "https://example.com"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-w2-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path) or self.dir, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def load(self, root=None, site=SITE):
        return core.load_pages(root or self.dir, site)

    def run_cli(self, argv):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            code = cli.main(argv)
        return code, out.getvalue()


# ── потеря данных ─────────────────────────────────────────────────────────────

class TestDataLoss(Fixture):
    def test_foreign_sitemaps_survive(self):
        """Уборка «устаревших шардов» по маске сносила чужие файлы."""
        self.write("a.md", "---\ntitle: А\n---\n\nТекст")
        pages, _ = self.load()
        out = os.path.join(self.dir, "public")
        os.makedirs(out)
        for name in ("sitemap-news.xml", "sitemap-images.xml", "sitemap-video.xml"):
            with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
                fh.write("<urlset/>")
        publish.build_sitemap(pages, out, SITE, manifest={})
        for name in ("sitemap-news.xml", "sitemap-images.xml", "sitemap-video.xml"):
            self.assertTrue(os.path.exists(os.path.join(out, name)), name)

    def test_own_shards_are_cleaned_up(self):
        pages = [_FakePage(f"{SITE}/p{i}/", f"текст {i}") for i in range(3)]
        out = os.path.join(self.dir, "public")
        saved = publish.MAX_URLS_PER_FILE
        publish.MAX_URLS_PER_FILE = 1
        try:
            first = publish.build_sitemap(pages, out, SITE, manifest={})
            self.assertTrue(os.path.exists(os.path.join(out, "sitemap-3.xml")))
            second = publish.build_sitemap(pages[:1], out, SITE,
                                           manifest=first["manifest"])
        finally:
            publish.MAX_URLS_PER_FILE = saved
        self.assertFalse(os.path.exists(os.path.join(out, "sitemap-3.xml")))
        self.assertTrue(second["removed"])

    def test_report_refuses_to_overwrite_a_page(self):
        page = self.write("content/p1/index.html", "<html><body><p>Моя страница</p></body></html>")
        with self.assertRaises(SourceError):
            cli.check_out_path(page)
        self.assertIn("Моя страница", open(page, encoding="utf-8").read())

    def test_report_may_overwrite_its_own_output(self):
        from indexgap import report
        path = report.build({}, out_path=os.path.join(self.dir, "r.html"))
        self.assertEqual(cli.check_out_path(path), path)

    def test_out_pointing_at_a_directory_is_refused(self):
        with self.assertRaises(SourceError):
            cli.check_out_path(self.dir)


# ── недоделанные починки первой волны ─────────────────────────────────────────

class TestHalfDoneFixes(Fixture):
    def test_div_role_main_closes(self):
        """Счётчик основного блока рос для role=main и не падал никогда."""
        template = ("<html><body><nav>Меню Каталог</nav>"
                    "<div role=\"main\"><p>Основной текст страницы</p></div>"
                    "<footer>Телефон {phone}</footer></body></html>")
        for i in range(5):
            self.write(f"p{i}.html", template.format(phone="111"))
        before = {p.url: p.content_hash for p in self.load()[0]}
        for i in range(5):
            self.write(f"p{i}.html", template.format(phone="222"))
        after = {p.url: p.content_hash for p in self.load()[0]}
        self.assertEqual(before, after)

    def test_main_text_excludes_footer_with_role_main(self):
        self.write("a.html", '<html><body><div role="main"><p>Тело</p></div>'
                             '<footer>Подвал</footer></body></html>')
        page = self.load()[0][0]
        self.assertNotIn("подвал", page.words)

    def test_missing_home_is_reported_through_the_cli(self):
        """Через CLI предупреждение не печаталось никогда."""
        for name in ("a", "b", "c"):
            self.write(f"{name}/index.md", f"---\ntitle: {name}\n---\n\nТекст {name}")
        code, out = self.run_cli(["check", self.dir, "--site", SITE, "--no-aeo",
                                  "--out", os.path.join(self.dir, "r.html")])
        self.assertEqual(code, 0)
        self.assertIn("главной страницы нет", out)

    def test_bad_key_is_a_human_message_not_a_traceback(self):
        self.write("a.md", "---\ntitle: А\n---\n\nТекст")
        code, out = self.run_cli(["notify", self.dir, "--site", SITE,
                                  "--key", "<свой-ключ>", "--offline"])
        self.assertEqual(code, 2)

    def test_relative_base_href_keeps_canonical_self(self):
        self.write("guides/a.html",
                   '<html><head><base href="/guides/">'
                   '<link rel="canonical" href="a.html"></head>'
                   '<body><p>Текст</p></body></html>')
        page = self.load()[0][0]
        self.assertTrue(publish.indexable(page))
        self.assertFalse([i for i in checks.technical_issues([page])
                          if i[2] == "canonical-elsewhere"])

    def test_double_slash_link_is_not_an_orphan(self):
        self.write("index.html", '<html><body><a href="/guides//visa/">Виза</a></body></html>')
        self.write("guides/visa/index.html", "<html><body><p>Виза</p></body></html>")
        pages, _ = self.load()
        graph = checks.link_graph(pages, SITE)
        self.assertEqual(graph["orphans"], [])

    def test_charset_in_a_script_url_is_ignored(self):
        body = ('<html><head><meta charset="utf-8">'
                '<script src="/x.js?charset=koi8-r"></script>'
                '<title>Виза в Сингапур</title></head><body><p>Текст</p></body></html>')
        with open(os.path.join(self.dir, "a.html"), "wb") as fh:
            fh.write(body.encode("utf-8"))
        page = self.load()[0][0]
        self.assertEqual(page.title, "Виза в Сингапур")

    def test_utf8_aliases_do_not_produce_a_warning(self):
        with open(os.path.join(self.dir, "a.html"), "wb") as fh:
            fh.write('<html><head><meta charset="utf8"><title>Заголовок страницы</title>'
                     '</head><body><p>Текст</p></body></html>'.encode("utf-8"))
        page = self.load()[0][0]
        self.assertEqual(page.notes, [])

    def test_timeout_does_not_lose_confirmed_batches(self):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise TimeoutError("read timed out")

            class R:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            return R()

        saved = publish.INDEXNOW_BATCH
        publish.INDEXNOW_BATCH = 1
        try:
            with mock.patch("urllib.request.urlopen", fake_urlopen):
                out = publish.submit_indexnow([f"{SITE}/a/", f"{SITE}/b/", f"{SITE}/c/"],
                                              SITE, "abcdef1234567890", dry_run=False)
        finally:
            publish.INDEXNOW_BATCH = saved
        self.assertEqual(out["accepted"], [f"{SITE}/a/"])
        self.assertTrue(any(r.get("status") == "network" for r in out["results"]))


# ── ложные тревоги ────────────────────────────────────────────────────────────

class _FakePage:
    def __init__(self, url, text, title="", description=""):
        self.url, self.text, self.title, self.description = url, text, title, description
        self.canonical = self.robots = self.lang = self.chrome = ""
        self.links, self.anchors, self.headings, self.jsonld = [], [], [], []
        self.meta, self.blocks, self.notes = {}, {}, []
        self.paragraphs = [text]
        self.raw = text
        self.path = url

    key = property(lambda self: core.url_key(self.url))
    words = property(lambda self: core.Page.words.fget(self))
    word_count = property(lambda self: len(self.words))
    noindex = property(lambda self: core.Page.noindex.fget(self))
    nosnippet = property(lambda self: core.Page.nosnippet.fget(self))
    content_hash = property(lambda self: core.Page.content_hash.fget(self))


class TestFalseAlarms(Fixture):
    def test_digits_keep_intents_apart_on_a_real_catalogue(self):
        rows = [{"keyword": f"{n} комнатная квартира {c}"}
                for c in ("москва", "спб", "казань") for n in range(1, 6)]
        audit = generate.audit_dataset(rows, ["keyword"], "keyword")
        self.assertEqual(len(audit["keep"]), 15)

    def test_amnesty_does_not_swallow_the_check_on_a_big_dataset(self):
        """Прощалось любое число из датасета: 85% выдумок на 5000 строк."""
        rows = [{"keyword": f"услуга {i}", "price": f"{1000 + i * 7} RUB"}
                for i in range(2000)]
        constants = content._site_constants(rows)
        pardoned = sum(1 for n in range(1, 101) if str(n) in constants)
        self.assertLessEqual(pardoned, 5)

    def test_site_constant_is_still_pardoned(self):
        rows = [{"keyword": f"к{i}", "term": "14 дней", "price": f"{100 + i} RUB"}
                for i in range(20)]
        self.assertIn("14", content._site_constants(rows))

    def test_numbers_do_not_merge_across_punctuation(self):
        for text in ("* 44\n* 55 руб", "предлагаем 1, 2, 3 варианта",
                     "Смена с 9 до 21.\n\n## Мастера"):
            with self.subTest(text=text):
                found = content._generic_numbers_in(text)
                self.assertNotIn("4455", found)
                self.assertNotIn("123", found)

    def test_thousands_with_a_space_are_one_number(self):
        self.assertIn("18000", content._generic_numbers_in("цена 18 000 руб"))

    def test_counting_words_are_not_facts(self):
        text = ("Всего 3 шага до заказа. Оплата в 2 варианта. Рейтинг 5 звёзд. "
                "Офис на 1 этаже. Мы в топ-10 рейтинга.")
        self.assertEqual(content._generic_numbers_in(text), {})

    def test_real_measures_are_still_facts(self):
        found = content._generic_numbers_in(
            "Работаем 12 лет, выполнили 3500 заказов, грузоподъёмность 25 тонн, "
            "глубина до 4.5 м.")
        self.assertEqual(set(found), {"12", "3500", "25", "4.5"})

    def test_matching_survives_word_forms(self):
        rows = [{"keyword": "аренда экскаватора москва"}]
        page = _FakePage(f"{SITE}/a/", "Текст", title="Аренда экскаватора в Москве")
        result = content.match_rows([page], rows, "keyword", ".")
        self.assertIn(page.url, result["matched"])

    def test_city_anchors_are_not_vague(self):
        page = _FakePage(f"{SITE}/a/", "текст")
        page.anchors = ["Москва", "Омск", "Сочи", "Тула"]
        issues = content.check_brief([page], {"vague_anchors": []})
        self.assertFalse([i for i in issues if i[2] == "vague-anchor"])

    def test_boilerplate_verdict_does_not_flip_between_nine_and_ten(self):
        def corpus(n):
            return [_FakePage(f"{SITE}/p{i}/",
                              "меню каталог контакты " * 3
                              + f"уникальный текст города номер {i} " * 12)
                    for i in range(n)]
        nine = checks.boilerplate_profile(corpus(9))["shares"]
        ten = checks.boilerplate_profile(corpus(10))["shares"]
        self.assertLess(abs(min(nine.values()) - min(ten.values())), 0.25)

    def test_mixed_main_markup_does_not_invert_the_verdict(self):
        chrome = "<nav>Меню Каталог Контакты Цены Отзывы</nav>"
        for i in range(12):
            body = f"<p>Уникальный текст страницы номер {i} про аренду техники в городе</p>"
            if i % 2:
                self.write(f"m{i}.html", f"<html><body>{chrome}<main>{body}</main></body></html>")
            else:
                self.write(f"p{i}.html", f"<html><body>{chrome}<div>{body}</div></body></html>")
        pages, _ = self.load()
        words = checks.trimmed_words(pages)
        with_main = [len(words[p.url]) for p in pages if p.chrome]
        without = [len(words[p.url]) for p in pages if not p.chrome]
        self.assertLess(abs(sum(with_main) / len(with_main)
                            - sum(without) / len(without)), 4)

    def test_amp_page_is_not_an_empty_shell(self):
        self.write("amp.html",
                   '<html ⚡ lang="ru"><head><title>AMP</title>'
                   '<script async src="a.js"></script><script async src="b.js"></script>'
                   '<script async src="c.js"></script></head>'
                   '<body><main><h1>Аренда</h1><p>Коротко.</p></main></body></html>')
        page = self.load()[0][0]
        self.assertEqual(aeo.check_shell(page), [])

    def test_html_meta_author_and_date_are_seen(self):
        self.write("a.html",
                   '<html><head><meta name="author" content="ООО Ромашка">'
                   '<meta property="article:published_time" content="2026-02-01">'
                   '<title>Заголовок страницы про аренду</title></head>'
                   '<body><p>Текст страницы</p></body></html>')
        page = self.load()[0][0]
        self.assertEqual(aeo.check_provenance(page), [])

    def test_graph_jsonld_is_expanded(self):
        page = _FakePage(f"{SITE}/a/", "видимый текст страницы")
        page.jsonld = [json.dumps({"@context": "https://schema.org", "@graph": [
            {"@type": "WebPage", "datePublished": "2026-01-01",
             "author": {"@type": "Organization", "name": "Ромашка"}}]})]
        self.assertEqual(aeo.check_jsonld(page), [])
        self.assertEqual(aeo.check_provenance(page), [])

    def test_paragraphs_start_at_the_main_content(self):
        self.write("a.html",
                   "<html><body><header><nav>Главная Каталог Контакты</nav></header>"
                   "<main><h1>Заголовок</h1>"
                   "<p>Смена экскаватора стоит 18000 рублей за восемь часов работы.</p>"
                   "</main></body></html>")
        page = self.load()[0][0]
        self.assertTrue(page.paragraphs[0].startswith("Смена экскаватора"))
        self.assertEqual(aeo.check_answer(page), [])

    def test_crawl_delay_does_not_merge_robots_groups(self):
        path = self.write("robots.txt",
                          "User-agent: *\nCrawl-delay: 10\n\n"
                          "User-agent: GPTBot\nDisallow: /\n\n"
                          "Sitemap: https://example.com/sitemap.xml\n")
        codes = [i[2] for i in aeo.check_robots(aeo.read_robots(path))]
        self.assertNotIn("robots-blocks-all", codes)
        self.assertIn("ai-crawler-blocked", codes)

    def test_wildcard_disallow_is_a_block(self):
        path = self.write("robots.txt", "User-agent: PerplexityBot\nDisallow: /*\n")
        codes = [i[2] for i in aeo.check_robots(aeo.read_robots(path))]
        self.assertIn("ai-crawler-blocked", codes)

    def test_one_false_question_does_not_mute_the_check(self):
        page = _FakePage(f"{SITE}/a/", "текст " * 100)
        page.headings = [(2, "Наши преимущества"), (2, "Отзывы клиентов"),
                         (2, "What you get"), (2, "Условия аренды"), (2, "Цены")]
        codes = [i[2] for i in aeo.check_extractable(page)]
        self.assertIn("no-question-headings", codes)


# ── объём и приоритет ─────────────────────────────────────────────────────────

class TestVolume(Fixture):
    def test_duplicates_are_counted_per_page_not_per_pair(self):
        pages = [_FakePage(f"{SITE}/p{i}/", "совершенно одинаковый текст страницы здесь")
                 for i in range(20)]
        result = checks.run_all(pages, home_url=f"{SITE}/p0/")
        near = [i for i in result["issues"] if i[2] == "near-duplicate"]
        self.assertLessEqual(len(near), len(pages))
        self.assertGreater(len(result["duplicates"]), len(pages))

    def test_root_mismatch_is_named(self):
        """Каталог не соответствует корню сайта — самый частый неверный вердикт."""
        self.write("content/index.html",
                   '<html><body><a href="/a/">А</a><a href="/b/">Б</a></body></html>')
        self.write("content/a/index.html", '<html><body><a href="/b/">Б</a></body></html>')
        self.write("content/b/index.html", '<html><body><a href="/a/">А</a></body></html>')
        pages, _ = self.load()
        graph = checks.link_graph(pages, SITE)
        self.assertIn("каталог не соответствует корню сайта",
                      checks.root_mismatch(pages, graph))

    def test_correct_root_produces_no_mismatch_note(self):
        self.write("index.html", '<html><body><a href="/a/">А</a></body></html>')
        self.write("a/index.html", '<html><body><a href="/">Домой</a></body></html>')
        pages, _ = self.load()
        graph = checks.link_graph(pages, SITE)
        self.assertEqual(checks.root_mismatch(pages, graph), "")


# ── воронка и поисковики ──────────────────────────────────────────────────────

class TestFunnel(Fixture):
    def test_funnel_never_grows(self):
        self.write("a.md", "---\ntitle: А\nrobots: noindex\n---\n\nТекст")
        self.write("b.md", "---\ntitle: Б\n---\n\nТекст")
        pages, _ = self.load()
        result = doctor.funnel(pages, [f"{SITE}/b/"],
                               [f"{SITE}/a/", f"{SITE}/b/"])
        counts = [s["count"] for s in result["steps"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_foreign_export_is_named(self):
        self.write("a.md", "---\ntitle: А\n---\n\nТекст")
        pages, _ = self.load()
        result = doctor.funnel(pages, None,
                               [f"https://other.example/{i}/" for i in range(50)])
        self.assertTrue(result["foreign"])

    def test_similar_pages_do_not_get_canonical_advice(self):
        pages = [_FakePage(f"{SITE}/a/", "аренда экскаватора в москве недорого сегодня"),
                 _FakePage(f"{SITE}/b/", "аренда экскаватора в казани недорого завтра")]
        analysis = checks.run_all(pages, home_url=f"{SITE}/a/")
        funnel = doctor.funnel(pages, None, [])
        causes = doctor.explain(funnel, analysis)
        similar = [p for p in analysis["duplicates"]
                   if p[2] < analysis["config"]["near_duplicate"]]
        if similar:
            self.assertFalse([c for c in causes if "дубли" in c["cause"]])

    def test_self_referencing_sitemap_index_terminates(self):
        path = self.write("sitemap.xml",
                          '<?xml version="1.0"?><sitemapindex '
                          'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                          + '<sitemap><loc>https://example.com/sitemap.xml</loc></sitemap>' * 20
                          + '</sitemapindex>')
        result = doctor.read_sitemap(path)
        self.assertLess(len(result["error"]), 4000)

    def test_sitemap_without_namespace_is_read(self):
        path = self.write("s.xml", "<urlset><url><loc>https://example.com/a/</loc></url></urlset>")
        self.assertEqual(doctor.read_sitemap(path)["urls"], ["https://example.com/a/"])

    def test_ambiguous_engine_is_not_used_for_verdicts(self):
        engine, confident = engines.guess_engine("table.csv", ["URL", "Последнее сканирование"])
        self.assertFalse(confident)


# ── манифест ──────────────────────────────────────────────────────────────────

class TestManifest(Fixture):
    def test_dead_entries_are_pruned(self):
        pages = [_FakePage(f"{SITE}/p{i}/", f"текст {i}") for i in range(2)]
        out = os.path.join(self.dir, "public")
        manifest = {f"{SITE}/old/": {"hash": "x", "lastmod": "2020-01-01",
                                     "missing_since": "2020-01-01"}}
        result = publish.build_sitemap(pages, out, SITE, manifest=manifest,
                                       today="2026-08-28")
        self.assertNotIn(f"{SITE}/old/", result["manifest"])

    def test_recently_removed_entries_are_kept(self):
        pages = [_FakePage(f"{SITE}/p0/", "текст")]
        out = os.path.join(self.dir, "public")
        first = publish.build_sitemap(pages, out, SITE, manifest={}, today="2026-08-01")
        second = publish.build_sitemap([], out, SITE, manifest=first["manifest"],
                                       today="2026-08-10")
        self.assertIn(f"{SITE}/p0/", second["manifest"])

    def test_service_keys_are_not_reported_as_removed(self):
        pages = [_FakePage(f"{SITE}/p0/", "текст")]
        manifest = {"_shards": ["sitemap.xml"], f"{SITE}/p0/": {"notified": "x"}}
        diff = publish.diff_changed(pages, manifest)
        self.assertEqual(diff["removed"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
