# -*- coding: utf-8 -*-
"""
`doctor --live`: что из «поисковик знает, а на сайте нет» ещё требует действий.

Выгрузка показывает прошлое. На eventiq.io из пяти «пропавших» страниц четыре
уже отдавали 301 на правильные адреса, а служебный хост был закрыт noindex. На
rumors.app из семи чужих хостов действия требовал один — GitLab. Совет
«поставь 301» там, где 301 стоит, — шум, и в восьми случаях из десяти.

Проверка ходит в сеть, поэтому только по явному флагу.
"""

import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import doctor


def probe(table):
    """Подменяет сетевой запрос ответами из таблицы {адрес: (код, заголовки)}."""
    def fake(url, timeout=10):
        return table.get(url, (None, {}))
    return fake


class TestLiveVerify(unittest.TestCase):
    FOREIGN = {
        "other_hosts": ["//stage1.example.com/sign-in", "//gitlab.example.com/"],
        "missing": ["//example.com/moved", "//example.com/gone", "//example.com/alive"],
        "files": [],
    }
    TABLE = {
        "https://stage1.example.com/sign-in": (200, {"X-Robots-Tag": "noindex, nofollow"}),
        "https://gitlab.example.com/": (200, {}),
        "https://example.com/moved": (301, {"Location": "https://example.com/new"}),
        "https://example.com/gone": (410, {}),
        "https://example.com/alive": (200, {}),
    }

    def verify(self, table=None):
        with mock.patch.object(doctor, "_probe", probe(self.TABLE if table is None else table)):
            return doctor.verify_live(self.FOREIGN)

    def test_a_closed_host_is_done(self):
        result = self.verify()
        self.assertIn("//stage1.example.com/sign-in", result["done"])

    def test_an_open_host_needs_action(self):
        todo = {i["key"]: i for i in self.verify()["todo"]}
        self.assertIn("//gitlab.example.com/", todo)

    def test_a_redirected_page_is_done_and_says_where(self):
        result = self.verify()
        self.assertIn("//example.com/moved", result["done"])
        self.assertEqual(result["details"]["//example.com/moved"]["location"],
                         "https://example.com/new")

    def test_a_gone_page_is_done(self):
        self.assertIn("//example.com/gone", self.verify()["done"])

    def test_a_live_page_missing_from_the_files_means_a_stale_build(self):
        todo = {i["key"]: i for i in self.verify()["todo"]}
        self.assertIn("//example.com/alive", todo)
        self.assertEqual(todo["//example.com/alive"]["status"], 200)

    def test_an_unreachable_address_is_not_called_done(self):
        result = self.verify({})
        self.assertEqual(result["done"], [])
        self.assertEqual(len(result["unknown"]), 5)

    def test_a_host_behind_a_login_is_done(self):
        table = dict(self.TABLE)
        table["https://gitlab.example.com/"] = (401, {})
        self.assertIn("//gitlab.example.com/", self.verify(table)["done"])


class TestHostRedirects(unittest.TestCase):
    """
    Корень GitLab отвечает 302 на /users/sign_in, а та — 200 без noindex. Первая
    версия засчитала хост закрытым по одному редиректу, и на rumors.app сказала
    «8 из 8 в порядке» ровно про единственную настоящую беду.
    """

    def verify(self, table):
        foreign = {"other_hosts": ["//gitlab.example.com/"], "missing": [], "files": []}
        with mock.patch.object(doctor, "_probe", probe(table)):
            return doctor.verify_live(foreign)

    def test_a_redirect_within_the_host_is_followed_to_the_real_answer(self):
        result = self.verify({
            "https://gitlab.example.com/": (302, {"Location": "https://gitlab.example.com/users/sign_in"}),
            "https://gitlab.example.com/users/sign_in": (200, {}),
        })
        self.assertEqual([i["key"] for i in result["todo"]], ["//gitlab.example.com/"])

    def test_a_relative_redirect_is_followed_too(self):
        result = self.verify({
            "https://gitlab.example.com/": (302, {"Location": "/users/sign_in"}),
            "https://gitlab.example.com/users/sign_in": (200, {"X-Robots-Tag": "noindex"}),
        })
        self.assertEqual(result["done"], ["//gitlab.example.com/"])

    def test_a_host_redirected_elsewhere_is_retired(self):
        result = self.verify({
            "https://gitlab.example.com/": (301, {"Location": "https://example.com/"}),
        })
        self.assertEqual(result["done"], ["//gitlab.example.com/"])


class TestProbe(unittest.TestCase):
    def test_it_does_not_follow_redirects_and_introduces_itself(self):
        """Иначе 301 превращался бы в 200 конечной страницы и выглядел бы живым."""
        import urllib.error
        seen = {}

        class Opener:
            def open(self, request, timeout=None):
                seen["agent"] = request.get_header("User-agent")
                raise urllib.error.HTTPError(request.full_url, 301, "Moved",
                                             {"Location": "https://example.com/new"}, None)

        with mock.patch("urllib.request.build_opener", lambda *a: Opener()):
            code, headers = doctor._probe("https://example.com/old")
        self.assertEqual(code, 301)
        self.assertEqual(headers.get("Location"), "https://example.com/new")
        self.assertTrue(seen["agent"].startswith("indexgap/"))


if __name__ == "__main__":
    unittest.main()
