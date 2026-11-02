# -*- coding: utf-8 -*-
"""
ИИ-краулеры по логам сервера и цитирования в воронке.

Логи — единственные точные данные о том, видит ли сайт ИИ-поиск: панели,
как у Google, у ChatGPT и Perplexity нет. Ошибиться здесь легко в двух
местах: смешать обучающих ботов с поисковыми (GPTBot не делает страницу
источником ответа, OAI-SearchBot делает) и принять 403 от CDN за «бот не
приходил».
"""

import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cite, cli, core, crawlers, doctor
from indexgap.core import SourceError

SITE = "https://example.com"
UA = {
    "search": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot",
    "train": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot",
    "user": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    "pplx": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    "claude": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +Claude-SearchBot@anthropic.com)",
    "google": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "human": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15",
}


def combined(path, ua, status=200, method="GET"):
    return (f'203.0.113.7 - - [02/Nov/2026:10:00:00 +0000] "{method} {path} HTTP/1.1" '
            f'{status} 512 "-" "{ua}"')


def page(title):
    words = " ".join(f"{title} слово{j}" for j in range(150))
    return (f"<html><head><title>{title} — достаточно длинный заголовок</title></head>"
            f"<body><h1>{title}</h1><p>{words}</p><a href='/'>главная</a></body></html>")


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-ai-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def log(self, lines, name="access.log"):
        with open(self.path(name), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return self.path(name)

    def site(self, sections):
        root = self.path("site")
        for name, count in sections.items():
            for i in range(count):
                d = os.path.join(root, name, f"p{i}")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                    fh.write(page(f"{name} {i}"))
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page("главная"))
        pages, _ = core.load_pages(root, SITE)
        return root, pages


class TestWhoIsWho(unittest.TestCase):
    def test_each_bot_has_its_purpose(self):
        self.assertEqual(crawlers.identify(UA["search"])[2], crawlers.AI_SEARCH)
        self.assertEqual(crawlers.identify(UA["train"])[2], crawlers.TRAINING)
        self.assertEqual(crawlers.identify(UA["user"])[2], crawlers.AI_USER)
        self.assertEqual(crawlers.identify(UA["claude"])[2], crawlers.AI_SEARCH)
        self.assertEqual(crawlers.identify(UA["google"])[2], crawlers.SEARCH)
        self.assertEqual(crawlers.identify(UA["human"]), ())

    def test_a_longer_name_is_not_taken_for_a_shorter_one(self):
        """`Claude-SearchBot` содержит `claude`, но это не ClaudeBot для обучения."""
        self.assertEqual(crawlers.identify(UA["claude"])[0], "Claude-SearchBot")
        self.assertEqual(crawlers.identify("Mozilla/5.0 (compatible; ClaudeBot/1.0)")[0],
                         "ClaudeBot")

    def test_combined_and_json_lines_are_read(self):
        hit = crawlers.parse_line(combined("/a/?x=1", UA["search"], 304))
        self.assertEqual((hit["target"], hit["status"], hit["method"]), ("/a/?x=1", 304, "GET"))
        cf = crawlers.parse_line(json.dumps({
            "ClientRequestURI": "/b/", "ClientRequestHost": "example.com",
            "ClientRequestUserAgent": UA["user"], "EdgeResponseStatus": 200,
            "ClientRequestMethod": "GET"}))
        self.assertEqual((cf["target"], cf["host"], cf["status"]), ("/b/", "example.com", 200))
        nested = crawlers.parse_line(json.dumps({
            "request": {"path": "/c/", "userAgent": UA["pplx"]}, "status": 403}))
        self.assertEqual((nested["target"], nested["status"]), ("/c/", 403))

    def test_garbage_lines_are_skipped_not_crashed(self):
        for line in ("", "nonsense", "{not json", "[]", '{"url": "/a/"}', "1.2.3.4 - - [x] bad"):
            self.assertEqual(crawlers.parse_line(line), {}, line)


