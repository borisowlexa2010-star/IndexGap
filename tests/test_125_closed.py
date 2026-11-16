# -*- coding: utf-8 -*-
"""
1.25: закрытые страницы, которые отчёт считал закрытыми намеренно — или не
видел закрытыми вовсе.

* canonical на главную или хаб раздела считался «печатной копией»;
* `User-agent: Googlebot` + `Disallow: /` и частичный запрет ИИ-поиска
  не давали ни одной находки;
* закрытый раздел, который стоит в sitemap, понижался до сведений;
* мета-переадресация в строке JavaScript превращала страницу в заглушку;
* `X-Robots-Tag: nosnippet` из `_headers` не переносился на страницы;
* недочитанный sitemap и `?utm_` в нём понижали критичный noindex;
* `draft: true` и родня убирали страницу из отчёта без объяснения.
"""

import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, cli, core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


def run_check(folder, *extra):
    out = os.path.join(folder, "r.json")
    with mock.patch.object(sys, "stdout", io.StringIO()):
        cli.main(["check", folder, "--site", SITE, "--out", out, *extra])
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)["issues"]


class Demo(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(prefix="indexgap-125-"), "site")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir), True)
        shutil.copytree(DEMO, self.dir)
        self.dataset = os.path.join(self.dir, "cities.csv")

    def edit(self, slug, change):
        path = os.path.join(self.dir, "rent", slug, "index.html")
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(change(html))

    def slugs(self):
        return sorted(s for s in os.listdir(os.path.join(self.dir, "rent"))
                      if os.path.isdir(os.path.join(self.dir, "rent", s)))

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def pages(self):
        return core.load_pages(self.dir, SITE)[0]

    def page(self, slug):
        return next(p for p in self.pages() if p.url.endswith(f"/rent/{slug}/"))


class TestCanonicalToHomeOrHub(Demo):
    def test_canonical_to_the_home_page_is_not_a_print_copy(self):
        tag = f'<link rel="canonical" href="{SITE}/">'
        for slug in self.slugs():
            self.edit(slug, lambda h: h.replace("</head>", tag + "</head>", 1))
        issues = run_check(self.dir, "--dataset", self.dataset)
        found = [i for i in issues if i["code"] == "canonical-elsewhere"]
        self.assertTrue(found)
        self.assertEqual({i["level"] for i in found}, {"critical"})
        hamburg = {i["code"] for i in issues if i["url"].endswith("/rent/hamburg/")}
        self.assertIn("unsupported-number", hamburg)

    def twin(self, source, url, canonical):
        page = copy.copy(source)
        page.url, page.canonical = url, canonical
        return page

    def test_a_child_of_a_hub_is_not_its_variant(self):
        berlin, hamburg = self.page("berlin"), self.page("hamburg")
        hub = self.twin(berlin, SITE + "/rent/", SITE + "/rent/")
        child = self.twin(hamburg, SITE + "/rent/hamburg/", hub.url)
        self.assertFalse(checks._a_variant_of(child, hub))

    def test_print_amp_and_pagination_under_a_page_stay_variants(self):
        berlin, hamburg = self.page("berlin"), self.page("hamburg")
        for tail in ("print/", "index.print/", "amp/", "page/2/", "2/"):
            copy_ = self.twin(hamburg, berlin.url + tail, berlin.url)
            self.assertTrue(checks._a_variant_of(copy_, berlin), tail)


class TestGooglebotGroup(unittest.TestCase):
    def robots(self, text):
        folder = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "robots.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return aeo.read_robots(path)

    def test_googlebot_disallow_all_is_critical(self):
        robots = self.robots("User-agent: *\nAllow: /\n\nUser-agent: Googlebot\nDisallow: /\n")
        found = [i for i in aeo.check_robots(robots) if i[2] == "robots-blocks-all"]
        self.assertEqual([i[0] for i in found], ["critical"])

    def test_an_open_googlebot_group_says_nothing(self):
        robots = self.robots("User-agent: *\nAllow: /\n\nUser-agent: Googlebot\nDisallow: /tmp/\n")
        self.assertFalse([i for i in aeo.check_robots(robots) if i[2] == "robots-blocks-all"])


