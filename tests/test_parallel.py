# -*- coding: utf-8 -*-
"""
Параллельный разбор даёт то же, что однопроцессный — на любой системе.

Он включается с 2 000 страниц, и до этого теста ни один тест его не
проходил: Windows и macOS запускают процессы через spawn, и ошибка там
видна только на настоящем большом сайте.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import core

SITE = "https://example.com"


class Parallel(unittest.TestCase):
    def test_parallel_and_sequential_parse_alike(self):
        root = tempfile.mkdtemp(prefix="indexgap-par-")
        self.addCleanup(shutil.rmtree, root, True)
        for n in range(40):
            path = os.path.join(root, f"p{n}", "index.html")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"<!doctype html><html lang=\"ru\"><head><title>Страница {n}</title>"
                         f"</head><body><main><h1>Страница {n}</h1><p>{'текст ' * (20 + n)}"
                         f"</p><a href=\"/p{(n + 1) % 40}/\">дальше</a></main></body></html>")

        def snapshot(pages):
            return [(p.url, p.title, p.text, tuple(p.links), p.paragraphs, p.blocks)
                    for p in pages]

        one = snapshot(core.load_pages(root, SITE, jobs=1)[0])
        with mock.patch.object(core, "PARALLEL_FROM", 0):
            many = snapshot(core.load_pages(root, SITE, jobs=2)[0])
        self.assertEqual(len(one), 40)
        self.assertEqual(one, many)


if __name__ == "__main__":
    unittest.main()
