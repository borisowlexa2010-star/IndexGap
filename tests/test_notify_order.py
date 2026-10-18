# -*- coding: utf-8 -*-
"""
`notify`: пробный прогон показывает, что уйдёт, ничего не трогая.

Ревьюер-агент: пробный прогон печатал только счётчики, хотя навык обещал
показать адреса; ходил в сеть за реестром IndexNow (в тестовой обвязке без
сети — падение); и отправка шла при открытых критичных находках `check`.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, engines

SITE = "https://example.com"
PAGE = ("<!doctype html><html lang=\"ru\"><head><title>{t}</title></head><body><main>"
        "<h1>{t}</h1><p>Текст страницы {t}.</p></main></body></html>")


class DryRun(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-notify-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.site = os.path.join(self.dir, "public")
        for name in ("index", "a", "b"):
            path = os.path.join(self.site, "" if name == "index" else name, "index.html")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(PAGE.format(t=name))
        self.cache = tempfile.mkdtemp(prefix="indexgap-cache-")
        self.addCleanup(shutil.rmtree, self.cache, True)

    def run_notify(self, *extra):
        out = io.StringIO()
        with mock.patch.object(engines, "cache_dir", return_value=self.cache), \
                mock.patch("urllib.request.urlopen",
                           side_effect=AssertionError("пробный прогон вышел в сеть")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["notify", self.site, "--site", SITE, "--key", "k" * 32,
                             "--manifest", os.path.join(self.dir, "m.json"), *extra])
        return code, out.getvalue()

    def test_the_dry_run_does_not_touch_the_network(self):
        code, _ = self.run_notify()
        self.assertEqual(code, 0)

    def test_the_dry_run_lists_the_addresses(self):
        _, out = self.run_notify()
        self.assertIn(SITE + "/a/", out)
        self.assertIn(SITE + "/b/", out)

    def test_open_critical_findings_are_named_before_sending(self):
        report = os.path.join(self.dir, "indexgap-check.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump({"_indexgap": "x", "issues": [
                {"level": "critical", "url": SITE + "/a/", "code": "no-title", "message": "нет"}]},
                fh)
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)
        _, out = self.run_notify()
        self.assertIn("критичн", out)


if __name__ == "__main__":
    unittest.main()