class TestPartialAiBlock(Demo):
    def found(self, robots):
        self.write("robots.txt", robots)
        robots = aeo.read_robots(os.path.join(self.dir, "robots.txt"))
        return [i for i in aeo.check_blocked_pages(self.pages(), robots)
                if i[2] == "ai-crawler-blocked"]

    def test_a_blocked_catalog_is_critical(self):
        for agent in ("OAI-SearchBot", "Bingbot"):
            found = self.found(f"User-agent: *\nAllow: /\n\nUser-agent: {agent}\nDisallow: /rent/\n")
            self.assertEqual([i[0] for i in found], ["critical"], agent)
            self.assertIn("/rent/", found[0][3])

    def test_a_small_blocked_corner_is_a_warning(self):
        found = self.found("User-agent: *\nAllow: /\n\nUser-agent: OAI-SearchBot\nDisallow: /about/\n")
        self.assertEqual([i[0] for i in found], ["warning"])

    def test_a_crawler_without_its_own_group_is_not_reported(self):
        self.assertEqual(self.found("User-agent: *\nDisallow: /about/\n"), [])


class TestSitemapAndClosedPages(unittest.TestCase):
    url = SITE + "/rent/cologne/"

    def test_a_closed_section_still_in_the_sitemap_is_critical(self):
        issues = [("info", self.url, "noindex", "x")]
        out = checks.closed_off_map(issues, [self.url])
        self.assertEqual(out[0][0], "critical")

    def test_a_print_page_in_the_sitemap_stays_info(self):
        url = SITE + "/rent/print/"
        out = checks.closed_off_map([("info", url, "noindex", "x")], [url])
        self.assertEqual(out[0][0], "info")

    def test_a_tracking_query_in_the_sitemap_still_lists_the_page(self):
        issues = [("critical", self.url, "noindex", "x")]
        out = checks.closed_off_map(issues, [self.url + "?utm_source=feed", SITE + "/"])
        self.assertEqual(out[0][0], "critical")

    def test_an_incomplete_sitemap_does_not_lower_noindex(self):
        issues = [("critical", self.url, "noindex", "x")]
        self.assertEqual(checks.closed_off_map(issues, [SITE + "/"], complete=False)[0][0],
                         "critical")
        self.assertEqual(checks.closed_off_map(issues, [SITE + "/"])[0][0], "info")

    def test_a_closed_template_section_in_the_sitemap_fails_strict(self):
        folder = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, folder, True)
        body = "<p>" + " ".join(f"word{i}" for i in range(400)) + "</p>"
        urls = [SITE + "/"]
        pages = {"index.html": "<h1>Home</h1>" + body}
        for section, n, head in (("rent", 20, '<meta name="robots" content="noindex">'),
                                 ("buy", 21, "")):
            for i in range(n):
                pages[f"{section}/city{i}/index.html"] = (
                    f"<head><title>{section} in city {i} for families</title>{head}</head>"
                    f"<h1>{section} {i}</h1><p>{section} city{i} unique{i} text.</p>" + body)
                urls.append(f"{SITE}/{section}/city{i}/")
        for name, text in pages.items():
            path = os.path.join(folder, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"<!doctype html><html lang=\"en\">{text}</html>")
        sitemap = os.path.join(folder, "sitemap.xml")
        with open(sitemap, "w", encoding="utf-8") as fh:
            fh.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                     + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
        issues = run_check(folder, "--sitemap", sitemap)
        levels = {i["level"] for i in issues if i["code"] == "noindex"}
        self.assertEqual(levels, {"critical"})


