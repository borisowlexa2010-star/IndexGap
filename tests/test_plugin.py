# -*- coding: utf-8 -*-
"""
Обёртка плагина не должна расходиться с пакетом.

Каталог плагинов читает `.claude-plugin/plugin.json` и `skills/` из корня
репозитория, а живут скиллы в `indexgap/skills/`. Копия, которую забыли
пересобрать, — это описание, не совпадающее с поведением, то самое, за что
заявку в официальном каталоге и заворачивают.

Поэтому здесь не проверяется «файл существует»: собирается то же самое, что
собрал бы `tools/sync_plugin.py`, и сравнивается с тем, что лежит в репозитории.
"""

import json
import os
import sys
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import sync_plugin                                     # noqa: E402
from indexgap import __version__                       # noqa: E402


class TestPlugin(unittest.TestCase):

    def setUp(self):
        self.expected = sync_plugin.build(write=False)

    def test_every_generated_file_is_committed_and_current(self):
        for path, text in self.expected.items():
            with self.subTest(path=path):
                real = os.path.join(ROOT, path)
                self.assertTrue(
                    os.path.exists(real),
                    f"{path} отсутствует — запусти python3 tools/sync_plugin.py")
                with open(real, encoding="utf-8") as fh:
                    self.assertEqual(
                        fh.read(), text,
                        f"{path} разошёлся с источником — "
                        f"запусти python3 tools/sync_plugin.py")

    def test_no_stray_skills_left_behind(self):
        """Удалённый скилл должен исчезать из плагина, а не оставаться копией."""
        expected = {p for p in self.expected if p.startswith("skills/")}
        actual = set()
        root = os.path.join(ROOT, "skills")
        for dirpath, _, names in os.walk(root):
            for name in names:
                full = os.path.join(dirpath, name)
                actual.add(os.path.relpath(full, ROOT).replace(os.sep, "/"))
        self.assertEqual(actual, expected)

    def test_manifest_version_follows_the_package(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["version"], __version__)

    def test_every_skill_is_english(self):
        """Каталог международный: основным идёт перевод, а не русский оригинал."""
        for path, text in self.expected.items():
            if not path.startswith("skills/"):
                continue
            with self.subTest(path=path):
                head = text.split("---")[1] if "---" in text else text
                cyrillic = sum(1 for c in head if "Ѐ" <= c <= "ӿ")
                self.assertEqual(
                    cyrillic, 0,
                    f"{path}: во фронтматтере кириллица — "
                    f"похоже, взят SKILL.md вместо SKILL.en.md")

    def test_manifest_declares_what_the_package_actually_does(self):
        """Описание не должно обещать того, чего в пакете нет."""
        data = sync_plugin.manifest()
        self.assertNotIn("MCP", data["description"])
        self.assertIn("indexgap", data["description"])
        self.assertEqual(data["license"], "MIT")


if __name__ == "__main__":
    unittest.main()