class TestReadLogs(Case):
    def test_pages_assets_and_robots_are_told_apart(self):
        path = self.log([combined("/a/", UA["search"]), combined("/app.js", UA["search"]),
                         combined("/img/x.webp", UA["search"]), combined("/robots.txt", UA["search"]),
                         combined("/b.html", UA["search"]), combined("/c/", UA["search"], method="POST")])
        bot = crawlers.read_logs([path], SITE)["bots"]["OAI-SearchBot"]
        self.assertEqual(bot["robots_txt"], 1)
        self.assertEqual(sorted(p["url"] for p in bot["pages"].values()),
                         [SITE + "/a/", SITE + "/b.html"])

    def test_gzip_is_read(self):
        path = self.path("access.log.gz")
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(combined("/a/", UA["user"]) + "\n")
        self.assertIn("ChatGPT-User", crawlers.read_logs([path], SITE)["bots"])

    def test_a_log_without_bots_is_explained(self):
        path = self.log([combined("/a/", UA["human"])])
        with self.assertRaises(SourceError) as caught:
            crawlers.read_logs([path], SITE)
        self.assertIn("ни одного известного бота", str(caught.exception))

    def test_a_missing_log_is_a_message(self):
        with self.assertRaises(SourceError):
            crawlers.read_logs([self.path("nope.log")], SITE)

    def test_encoded_and_plain_cyrillic_paths_are_one_page(self):
        path = self.log([combined("/%D0%B2%D0%B8%D0%B7%D0%B0/", UA["search"]),
                         combined("/виза/", UA["user"])])
        bots = crawlers.read_logs([path], SITE)["bots"]
        keys = set(bots["OAI-SearchBot"]["pages"]) | set(bots["ChatGPT-User"]["pages"])
        self.assertEqual(len(keys), 1)


class TestCoverage(Case):
    def test_training_bots_do_not_count_as_ai_search(self):
        _, pages = self.site({"a": 3})
        path = self.log([combined(f"/a/p{i}/", UA["train"]) for i in range(3)]
                        + [combined("/a/p0/", UA["search"])])
        got = crawlers.coverage(pages, crawlers.read_logs([path], SITE))
        self.assertEqual(got["ai_fetched_count"], 1)
        self.assertEqual(len(got["ai_not_fetched"]), 3)       # главная и две страницы

    def test_mass_403_is_named_as_a_cdn_block(self):
        """Cloudflare режет ИИ-ботов по умолчанию — это не «бот не приходил»."""
        _, pages = self.site({"a": 6})
        path = self.log([combined(f"/a/p{i}/", UA["pplx"], 403) for i in range(6)])
        got = crawlers.coverage(pages, crawlers.read_logs([path], SITE))
        self.assertTrue(any("PerplexityBot" in n and "CDN" in n for n in got["notes"]))
        self.assertEqual(len([e for e in got["errors"] if e["bot"] == "PerplexityBot"]), 6)

    def test_an_error_once_and_success_later_is_not_an_error(self):
        _, pages = self.site({"a": 2})
        path = self.log([combined("/a/p0/", UA["search"], 503), combined("/a/p0/", UA["search"])])
        got = crawlers.coverage(pages, crawlers.read_logs([path], SITE))
        self.assertEqual(got["errors"], [])

    def test_no_ai_search_at_all_is_said_aloud(self):
        _, pages = self.site({"a": 2})
        path = self.log([combined("/a/p0/", UA["google"])])
        got = crawlers.coverage(pages, crawlers.read_logs([path], SITE))
        self.assertTrue(any("невидим" in n for n in got["notes"]))

    def test_the_spoofing_caveat_is_always_there(self):
        _, pages = self.site({"a": 2})
        path = self.log([combined("/a/p0/", UA["search"])])
        got = crawlers.coverage(pages, crawlers.read_logs([path], SITE))
        self.assertTrue(any("User-Agent" in n for n in got["notes"]))

    def test_the_section_ai_search_skips_is_highlighted(self):
        _, pages = self.site({"rent": 20, "buy": 20})
        lines = [combined(f"/buy/p{i}/", UA["search"]) for i in range(20)]
        lines += [combined(f"/rent/p{i}/", UA["train"]) for i in range(20)]
        lines += [combined("/rent/p0/", UA["user"]), combined("/", UA["search"])]
        crawl = crawlers.coverage(pages, crawlers.read_logs([self.log(lines)], SITE))
        seg = doctor.ai_segments(pages, crawl)
        self.assertEqual([(h["segment"], h["lost"]) for h in seg["highlighted"]], [("/rent/", 19)])
        rent = next(r for r in seg["rows"] if r["segment"] == "/rent/")
        self.assertEqual(rent["ai_user"], 1)