class TestRedirectStubs(Demo):
    def test_a_refresh_inside_a_script_string_is_not_a_stub(self):
        tag = "<script>var f = '<meta http-equiv=\"refresh\" content=\"0;url=/rent/\">';</script>"
        self.edit("hamburg", lambda h: h.replace("</body>", tag + "</body>", 1))
        self.assertEqual(checks.redirect_target(self.page("hamburg")), "")

    def test_a_refresh_inside_a_script_of_a_large_page_is_not_a_stub(self):
        """Исходник больше 4 КБ хранится выжимкой: тег из скрипта в неё не попадает."""
        tag = ("<script>var f = '<meta http-equiv=\"refresh\" content=\"0;url=/rent/\">';"
               + "/*" + "x" * 6000 + "*/</script>")
        self.edit("hamburg", lambda h: h.replace("</body>", tag + "</body>", 1))
        self.assertEqual(checks.redirect_target(self.page("hamburg")), "")

    def test_a_refresh_inside_a_template_is_not_a_stub(self):
        tag = '<template><meta http-equiv="refresh" content="0;url=/rent/"></template>'
        self.edit("hamburg", lambda h: h.replace("</body>", tag + "</body>", 1))
        self.assertEqual(checks.redirect_target(self.page("hamburg")), "")

    def test_a_refresh_to_itself_is_not_a_stub(self):
        tag = '<meta http-equiv="refresh" content="1;url=/rent/hamburg/">'
        self.edit("hamburg", lambda h: h.replace("</head>", tag + "</head>", 1))
        self.assertEqual(checks.redirect_target(self.page("hamburg")), "")

    def test_a_live_refresh_is_still_a_stub(self):
        tag = '<meta http-equiv="refresh" content="0;url=/rent/">'
        self.edit("hamburg", lambda h: h.replace("</head>", tag + "</head>", 1))
        self.assertEqual(checks.redirect_target(self.page("hamburg")), SITE + "/rent/")


class TestSnippetHeader(Demo):
    def test_headers_nosnippet_reaches_the_pages(self):
        self.write("_headers", "/rent/*\n  X-Robots-Tag: nosnippet\n")
        by_url = {p.url: p for p in self.pages()}
        self.assertTrue(by_url[SITE + "/rent/berlin/"].nosnippet)
        self.assertFalse(by_url[SITE + "/about/"].nosnippet)

    def test_vercel_max_snippet_zero_reaches_the_pages(self):
        self.write("vercel.json", json.dumps({"headers": [{
            "source": "/rent/(.*)",
            "headers": [{"key": "X-Robots-Tag", "value": "max-snippet:0"}]}]}))
        self.assertTrue(self.page("berlin").nosnippet)

    def test_a_snippet_rule_for_another_bot_does_not_apply(self):
        self.write("_headers", "/rent/*\n  X-Robots-Tag: bingbot: nosnippet\n")
        self.assertFalse(self.page("berlin").nosnippet)


class TestOtherDrafts(unittest.TestCase):
    def test_every_draft_marker_says_why(self):
        folder = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, folder, True)
        marks = {"munich": "draft: true", "hamburg": "published: false",
                 "cologne": "status: wip", "frankfurt": "publishDate: 2099-01-01",
                 "dresden": ""}
        for slug, mark in marks.items():
            with open(os.path.join(folder, f"{slug}.md"), "w", encoding="utf-8") as fh:
                fh.write(f"---\ntitle: \"Renting in {slug}: rent and deposit\"\n{mark}\n---\n\n"
                         f"# Renting in {slug}\n\nA flat in {slug} costs a fair amount.\n")
        issues = run_check(folder)
        drafts = {i["url"].rstrip("/").rsplit("/", 1)[-1]: i["level"]
                  for i in issues if i["code"] == "still-draft"}
        self.assertEqual(drafts, {"munich": "critical", "hamburg": "critical",
                                  "cologne": "critical", "frankfurt": "info"})


if __name__ == "__main__":
    unittest.main()
