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


if __name__ == "__main__":
    unittest.main()
