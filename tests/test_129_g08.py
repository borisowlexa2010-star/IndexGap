# -*- coding: utf-8 -*-
"""
1.29 (g08): заглушки-редиректы в сборке и разбор robots.txt.

Заглушки: meta refresh без `url=`, редирект одним скриптом, NEXT_REDIRECT с
шапкой вокруг пустого <main>, цель с параметрами, цель в разделе, которого
нет, петли заглушек, заглушки на главную — в `check` и в `diff`.

robots.txt: пустая строка и комментарий между User-agent, правила до первой
группы, опечатки Google, `Allow` разделов при `Disallow: /`, наследование `*`
ботами ИИ-поиска, Яндекс и Applebot, длина правила в %-записи, пустой и
относительный Sitemap, маршрут Next.js `robots.txt/` при явном --robots.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, core, diff

SITE = "https://demo.example"
BODY = " ".join(f"word{i} sentence about renting flats in the city" for i in range(20))


class Site:
    def __init__(self, case):
        self.root = tempfile.mkdtemp(prefix="indexgap-129-")
        case.addCleanup(shutil.rmtree, self.root, True)

    def write(self, path, html):
        folder = os.path.join(self.root, path.strip("/"))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html)

    def page(self, path, title, links=(), head=""):
        anchors = "".join(f'<a href="{u}">{u}</a> ' for u in links)
        self.write(path, f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                         f'<title>{title} guide page</title>{head}</head><body><h1>{title}</h1>'
                         f'<p>{BODY}</p><nav>{anchors}</nav></body></html>')

    def stub(self, path, head="", body=""):
        self.write(path, f'<!doctype html><html><head><meta charset="utf-8"><title>Moved</title>'
                         f'{head}</head><body>{body}</body></html>')

    def file(self, name, text):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def pages(self):
        return core.load_pages(self.root, SITE)[0]

    def run(self):
        return checks.run_all(self.pages(), SITE + "/")


def found(result, code):
    return {(i[0], i[1].replace(SITE, "")) for i in result["issues"] if i[2] == code}


def refresh(url, delay="0", keyword="url="):
    return f'<meta http-equiv="refresh" content="{delay}; {keyword}{url}">'


class RedirectStubs(unittest.TestCase):
    def base(self, links):
        site = Site(self)
        site.page("/", "Home", links=list(links) + ["/rent/a/", "/rent/b/"])
        site.page("/rent/a/", "Alpha", links=["/"])
        site.page("/rent/b/", "Beta", links=["/"])
        return site

    def test_refresh_without_url_keyword_is_a_stub(self):
        site = self.base(["/v1/"])
        site.stub("/v1/", head=refresh("/rent/missing/", keyword=""))
        self.assertEqual(checks.redirect_target([p for p in site.pages()
                                                 if p.url.endswith("/v1/")][0]),
                         SITE + "/rent/missing/")
        self.assertIn(("warning", "/v1/"), found(site.run(), "broken-link"))

    def test_one_line_script_redirect_is_a_stub_not_a_js_shell(self):
        site = self.base(["/v2/"])
        site.stub("/v2/", head='<script>window.location.replace("/rent/missing/")</script>')
        result = site.run()
        self.assertIn(("warning", "/v2/"), found(result, "broken-link"))
        self.assertFalse(found(result, "js-shell"))

    def test_conditional_script_redirect_is_not_a_stub(self):
        site = self.base([])
        site.stub("/app/", body='<div id="root"></div><script>if (!window.user) '
                                'location.href = "/login/";</script>')
        page = [p for p in site.pages() if p.url.endswith("/app/")][0]
        self.assertEqual(checks.redirect_target(page), "")

    def test_next_redirect_digest_with_layout_text_is_a_stub(self):
        site = self.base(["/connect/"])
        nav = " ".join(f"menu{i}" for i in range(40))
        site.write("/connect/", '<!doctype html><html><head><meta charset="utf-8"></head><body>'
                   f'<header><p>{nav}</p></header><main></main><script>'
                   'self.__next_f.push([1,"0:{\\"digest\\":\\"NEXT_REDIRECT;replace;'
                   '/rent/missing;307;\\"}"])</script></body></html>')
        self.assertIn(("warning", "/connect/"), found(site.run(), "broken-link"))

    def test_next_redirect_mentioned_in_a_long_page_is_not_a_stub(self):
        site = self.base([])
        site.page("/blog/", "Blog", head='<script>var x = "NEXT_REDIRECT;replace;/a;307;";</script>')
        page = [p for p in site.pages() if p.url.endswith("/blog/")][0]
        self.assertEqual(checks.redirect_target(page), "")

    def test_target_with_query_string_is_still_a_link(self):
        site = self.base(["/old/"])
        site.page("/rent/c/", "Gamma", links=["/"])
        site.stub("/old/", head=refresh("/rent/c/?from=old"))
        self.assertNotIn(("critical", "/rent/c/"), found(site.run(), "orphan"))

    def test_target_in_a_section_missing_from_the_build_is_broken(self):
        site = self.base(["/rent/old/"])
        site.stub("/rent/old/", head=refresh("/guides/alpha/"))
        self.assertIn(("warning", "/rent/old/"), found(site.run(), "broken-link"))

    def test_a_link_into_a_missing_section_stays_lenient(self):
        site = self.base(["/guides/alpha/"])
        self.assertFalse(found(site.run(), "broken-link"))

    def test_loop_of_stubs_is_reported(self):
        site = self.base(["/go/a/", "/go/b/"])
        site.stub("/go/a/", head=refresh("/go/b/"))
        site.stub("/go/b/", head=refresh("/go/a/"))
        bad = found(site.run(), "broken-link")
        self.assertIn(("warning", "/go/a/"), bad)
        self.assertIn(("warning", "/go/b/"), bad)

    def test_chain_without_loop_is_not_a_loop(self):
        site = self.base(["/go/a/"])
        site.stub("/go/a/", head=refresh("/go/b/"))
        site.stub("/go/b/", head=refresh("/rent/a/"))
        self.assertFalse(found(site.run(), "broken-link"))

    def test_content_page_redirected_home_is_a_warning(self):
        site = self.base([])
        site.page("/rent/c/", "Gamma", head=refresh("/"))
        site.stub("/old/", head=refresh("/"))
        home = found(site.run(), "redirect-home")
        self.assertIn(("warning", "/rent/c/"), home)
        self.assertIn(("info", "/old/"), home)

    def test_stub_to_another_page_is_quiet(self):
        site = self.base(["/old/"])
        site.stub("/old/", head=refresh("/rent/a/"))
        result = site.run()
        self.assertFalse(found(result, "redirect-home"))
        self.assertFalse(found(result, "broken-link"))


class DiffStubs(unittest.TestCase):
    def build(self, stubs=None):
        site = Site(self)
        site.page("/", "Home", links=["/rent/a/", "/rent/b/", "/rent/c/"])
        for name in ("a", "b", "c"):
            path = f"/rent/{name}/"
            if stubs and path in stubs:
                site.stub(path, head=refresh(stubs[path]))
            else:
                site.page(path, name.upper(), links=["/"])
        return site.pages()

    def closed(self, stubs):
        result = diff.compare(self.build(), self.build(stubs))
        return {c["url"].replace(SITE, ""): c["level"] for c in result["closed"]}

    def test_stub_to_home_is_critical(self):
        self.assertEqual(self.closed({"/rent/a/": "/"}), {"/rent/a/": "critical"})

    def test_loop_is_critical(self):
        self.assertEqual(self.closed({"/rent/a/": "/rent/b/", "/rent/b/": "/rent/a/"}),
                         {"/rent/a/": "critical", "/rent/b/": "critical"})

    def test_stub_to_a_live_page_stays_info(self):
        self.assertEqual(self.closed({"/rent/a/": "/rent/b/"}), {"/rent/a/": "info"})


class Robots(unittest.TestCase):
    def setUp(self):
        self.site = Site(self)
        self.site.page("/", "Home", links=["/rent/a/", "/rent/b/", "/about/"])
        for path in ("/rent/a/", "/rent/b/", "/about/"):
            self.site.page(path, path.strip("/"), links=["/"])

    def read(self, text):
        return aeo.read_robots(self.site.file("robots.txt", text))

    def findings(self, text):
        robots = self.read(text)
        pages = self.site.pages()
        out = aeo.check_robots(robots, pages) + aeo.check_blocked_pages(pages, robots)
        return {(i[0], i[1].replace(SITE, ""), i[2]) for i in out}

    def test_blank_or_comment_line_between_agents_keeps_one_group(self):
        for gap in ("\n", "# note\n"):
            robots = self.read(f"User-agent: Googlebot\n{gap}User-agent: *\nDisallow: /rent/\n")
            self.assertEqual(aeo.blocking_rule(robots, "/rent/a/"), "/rent/", gap)

    def test_rules_before_any_agent_are_ignored(self):
        robots = self.read("Disallow: /\n\nUser-agent: *\nDisallow: /tmp/\n")
        self.assertEqual(aeo.blocking_rule(robots, "/rent/a/"), "")

    def test_typos_and_missing_colon_are_read_as_google_does(self):
        for line in ("Disalow: /", "Disallow /"):
            robots = self.read(f"User-agent: *\n{line}\n")
            self.assertEqual(aeo.blocking_rule(robots, "/rent/a/"), "/", line)

    def test_allowlist_robots_is_not_a_full_block(self):
        got = self.findings("User-agent: *\nDisallow: /\nAllow: /rent/\nAllow: /about/\n"
                            "Allow: /$\nSitemap: https://demo.example/sitemap.xml\n")
        self.assertFalse({f for f in got if f[2].startswith("robots-blocks")})
        got = self.findings("User-agent: *\nDisallow: /\nAllow: *\n"
                            "Sitemap: https://demo.example/sitemap.xml\n")
        self.assertFalse({f for f in got if f[2].startswith("robots-blocks")})

    def test_home_only_allow_is_still_a_full_block(self):
        got = self.findings("User-agent: *\nDisallow: /\nAllow: /$\n"
                            "Sitemap: https://demo.example/sitemap.xml\n")
        self.assertIn(("critical", "robots.txt", "robots-blocks-all"), got)
        self.assertFalse({f for f in got if f[2] == "robots-blocks-page"})

    def test_star_partial_block_reaches_ai_search_bots(self):
        got = self.findings("User-agent: Googlebot\nAllow: /\n\nUser-agent: *\n"
                            "Disallow: /rent/\nSitemap: https://demo.example/sitemap.xml\n")
        self.assertIn(("critical", "robots.txt", "ai-crawler-blocked"), got)

    def test_star_partial_for_everyone_is_one_page_level_finding(self):
        got = self.findings("User-agent: *\nDisallow: /rent/\n"
                            "Sitemap: https://demo.example/sitemap.xml\n")
        self.assertFalse({f for f in got if f[2] == "ai-crawler-blocked"})
        self.assertIn(("critical", "/rent/a/", "robots-blocks-page"), got)

    def test_only_yandex_open_is_critical(self):
        got = self.findings("User-agent: *\nDisallow: /\n\nUser-agent: Yandex\nAllow: /\n"
                            "Sitemap: https://demo.example/sitemap.xml\n")
        self.assertIn(("critical", "robots.txt", "robots-blocks-all"), got)
        got = self.findings("User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nAllow: /\n"
                            "Sitemap: https://demo.example/sitemap.xml\n")
        self.assertIn(("warning", "robots.txt", "robots-blocks-all"), got)

    def test_partial_ai_block_shown_while_googlebot_is_closed(self):
        got = self.findings("User-agent: Googlebot\nDisallow: /\n\nUser-agent: OAI-SearchBot\n"
                            "Disallow: /rent/\n\nUser-agent: *\nAllow: /\n"
                            "Sitemap: https://demo.example/sitemap.xml\n")
        self.assertIn(("critical", "robots.txt", "robots-blocks-all"), got)
        self.assertTrue({f for f in got if f[2] == "ai-crawler-blocked"})

    def test_other_search_engines_closed_is_a_warning(self):
        got = self.findings("User-agent: *\nAllow: /\n\nUser-agent: Yandex\nDisallow: /\n\n"
                            "User-agent: Applebot\nDisallow: /\n"
                            "Sitemap: https://demo.example/sitemap.xml\n")
        self.assertEqual({f for f in got if f[2] == "robots-blocks-all"},
                         {("warning", "robots.txt", "robots-blocks-all")})

    def test_rule_length_is_counted_in_percent_form(self):
        robots = self.read("User-agent: *\nDisallow: /%D0%BA%D0%B0%D1%82/\n"
                           "Allow: /кат/berlin/\n")
        self.assertEqual(aeo.blocking_rule(robots, "/кат/berlin/"), "")
        self.assertEqual(aeo.blocking_rule(robots, "/кат/other/"), "/%D0%BA%D0%B0%D1%82/")

    def test_empty_or_relative_sitemap_is_not_declared(self):
        for line in ("Sitemap:", "Sitemap: /sitemap.xml"):
            got = self.findings(f"User-agent: *\nAllow: /\n{line}\n")
            self.assertIn(("info", "robots.txt", "robots-no-sitemap"), got, line)

    def test_next_route_folder_reads_its_body(self):
        folder = os.path.join(self.site.root, "robots.txt")
        os.makedirs(folder)
        self.site.file(os.path.join("robots.txt", "route.js"), "export const GET = 1;\n")
        self.site.file("robots.txt.body", "User-agent: *\nDisallow: /rent/\n")
        robots = aeo.read_robots(folder)
        self.assertTrue(robots["found"])
        self.assertEqual(aeo.blocking_rule(robots, "/rent/a/"), "/rent/")


if __name__ == "__main__":
    unittest.main()