class TestDoctor(Case):
    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_logs_alone_are_enough_for_doctor(self):
        root, _ = self.site({"rent": 10, "buy": 10})
        lines = [combined(f"/buy/p{i}/", UA["search"]) for i in range(10)]
        lines += [combined(f"/rent/p{i}/", UA["pplx"], 403) for i in range(10)]
        report = self.path("r.html")
        code, out = self.run_cli("doctor", root, "--site", SITE, "--logs", self.log(lines),
                                 "--out", report)
        self.assertEqual(code, 0, out)
        self.assertIn("Открыто ИИ-поиском (по логам)", out)
        self.assertIn("PerplexityBot      403  на 10 стр.", out)
        with open(self.path("r.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["ai_segments"]["highlighted"][0]["segment"], "/rent/")
        with open(report, encoding="utf-8") as fh:
            self.assertIn("Боты по логам сервера", fh.read())

    def test_a_missing_log_flag_is_an_error_not_a_green_run(self):
        root, _ = self.site({"a": 2})
        code, _ = self.run_cli("doctor", root, "--site", SITE, "--logs", self.path("nope.log"),
                               "--out", self.path("r.html"))
        self.assertEqual(code, 2)

    def test_a_cite_measurement_joins_the_funnel(self):
        root, pages = self.site({"rent": 6, "buy": 6})
        sm = self.path("sitemap.xml")
        listed = [p.url for p in pages if "/rent/p5/" not in p.url]
        with open(sm, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                     + "".join(f"<url><loc>{u}</loc></url>" for u in listed) + "</urlset>")
        measured = self.path("cite.json")
        with open(measured, "w", encoding="utf-8") as fh:
            json.dump({"domain": "example.com", "runs": 3, "providers": ["perplexity"],
                       "results": [{"prompt": "q", "provider": "perplexity", "runs": 3,
                                    "cited": 2, "urls": [SITE + "/buy/p1/"],
                                    "url_hits": {SITE + "/buy/p1/": 2, SITE + "/rent/p5/": 1}}]},
                      fh)
        code, out = self.run_cli("doctor", root, "--site", SITE, "--sitemap", sm,
                                 "--cite", measured, "--out", self.path("r.html"))
        self.assertEqual(code, 0, out)
        self.assertIn("Цитируется: Perplexity (замер indexgap cite)", out)
        self.assertIn("Цитируется, но в sitemap нет (1)", out)
        with open(self.path("r.json"), encoding="utf-8") as fh:
            rows = json.load(fh)["segments"]["rows"]
        self.assertEqual({r["segment"]: r.get("cited") for r in rows}["/buy/"], 1)

    def test_an_old_measurement_without_url_hits_still_reads(self):
        path = self.path("old.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"results": [{"provider": "openai", "urls": [SITE + "/a/"]}]}, fh)
        self.assertEqual(cite.read_result(path)["cited"], {"cite-openai": {SITE + "/a/": 1}})

    def test_a_file_that_is_not_a_measurement_is_named(self):
        path = self.path("x.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pages": 3}, fh)
        with self.assertRaises(SourceError):
            cite.read_result(path)


class TestCompare(Case):
    @staticmethod
    def measure(hits, competitors=(), runs=10, domain="example.com"):
        return {"domain": domain, "runs": runs, "providers": ["perplexity"], "results": [
            {"prompt": f"q{i}", "provider": "perplexity", "runs": runs, "cited": h,
             "urls": [f"{SITE}/a{i}/"] if h else [], "top_competitors": list(competitors)}
            for i, h in enumerate(hits)]}

    def test_fisher_matches_known_values(self):
        self.assertAlmostEqual(cite.fisher_p(0, 3, 3, 3), 0.1, places=6)
        self.assertAlmostEqual(cite.fisher_p(0, 3, 2, 3), 0.4, places=6)
        self.assertEqual(cite.fisher_p(5, 10, 5, 10), 1.0)
        self.assertEqual(cite.fisher_p(0, 0, 1, 3), 1.0)
        self.assertLess(cite.fisher_p(0, 30, 12, 30), 0.001)

    def test_a_small_wobble_is_noise(self):
        """1 из 3 → 2 из 3 — это не рост, и отчёт не должен называть его ростом."""
        diff = cite.compare(self.measure([2], runs=3), self.measure([1], runs=3))
        self.assertFalse(diff["rows"][0]["notable"])
        self.assertFalse(diff["providers"][0]["notable"])

    def test_a_real_shift_is_notable(self):
        diff = cite.compare(self.measure([6, 7, 1, 2]), self.measure([0, 1, 0, 2]))
        self.assertTrue(diff["providers"][0]["notable"])
        self.assertEqual(sorted(r["prompt"] for r in diff["rows"] if r["notable"]), ["q0", "q1"])

    def test_new_and_removed_questions_are_not_compared(self):
        now = self.measure([1, 1])
        before = self.measure([1])
        before["results"][0]["prompt"] = "old"
        diff = cite.compare(now, before)
        self.assertEqual(diff["rows"], [])
        self.assertEqual(len(diff["only_now"]), 2)
        self.assertEqual(diff["only_before"], ["[perplexity] old"])

    def test_competitors_that_came_and_went(self):
        diff = cite.compare(self.measure([1], [("rival.com", 5), ("new.com", 2)]),
                            self.measure([1], [("rival.com", 5), ("old.com", 2)]))
        row = diff["providers"][0]
        self.assertEqual((row["competitors_new"], row["competitors_gone"]), (["new.com"], ["old.com"]))

    def test_different_domains_are_flagged(self):
        diff = cite.compare(self.measure([1]), self.measure([1], domain="other.com"))
        self.assertTrue(diff["domain_changed"])

    def test_compare_two_files_sends_nothing(self):
        old, new = self.path("old.json"), self.path("new.json")
        for path, data in ((old, self.measure([0, 1, 0, 2])), (new, self.measure([6, 7, 1, 2]))):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen") as opened, mock.patch.object(sys, "stdout", out):
            code = cli.main(["cite", "--baseline", old, "--against", new])
        self.assertEqual(code, 0, out.getvalue())
        opened.assert_not_called()
        self.assertIn("заметно", out.getvalue())

    def test_against_without_baseline_is_explained(self):
        new = self.path("new.json")
        with open(new, "w", encoding="utf-8") as fh:
            json.dump(self.measure([1]), fh)
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            code = cli.main(["cite", "--against", new])
        self.assertEqual(code, 2)

    def test_a_fresh_measurement_records_how_often_each_url_was_cited(self):
        replies = [{"urls": [SITE + "/a/", SITE + "/a/"], "text": ""},
                   {"urls": [SITE + "/a/", SITE + "/b/"], "text": ""}]
        env = {"PERPLEXITY_API_KEY": "x"}
        with mock.patch.object(cite, "ask", side_effect=replies):
            got = cite.measure(["q"], "example.com", providers=["perplexity"], runs=2,
                               env=env, pause=0)
        self.assertEqual(got["results"][0]["url_hits"], {SITE + "/a/": 2, SITE + "/b/": 1})


if __name__ == "__main__":
    unittest.main()
