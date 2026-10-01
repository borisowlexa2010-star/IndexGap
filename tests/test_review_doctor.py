# -*- coding: utf-8 -*-
"""
`doctor`: находки ревью десяти агентов перед публичным запуском.

`--live` спрашивал сайт не о том адресе, что стоял в выгрузке, а о его ключе
для сравнения — без завершающего слэша, без `.html`, без `www`. Живая страница
`/live-dir/` запрашивалась как `/live-dir`, сервер отвечал 301 на свой же
адрес со слэшем, и страница попадала в «уже в порядке». Проверка, которая
должна отделять сделанное от несделанного, подтверждала несделанное.
"""

import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import doctor

SITE = "https://www.example.com"


def probe(table, asked=None):
    def fake(url, timeout=10):
        if asked is not None:
            asked.append(url)
        return table.get(url, (None, {}))
    return fake


class TestLiveAsksTheExportedAddress(unittest.TestCase):
    def test_live_probes_the_exported_url_not_the_normalised_key(self):
        exported = [f"{SITE}/live-dir/", f"{SITE}/live.html", f"{SITE}/путь/"]
        funnel = doctor.funnel([], by_engine={"google": exported})
        foreign = doctor.foreign_urls(funnel, SITE)
        asked = []
        table = {f"{SITE}/live-dir/": (200, {}), f"{SITE}/live.html": (200, {}),
                 f"{SITE}/%D0%BF%D1%83%D1%82%D1%8C/": (200, {}),
                 # То, что спрашивалось раньше: ключ без слэша, расширения и www.
                 "https://example.com/live-dir": (301, {"Location": f"{SITE}/live-dir/"}),
                 "https://example.com/live": (404, {})}
        with mock.patch.object(doctor, "_probe", probe(table, asked)):
            result = doctor.verify_live(foreign)
        self.assertEqual(sorted(asked), sorted([
            f"{SITE}/live-dir/", f"{SITE}/live.html",
            f"{SITE}/%D0%BF%D1%83%D1%82%D1%8C/"]))
        self.assertEqual(result["done"], [])
        self.assertEqual(len(result["todo"]), 3)


class TestLiveReadsRobots(unittest.TestCase):
    def verify(self, answer, kind="other_hosts"):
        foreign = {"other_hosts": [], "missing": [], "files": []}
        foreign[kind] = ["//stage.example.com/"]
        with mock.patch.object(doctor, "_probe", probe({"https://stage.example.com/": answer})):
            return doctor.verify_live(foreign)

    def test_host_closed_by_meta_robots_or_second_header_is_done(self):
        for answer in ((200, {"X-Robots-Tag": "nofollow, noindex"}),
                       (200, {"X-Robots-Tag": "none"}),
                       (200, {"X-Robots-Tag": "googlebot: noindex"}),
                       (200, {"_body": '<html><head><meta name="robots" content="noindex,nofollow">'}),
                       (200, {"_body": "<meta content='none' name='robots'>"})):
            self.assertEqual(self.verify(answer)["done"], ["//stage.example.com/"], answer)

    def test_a_rule_for_another_bot_closes_nothing(self):
        result = self.verify((200, {"X-Robots-Tag": "otherbot: noindex"}))
        self.assertEqual([i["key"] for i in result["todo"]], ["//stage.example.com/"])

    def test_5xx_429_and_redirect_loops_are_unknown_not_done_or_open(self):
        for status in (500, 503, 429):
            for kind in ("other_hosts", "missing"):
                result = self.verify((status, {}), kind)
                self.assertEqual(result["unknown"], ["//stage.example.com/"], (status, kind))
        loop = {"https://stage.example.com/": (302, {"Location": "/a"}),
                "https://stage.example.com/a": (302, {"Location": "/"})}
        with mock.patch.object(doctor, "_probe", probe(loop)):
            result = doctor.verify_live({"other_hosts": ["//stage.example.com/"],
                                         "missing": [], "files": []})
        self.assertEqual(result["unknown"], ["//stage.example.com/"])
        self.assertEqual(self.verify((302, {}))["unknown"], ["//stage.example.com/"])


class Site(unittest.TestCase):
    def pages(self, names, closed=()):
        import os, shutil, tempfile
        from indexgap import core
        root = tempfile.mkdtemp(prefix="indexgap-doc-")
        self.addCleanup(shutil.rmtree, root, True)
        for name in names:
            os.makedirs(os.path.join(root, name))
            links = "".join(f'<a href="/{o}/">{o}</a>' for o in names if o != name)
            robots = '<meta name="robots" content="noindex">' if name in closed else ""
            with open(os.path.join(root, name, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f"<html><head><title>Страница {name} сайта</title>{robots}</head>"
                         f"<body><main><h1>{name}</h1><p>{'слово ' * 300}</p>{links}</main></body></html>")
        return core.load_pages(root, HOME)[0]


HOME = "https://example.com"


class TestSitemapSaysWhatIsWrong(Site):
    def test_sitemap_on_another_host_is_named_not_counted_as_lost_pages(self):
        """Sitemap собран с адресом dev-сервера: выпали не страницы, а хост."""
        result = doctor.funnel(self.pages(["a", "b", "c"]), sitemap_urls=[
            "http://localhost:3000/a/", "http://localhost:3000/b/", "http://localhost:3000/c/"])
        self.assertTrue(any("localhost:3000" in n for n in result["foreign"]), result["foreign"])

    def test_noindex_and_stale_sitemap_entries_are_listed(self):
        result = doctor.funnel(self.pages(["a", "b", "closed"], closed=["closed"]), sitemap_urls=[
            f"{HOME}/a/", f"{HOME}/closed/", f"{HOME}/gone-1/"])
        self.assertEqual(result["closed_in_sitemap"], [f"{HOME}/closed/"])
        self.assertEqual(result["stale_in_sitemap"], ["//example.com/gone-1"])
        self.assertEqual(result["missing_from_sitemap"], [f"{HOME}/b/"])


class TestParameterVariants(Site):
    def test_query_variant_of_an_existing_page_is_not_missing(self):
        """`/a/?utm_source=newsletter` в выгрузке — это страница `/a/`, а не
        «удалённая или переименованная», которой нужен 301."""
        result = doctor.funnel(self.pages(["a", "b"]), by_engine={"google": [
            f"{HOME}/a/?utm_source=newsletter", f"{HOME}/b/?page=2"]})
        self.assertEqual(result["indexed_unknown"], [])
        self.assertEqual(result["not_indexed"], [])


class TestCitationCounts(Site):
    def test_citations_sum_across_url_variants_and_ignore_other_engines(self):
        pages = self.pages(["a", "b", "c"])
        cited = {"copilot": {f"{HOME}/a/": 10, f"{HOME}/a": 5,
                             f"http://www.example.com/a/index.html": 7,
                             f"{HOME}/b/": 2, f"{HOME}/c/": 1}}
        alone = doctor.funnel(pages, cited=cited)
        self.assertEqual(dict(alone["cited_top"])[f"{HOME}/a/"], 22)
        step = lambda r: next(s["count"] for s in r["steps"] if s.get("engine") == "copilot")
        self.assertEqual(step(alone), 3)
        # Выгрузка показов Google, где есть только одна страница, не делает
        # процитированные страницы непроцитированными.
        with_google = doctor.funnel(pages, cited=cited, by_engine={"google": [f"{HOME}/a/"]},
                                    impressions=["google"])
        self.assertEqual(step(with_google), 3)


if __name__ == "__main__":
    unittest.main()
