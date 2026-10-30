# -*- coding: utf-8 -*-
"""
Скиллы проекта стареют вместе с пакетом.

`indexgap init` кладёт скиллы в `.claude/skills/` проекта, а `pipx upgrade`
обновляет только пакет: агент в проекте продолжал читать инструкции версии
1.14 — без `diff`, `fetch` и новых кодов. `check` теперь говорит об этом
и называет команду, которая обновит скиллы, не трогая `indexgap.json`.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cli, install

SITE = "https://example.com"


class StaleSkills(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-skills-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "site"))
        with open(os.path.join(self.root, "site", "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><html lang='ru'><head><title>Главная страница сайта"
                     "</title></head><body><h1>Главная</h1><p>текст</p></body></html>")
        install.install_skills(self.root)

    def test_fresh_skills_are_not_stale(self):
        self.assertEqual(install.stale_skills(self.root), [])

    def test_an_old_copy_is_named(self):
        path = os.path.join(self.root, ".claude", "skills", "indexgap-review", "SKILL.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("---\nname: indexgap-review\n---\nстарая версия\n")
        self.assertEqual(install.stale_skills(self.root), ["indexgap-review"])

    def test_the_english_copy_counts_as_current(self):
        source = install.skills_source()
        shutil.copyfile(os.path.join(source, "indexgap-plan", "SKILL.en.md"),
                        os.path.join(self.root, ".claude", "skills", "indexgap-plan", "SKILL.md"))
        self.assertEqual(install.stale_skills(self.root), [])

    def test_a_project_without_skills_says_nothing(self):
        shutil.rmtree(os.path.join(self.root, ".claude"))
        self.assertEqual(install.stale_skills(self.root), [])

    def test_check_says_how_to_update(self):
        path = os.path.join(self.root, ".claude", "skills", "indexgap-review", "SKILL.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("старая версия\n")
        out = io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["check", "site", "--site", SITE, "--out", "r.html"])
        self.assertIn("indexgap-review", out.getvalue())
        self.assertIn("indexgap init", out.getvalue())


if __name__ == "__main__":
    unittest.main()
