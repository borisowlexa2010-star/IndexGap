# -*- coding: utf-8 -*-
"""
Регрессии. Каждый тест — воспроизведённая находка враждебного аудита.

Запуск: `python3 -m unittest discover -s tests` из корня репозитория.
Зависимостей нет.

Правило: находка без теста возвращается. Баг с очередью IndexNow чинился
дважды именно потому, что теста на него не было.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexgap import aeo, checks, content, core, doctor, engines, generate, publish, report
from indexgap.core import SourceError

SITE = "https://example.com"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-test-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel, text, encoding="utf-8"):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path) or self.dir, exist_ok=True)
        with open(path, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        return path

    def write_bytes(self, rel, data):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path) or self.dir, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def load(self, site=SITE):
        pages, problems = core.load_pages(self.dir, site)
        return pages, problems


# ── core: URL и ссылки ────────────────────────────────────────────────────────

class TestUrlMatching(Fixture):
    def test_flat_html_site_is_not_all_orphans(self):
        """URL страницы терял .html, ссылка — нет, и весь сайт был сиротами."""
        self.write("index.html",
                   '<html><body><a href="/about.html">О нас</a>'
                   '<a href="/guides/visa.html">Виза</a></body></html>')
        self.write("about.html", '<html><body><a href="/">Домой</a></body></html>')
        self.write("guides/visa.html", '<html><body><a href="/">Домой</a></body></html>')
        pages, _ = self.load()
        graph = checks.link_graph(pages, SITE)
        self.assertEqual(graph["orphans"], [])
        self.assertEqual(graph["unreachable"], [])

    def test_query_string_link_matches(self):
        self.assertEqual(core.url_key("https://example.com/t/?a=1"),
                         core.url_key("https://example.com/t?a=1"))

    def test_percent_encoded_matches(self):
        self.assertEqual(core.url_key("https://example.com/%D0%B2%D0%B8%D0%B7%D0%B0/"),
                         core.url_key("https://example.com/виза"))

    def test_index_md_and_html_collide_loudly(self):
        self.write("index.html", "<html><body><p>Раз</p></body></html>")
        self.write("index.md", "# Раз")
        pages, problems = self.load()
        self.assertEqual(len(pages), 1)
        self.assertTrue(any("один URL" in p for p in problems))

    def test_site_without_scheme_is_refused(self):
        with self.assertRaises(SourceError):
            core.check_site_url("example.com")

    def test_spaces_and_cyrillic_are_encoded(self):
        path = self.write("о нас.html", "<html><body><p>Текст</p></body></html>")
        url = core.path_to_url(path, self.dir, SITE + "/")
        self.assertNotIn(" ", url)
        self.assertIn("%", url)


# ── core: чтение файлов ───────────────────────────────────────────────────────

class TestReading(Fixture):
    def test_cp1251_is_decoded_not_mangled(self):
        self.write_bytes("a.html",
                         "<html><head><title>Виза в Сингапур</title></head>"
                         "<body><p>Текст страницы</p></body></html>".encode("cp1251"))
        pages, _ = self.load()
        self.assertEqual(pages[0].title, "Виза в Сингапур")
        self.assertTrue(any("cp1251" in n for n in pages[0].notes))

    def test_utf16_is_decoded(self):
        self.write_bytes("a.html",
                         "<html><head><title>Заголовок</title></head>"
                         "<body><p>Текст</p></body></html>".encode("utf-16"))
        pages, _ = self.load()
        self.assertEqual(pages[0].title, "Заголовок")

    def test_bom_frontmatter_is_parsed(self):
        self.write_bytes("a.md",
                         "﻿---\ntitle: Виза\ndescription: Описание\n---\n\nТекст"
                         .encode("utf-8"))
        pages, _ = self.load()
        self.assertEqual(pages[0].title, "Виза")

    def test_four_dashes_frontmatter(self):
        self.write("a.md", "----\ntitle: Виза\n----\n\nТекст")
        pages, _ = self.load()
        self.assertEqual(pages[0].title, "Виза")

    def test_unclosed_frontmatter_is_reported(self):
        self.write("a.md", "---\ntitle: Виза\n\nТекст без закрытия")
        pages, _ = self.load()
        self.assertTrue(pages[0].notes)

    def test_nested_yaml_does_not_override_title(self):
        self.write("a.md", "---\ntitle: Настоящий\nseo:\n  title: Вложенный\n---\n\nТекст")
        pages, _ = self.load()
        self.assertEqual(pages[0].title, "Настоящий")

    def test_broken_symlink_does_not_kill_the_run(self):
        self.write("ok.html", "<html><body><p>Живая страница</p></body></html>")
        link = os.path.join(self.dir, "broken.html")
        try:
            os.symlink(os.path.join(self.dir, "nope.html"), link)
        except (OSError, NotImplementedError):
            self.skipTest("симлинки недоступны")
        pages, problems = self.load()
        self.assertEqual(len(pages), 1)
        self.assertTrue(problems)

    def test_own_report_is_not_parsed_as_a_page(self):
        self.write("a.html", "<html><body><p>Страница</p></body></html>")
        self.write("indexgap-report.html", "<html><body><p>Отчёт</p></body></html>")
        pages, _ = self.load()
        self.assertEqual(len(pages), 1)

    def test_jekyll_underscore_dir_is_read(self):
        self.write("_posts/first.md", "---\ntitle: Пост\n---\n\nТекст")
        pages, _ = self.load()
        self.assertEqual(len(pages), 1)


# ── core: разбор HTML ─────────────────────────────────────────────────────────

class TestExtraction(Fixture):
    def test_template_links_do_not_hide_an_orphan(self):
        self.write("index.html",
                   '<html><body><template><a href="/sirota/">Сирота</a></template>'
                   '<p>Главная</p></body></html>')
        self.write("sirota/index.html", "<html><body><p>Одинокая</p></body></html>")
        pages, _ = self.load()
        graph = checks.link_graph(pages, SITE)
        self.assertIn(SITE + "/sirota/", graph["orphans"])

    def test_inline_tags_do_not_split_words(self):
        self.write("a.html", "<html><body><p>Виза<b>фри</b> режим</p></body></html>")
        pages, _ = self.load()
        self.assertIn("визафри", pages[0].words)

    def test_nav_and_footer_excluded_when_main_exists(self):
        self.write("a.html",
                   "<html><body><nav>Меню Каталог Контакты</nav>"
                   "<main><p>Уникальный текст страницы</p></main>"
                   "<footer>Подвал</footer></body></html>")
        pages, _ = self.load()
        self.assertNotIn("меню", pages[0].words)
        self.assertIn("уникальный", pages[0].words)

    def test_robots_none_is_noindex(self):
        self.write("a.html", '<html><head><meta name="robots" content="none">'
                             '</head><body><p>Текст</p></body></html>')
        pages, _ = self.load()
        self.assertTrue(pages[0].noindex)
        self.assertFalse(publish.indexable(pages[0]))

    def test_max_snippet_zero_is_caught(self):
        self.write("a.html", '<html><head><meta name="robots" content="max-snippet:0">'
                             '</head><body><p>Текст</p></body></html>')
        pages, _ = self.load()
        self.assertTrue(pages[0].nosnippet)

    def test_relative_canonical_is_absolutized(self):
        self.write("visa/index.html",
                   '<html><head><link rel="canonical" href="/visa/"></head>'
                   '<body><p>Текст</p></body></html>')
        pages, _ = self.load()
        self.assertTrue(publish.indexable(pages[0]))
        issues = checks.technical_issues(pages)
        self.assertFalse([i for i in issues if i[2] == "canonical-elsewhere"])

    def test_base_href_is_respected(self):
        self.write("guides/page.html",
                   '<html><head><base href="https://example.com/guides/"></head>'
                   '<body><a href="relative.html">Ссылка</a></body></html>')
        self.write("guides/relative.html", "<html><body><p>Цель</p></body></html>")
        pages, _ = self.load()
        source = [p for p in pages if "page" in p.url][0]
        self.assertIn("https://example.com/guides/relative", source.links[0])

    def test_markdown_image_is_not_a_link(self):
        self.write("a.md", "---\ntitle: Т\n---\n\n![Карта](/img/map.png) и [ссылка](/b/)")
        pages, _ = self.load()
        self.assertNotIn("Карта", pages[0].anchors)

    def test_heading_inside_code_fence_is_ignored(self):
        self.write("a.md", "---\ntitle: Т\n---\n\n# Установка\n\n```bash\n# комментарий\n```\n")
        pages, _ = self.load()
        levels = [t for lvl, t in pages[0].headings]
        self.assertEqual(levels, ["Установка"])

    def test_jsonld_is_captured_not_discarded(self):
        self.write("a.html",
                   '<html><body><script type="application/ld+json">'
                   '{"@type":"Article"}</script><p>Текст</p></body></html>')
        pages, _ = self.load()
        self.assertEqual(len(pages[0].jsonld), 1)


# ── checks: дубли ─────────────────────────────────────────────────────────────

class FakePage:
    def __init__(self, url, text, title="", description="", headings=None):
        self.url = url
        self.text = text
        self.title = title
        self.description = description
        self.headings = headings or []
        self.chrome = ""
        self.links = []
        self.anchors = []
        self.meta = {}
        self.raw = text
        self.canonical = ""
        self.robots = ""
        self.lang = "ru"
        self.notes = []
        self.jsonld = []
        self.paragraphs = [text]
        self.blocks = {}
        self.path = url

    key = property(lambda self: core.url_key(self.url))
    words = property(lambda self: core.Page.words.fget(self))
    word_count = property(lambda self: len(self.words))
    noindex = property(lambda self: core.Page.noindex.fget(self))
    nosnippet = property(lambda self: core.Page.nosnippet.fget(self))
    content_hash = property(lambda self: core.Page.content_hash.fget(self))


class TestDuplicates(unittest.TestCase):
    def test_large_cluster_is_not_silently_dropped(self):
        """201 одинаковая страница давала ровно ноль находок."""
        body = " ".join(["одинаковый текст страницы про аренду техники в городе"] * 12)
        pages = [FakePage(f"https://example.com/p{i}/", body + f" город{i}")
                 for i in range(260)]
        result = checks.find_near_duplicates(pages, {"exact_below": 50})
        self.assertGreater(len(result["pairs"]), 0)

    def test_identical_pages_are_found(self):
        pages = [FakePage(f"https://example.com/p{i}/",
                          "полностью одинаковый текст без единого отличия здесь")
                 for i in range(5)]
        result = checks.find_near_duplicates(pages)
        self.assertGreaterEqual(len(result["pairs"]), 4)

    def test_template_pages_are_reported_as_similar(self):
        """12 страниц одного шаблона давали «дублей не найдено»."""
        pages = []
        for i, city in enumerate(["москва", "спб", "казань", "омск", "тверь",
                                  "сочи", "уфа", "пермь", "тула", "курск",
                                  "самара", "ростов"]):
            text = (f"аренда экскаватора в городе {city} по низкой цене "
                    f"мы работаем без выходных и подаём технику быстро "
                    f"оставьте заявку и получите расчёт стоимости сегодня")
            pages.append(FakePage(f"https://example.com/{i}/", text))
        result = checks.find_near_duplicates(pages)
        self.assertGreater(len(result["pairs"]), 0)

    def test_boilerplate_needs_enough_pages(self):
        pages = [FakePage(f"https://example.com/p{i}/", "текст " * 30) for i in range(3)]
        profile = checks.boilerplate_profile(pages)
        self.assertEqual(profile["shares"], {})
        self.assertTrue(profile["skipped"])

    def test_output_is_deterministic(self):
        pages = [FakePage(f"https://example.com/p{i}/", f"текст страницы номер {i} " * 40)
                 for i in range(12)]
        first = checks.run_all(pages, home_url="https://example.com/p0/")
        second = checks.run_all(pages, home_url="https://example.com/p0/")
        self.assertEqual(first["issues"], second["issues"])


# ── checks: граф ──────────────────────────────────────────────────────────────

class TestGraph(Fixture):
    def test_missing_home_is_reported_not_faked(self):
        """Раньше главной становился самый короткий URL и 11 из 12 были сиротами."""
        for name in ("arenda-a", "arenda-b", "arenda-c"):
            self.write(f"{name}/index.md", f"---\ntitle: {name}\n---\n\nТекст {name}")
        pages, _ = self.load()
        graph = checks.link_graph(pages, SITE)
        self.assertIsNone(graph["home"])
        self.assertTrue(graph["home_missing"])
        self.assertEqual(graph["unreachable"], [])


# ── content: факты ────────────────────────────────────────────────────────────

class TestFacts(unittest.TestCase):
    def test_thousands_separator_is_not_a_decimal(self):
        self.assertEqual(content._norm_number("1,500"), "1500")
        self.assertEqual(content._norm_number("1,5"), "1.5")
        self.assertEqual(content._norm_number("12,345,678"), "12345678")

    def test_units_beyond_the_dataset_are_caught(self):
        """Из семи выдумок ловилась одна: единицы брались только из датасета."""
        rows = [{"keyword": "аренда экскаватора москва", "day_rate": "18000 RUB"}]
        page = FakePage("https://example.com/a/",
                        "Аренда экскаватора: 18000 RUB в сутки. Мы работаем 12 лет "
                        "и выполнили 3500 заказов, грузоподъёмность до 25 тонн.")
        page.meta = {"keyword": "аренда экскаватора москва"}
        matched = {page.url: rows[0]}
        issues = content.check_facts([page], matched, rows, fact_units=["rub"])
        text = " ".join(i[3] for i in issues)
        for number in ("12", "3500", "25"):
            self.assertIn(number, text)

    def test_template_wide_fabrication_is_not_pardoned(self):
        """Число на всех страницах прощалось как «общее для сайта»."""
        rows = [{"keyword": f"ключ-{chr(97+i%26)}{i//26}", "price": f"{100 + i} RUB"}
                for i in range(30)]
        pages, matched = [], {}
        for i, row in enumerate(rows):
            page = FakePage(f"https://example.com/p{i}/",
                            f"Цена {100 + i} RUB. Скидка 15%.")
            pages.append(page)
            matched[page.url] = row
        issues = content.check_facts(pages, matched, rows, fact_units=["rub"])
        flagged = [i for i in issues if i[2] == "unsupported-number"]
        self.assertEqual(len(flagged), 30)

    def test_sku_does_not_pardon_a_fake_number(self):
        rows = [{"keyword": "станок", "sku": "A-90-15", "power": "7 кВт"}]
        page = FakePage("https://example.com/a/", "Мощность 90 кВт при цене 7 кВт")
        page.meta = {"keyword": "станок"}
        issues = content.check_facts([page], {page.url: rows[0]}, rows,
                                     fact_units=["квт"])
        self.assertTrue([i for i in issues if "90" in i[3]])

    def test_ambiguous_match_is_refused(self):
        rows = [{"keyword": "виза сингапур"}, {"keyword": "сингапур виза"}]
        page = FakePage("https://example.com/a/", "Текст", title="Виза Сингапур")
        result = content.match_rows([page], rows, "keyword", ".")
        self.assertNotIn(page.url, result["matched"])
        self.assertIn(page.url, result["ambiguous"])


# ── generate ──────────────────────────────────────────────────────────────────

class TestGenerate(Fixture):
    def test_cp1251_csv_is_read(self):
        self.write_bytes("k.csv", "keyword;city\nвиза сингапур;Сингапур\n".encode("cp1251"))
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["city"], "Сингапур")

    def test_xlsx_gets_a_human_message(self):
        self.write_bytes("k.csv", b"PK\x03\x04rest-of-a-zip")
        with self.assertRaises(SourceError) as ctx:
            generate.read_dataset(os.path.join(self.dir, "k.csv"))
        self.assertIn("xlsx", str(ctx.exception))

    def test_ragged_row_does_not_crash_write(self):
        self.write("k.csv", "keyword,city\nвиза,Сингапур,ЛИШНЕЕ\nтур,Бали\n")
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        result = generate.write_tasks(audit, os.path.join(self.dir, "out"), "keyword")
        self.assertTrue(result["written"])
        self.assertTrue(data["problems"])

    def test_empty_pattern_segment_cannot_escape_out_dir(self):
        self.write("k.csv", "keyword,city\nчай купить,\nкофе купить,\n")
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        out = os.path.join(self.dir, "out")
        result = generate.write_tasks(audit, out, "keyword",
                                      path_pattern="{city}/{slug}.md")
        self.assertEqual(result["written"], [])
        self.assertEqual(len(result["failed"]), 2)
        self.assertFalse(os.path.exists("/чай-kupit.md"))

    def test_parent_traversal_is_blocked(self):
        self.write("k.csv", "keyword\nчай купить\n")
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        out = os.path.join(self.dir, "out")
        result = generate.write_tasks(audit, out, "keyword",
                                      path_pattern="../../escaped/{slug}.md")
        self.assertEqual(result["written"], [])

    def test_unknown_pattern_column_is_caught_early(self):
        with self.assertRaises(SourceError):
            generate.check_pattern("{country}/{slug}.md", ["keyword", "city"])

    def test_empty_optional_column_does_not_reject_everything(self):
        self.write("k.csv", "keyword,city,note\nчай,Москва,\nкофе,Питер,\n")
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        self.assertEqual(len(audit["keep"]), 2)
        self.assertTrue(audit["warnings"])

    def test_quotes_in_keyword_do_not_break_yaml(self):
        self.write("k.csv", 'keyword\n"кофе ""арабика"" купить"\n')
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        out = os.path.join(self.dir, "out")
        generate.write_tasks(audit, out, "keyword")
        written = []
        for dirpath, _, names in os.walk(out):
            written += [os.path.join(dirpath, n) for n in names]
        text = open(written[0], encoding="utf-8").read()
        line = [l for l in text.splitlines() if l.startswith("keyword:")][0]
        self.assertEqual(line.count('"') % 2, 0)

    def test_comment_terminator_in_data_is_neutralized(self):
        self.write("k.csv", "keyword,note\nчай,конец --> начало\n")
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        out = os.path.join(self.dir, "out")
        result = generate.write_tasks(audit, out, "keyword")
        text = open(result["written"][0], encoding="utf-8").read()
        self.assertEqual(text.count("-->"), 1)

    def test_long_keys_do_not_collapse_into_one_slug(self):
        a = "аренда квартиры в москве на длительный срок недорого с мебелью и парковкой рядом"
        b = a + " с центром"
        self.assertNotEqual(generate.slugify(a), generate.slugify(b))

    def test_synonyms_are_caught_across_word_order_and_prepositions(self):
        pairs = [("виза в сингапур", "сингапур виза"),
                 ("квартиры москва аренда", "аренда квартир в москве"),
                 ("ремонт стиральных машин москва", "ремонт стиральной машины в москве"),
                 ("buy iphone 15", "iphone 15 buy")]
        for a, b in pairs:
            with self.subTest(pair=(a, b)):
                self.assertEqual(generate.intent_key(a), generate.intent_key(b))

    def test_real_words_are_not_collapsed_by_the_stemmer(self):
        """Третий проход окончаний схлопывал «молоток» с «молотом»."""
        for a, b in [("молоток купить", "молот купить"),
                     ("каталог товаров", "катала товаров"),
                     ("звонок в дверь", "звон в дверь")]:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(generate.intent_key(a), generate.intent_key(b))

    def test_adjective_forms_are_a_known_miss(self):
        """
        «отели сочи недорого» и «недорогие отели в сочи» — один интент,
        но грубая нормализация их не сводит. Это осознанный размен: третий
        проход по окончаниям поймал бы эту пару и заодно склеил «молоток»
        с «молотом», удалив строку каталога молча. Пропуск дешевле.
        """
        self.assertNotEqual(generate.intent_key("отели сочи недорого"),
                            generate.intent_key("недорогие отели в сочи"))

    def test_numbers_keep_keys_apart(self):
        """Односимвольные цифры выбрасывались, и 80% каталога удалялось."""
        for a, b in [("1 комнатная квартира москва", "5 комнатная квартира москва"),
                     ("тариф 1 гб", "тариф 9 гб"),
                     ("окно 2 камерное", "окно 3 камерное")]:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(generate.intent_key(a), generate.intent_key(b))

    def test_own_slug_column_is_respected(self):
        self.write("k.csv", "keyword,slug\nаренда экскаватора москва,avto-ekskavator\n")
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        audit = generate.audit_dataset(data["rows"], data["fields"], "keyword")
        out = os.path.join(self.dir, "out")
        result = generate.write_tasks(audit, out, "keyword",
                                      path_pattern="{slug}/index.md")
        self.assertIn("avto-ekskavator", result["written"][0])

    def test_single_column_csv_keeps_commas_in_keys(self):
        self.write("k.csv", "keyword\nаренда, дома москва\n")
        data = generate.read_dataset(os.path.join(self.dir, "k.csv"))
        self.assertEqual(data["rows"][0]["keyword"], "аренда, дома москва")

    def test_longer_key_is_not_a_synonym(self):
        pairs = [("виза в сингапур", "виза в сингапур для россиян"),
                 ("iphone 15", "iphone 15 pro"),
                 ("аренда квартиры в москве недорого с мебелью посуточно",
                  "аренда квартиры в москве недорого с мебелью посуточно центр")]
        for a, b in pairs:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(generate.intent_key(a), generate.intent_key(b))

    def test_synonym_detection_survives_a_large_dataset(self):
        """Отсечка «токен чаще 400 раз» тихо выключала детектор на больших файлах."""
        rows = [{"keyword": f"аренда квартир город{i}"} for i in range(1000)]
        rows += [{"keyword": "аренда квартир москва"},
                 {"keyword": "москва квартир аренда"}]
        audit = generate.audit_dataset(rows, ["keyword"], "keyword")
        self.assertTrue(audit["near_synonyms"])


# ── publish ───────────────────────────────────────────────────────────────────

class TestPublish(Fixture):
    def _pages(self):
        for i in range(3):
            self.write(f"p{i}/index.md", f"---\ntitle: Стр {i}\n---\n\nТекст {i}")
        pages, _ = self.load()
        return pages

    def test_sitemap_does_not_wipe_the_notify_queue(self):
        """Баг, который чинится второй раз. Отсюда он больше не уйдёт."""
        pages = self._pages()
        manifest = publish.mark_notified({}, pages, [p.url for p in pages])
        result = publish.build_sitemap(pages, os.path.join(self.dir, "public"),
                                       SITE, manifest=manifest)
        diff = publish.diff_changed(pages, result["manifest"])
        self.assertEqual(diff["new"], [])
        self.assertEqual(diff["changed"], [])
        self.assertEqual(len(diff["unchanged"]), 3)

    def test_menu_change_does_not_requeue_the_whole_site(self):
        self.write("a.html", "<html><body><nav>Меню Акции</nav>"
                             "<main><p>Текст страницы про аренду</p></main></body></html>")
        pages, _ = self.load()
        before = pages[0].content_hash
        self.write("a.html", "<html><body><nav>Меню Скидки</nav>"
                             "<main><p>Текст страницы про аренду</p></main></body></html>")
        pages, _ = self.load()
        self.assertEqual(before, pages[0].content_hash)

    def test_title_change_does_change_the_hash(self):
        self.write("a.md", "---\ntitle: Раз\n---\n\nТекст")
        pages, _ = self.load()
        before = pages[0].content_hash
        self.write("a.md", "---\ntitle: Два\n---\n\nТекст")
        pages, _ = self.load()
        self.assertNotEqual(before, pages[0].content_hash)

    def test_key_with_traversal_is_refused(self):
        with self.assertRaises(SourceError):
            publish.check_key("../../etc/passwd")

    def test_shard_index_points_at_the_public_path(self):
        pages = [FakePage(f"https://example.com/p{i}/", "текст") for i in range(2)]
        publish.MAX_URLS_PER_FILE, saved = 1, publish.MAX_URLS_PER_FILE
        try:
            out = os.path.join(self.dir, "public", "sitemaps")
            publish.build_sitemap(pages, out, SITE, public_prefix="sitemaps")
            index = open(os.path.join(out, "sitemap.xml"), encoding="utf-8").read()
            self.assertIn("https://example.com/sitemaps/sitemap-1.xml", index)
        finally:
            publish.MAX_URLS_PER_FILE = saved

    def test_manifest_is_written_atomically(self):
        path = os.path.join(self.dir, "m.json")
        core.save_manifest(path, {"a": {"hash": "1"}, "_broken": True})
        data = json.load(open(path, encoding="utf-8"))
        self.assertNotIn("_broken", data)

    def test_broken_manifest_is_flagged_not_silently_empty(self):
        path = self.write("m.json", "{not json")
        self.assertTrue(core.load_manifest(path).get("_broken"))


# ── doctor ────────────────────────────────────────────────────────────────────

class TestDoctor(Fixture):
    def test_missing_sitemap_is_an_error_not_a_catastrophe(self):
        result = doctor.read_sitemap(os.path.join(self.dir, "nope.xml"))
        self.assertEqual(result["urls"], [])
        self.assertTrue(result["error"])

    def test_broken_xml_is_reported(self):
        path = self.write("s.xml", "<urlset><url>")
        self.assertTrue(doctor.read_sitemap(path)["error"])

    def test_percent_encoded_gsc_export_matches(self):
        self.write("виза/index.md", "---\ntitle: Виза\n---\n\nТекст")
        pages, _ = self.load()
        indexed = ["https://example.com/%D0%B2%D0%B8%D0%B7%D0%B0/"]
        result = doctor.funnel(pages, None, indexed)
        self.assertEqual(result["not_indexed"], [])

    def test_unknown_header_is_an_error_not_a_zero(self):
        path = self.write("x.csv", "колонкаа,значение\n1,2\n")
        with self.assertRaises(SourceError):
            doctor.read_indexed(path)

    def test_gsc_zip_gets_a_human_message(self):
        path = self.write_bytes("gsc.csv", b"PK\x03\x04zip")
        with self.assertRaises(SourceError) as ctx:
            doctor.read_indexed(path)
        self.assertIn("zip", str(ctx.exception).lower())

    def test_noindex_page_is_not_counted_as_missing_everywhere(self):
        self.write("a.md", "---\ntitle: А\nrobots: noindex\n---\n\nТекст")
        self.write("b.md", "---\ntitle: Б\n---\n\nТекст")
        pages, _ = self.load()
        funnel = doctor.funnel(pages, None, None,
                               by_engine={"bing": [SITE + "/b/"],
                                          "google": [SITE + "/b/"]})
        cross = doctor.cross_engine(funnel, pages)
        nowhere = [c for c in cross if c["kind"] == "нигде"]
        self.assertFalse(nowhere)

    def test_ambiguous_engine_is_not_guessed(self):
        engine, confident = engines.guess_engine("export.csv", ["url", "clicks"])
        self.assertFalse(confident)

    def test_duplicate_advice_is_not_harmful(self):
        pages = [FakePage("https://example.com/a/", "одинаковый текст здесь совсем"),
                 FakePage("https://example.com/b/", "одинаковый текст здесь совсем")]
        analysis = checks.run_all(pages, home_url="https://example.com/a/")
        funnel = doctor.funnel(pages, None, [])
        causes = doctor.explain(funnel, analysis)
        dupe = [c for c in causes if "дубли" in c["cause"]]
        if dupe:
            self.assertNotIn("связывать их ссылками между собой", dupe[0]["fix"][:20])
            self.assertIn("canonical", dupe[0]["fix"])


# ── aeo ───────────────────────────────────────────────────────────────────────

class TestAeo(Fixture):
    def test_blocked_ai_crawler_is_reported(self):
        path = self.write("robots.txt",
                          "User-agent: OAI-SearchBot\nDisallow: /\n\n"
                          "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml\n")
        issues = aeo.check_robots(aeo.read_robots(path))
        codes = [i[2] for i in issues]
        self.assertIn("ai-crawler-blocked", codes)

    def test_js_shell_is_caught(self):
        self.write("a.html",
                   "<html><body><div id=root></div>"
                   "<script src=1.js></script><script src=2.js></script>"
                   "<script src=3.js></script></body></html>")
        pages, _ = self.load()
        self.assertTrue(aeo.check_shell(pages[0]))

    def test_preamble_first_paragraph_is_flagged(self):
        page = FakePage("https://example.com/a/", "текст")
        page.paragraphs = ["В этой статье мы рассмотрим, как получить визу "
                           "в Сингапур и что для этого нужно."]
        issues = aeo.check_answer(page)
        self.assertTrue([i for i in issues if i[2] == "answer-preamble"])

    def test_broken_jsonld_is_flagged(self):
        page = FakePage("https://example.com/a/", "текст")
        page.jsonld = ['{"@type": "Article",}']
        self.assertTrue([i for i in aeo.check_jsonld(page) if i[2] == "jsonld-broken"])

    def test_faq_markup_must_match_the_text(self):
        page = FakePage("https://example.com/a/", "видимый текст страницы")
        page.jsonld = [json.dumps({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": "Сколько стоит виза в Сингапур?"}]})]
        self.assertTrue([i for i in aeo.check_jsonld(page)
                         if i[2] == "jsonld-faq-invisible"])


# ── report ────────────────────────────────────────────────────────────────────

class TestReport(Fixture):
    def test_no_class_of_findings_disappears_on_truncation(self):
        issues = ([("critical", f"https://example.com/a{i}/", "aaa-duplicate-title", "x")
                   for i in range(300)]
                  + [("critical", "https://example.com/z/", "unsupported-number", "y")]
                  + [("critical", "https://example.com/y/", "orphan", "z")])
        analysis = {"pages": [], "issues": issues, "graph": {"orphans": []},
                    "duplicates": [], "config": checks.CONFIG}
        path = report.build(analysis, out_path=os.path.join(self.dir, "r.html"))
        html = open(path, encoding="utf-8").read()
        self.assertIn("unsupported-number", html)
        self.assertIn("orphan", html)

    def test_unknown_level_is_escaped(self):
        issues = [("<script>alert(1)</script>", "https://example.com/a/", "code", "msg")]
        analysis = {"pages": [], "issues": issues, "graph": {}, "duplicates": [],
                    "config": checks.CONFIG}
        path = report.build(analysis, out_path=os.path.join(self.dir, "r.html"))
        html = open(path, encoding="utf-8").read()
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_empty_analysis_does_not_crash(self):
        path = report.build({}, out_path=os.path.join(self.dir, "r.html"))
        self.assertTrue(os.path.exists(path))

    def test_funnel_with_missing_keys_does_not_crash(self):
        analysis = {"pages": [], "issues": [], "graph": {}, "duplicates": [],
                    "config": checks.CONFIG}
        report.build(analysis, funnel_result={"steps": [{"name": "Шаг"}]},
                     causes=[{"cause": "нечто"}],
                     cross=[{"kind": "везде", "count": 1}],
                     out_path=os.path.join(self.dir, "r.html"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
