# -*- coding: utf-8 -*-
"""
Установка в проект.

Главное свойство, которое здесь проверяется: копируется только знание
об инструменте, а всё проектное определяется из самого проекта. Ключ IndexNow
между проектами не переносится ни при каких условиях — он привязан к домену,
и чужой ключ гарантированно даёт 403.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexgap import cli, install
from indexgap.core import SourceError


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-init-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path) or self.dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def pages(self, folder="content", count=6, dated=False, short=False, html=False):
        ext = "html" if html else "md"
        for i in range(count):
            if html:
                body = ("<html lang=\"ru\"><head><title>Страница %d</title></head>"
                        "<body><main><p>%s</p></main></body></html>"
                        % (i, "текст страницы " * (3 if short else 60)))
            else:
                head = f"---\ntitle: Страница {i}\n"
                if dated:
                    head += "date: 2026-03-01\n"
                head += "---\n\n"
                body = head + "# Страница\n\n" + "текст страницы " * (3 if short else 60)
            self.write(f"{folder}/p{i}/index.{ext}", body)
        return folder


# ── что определяется из проекта ───────────────────────────────────────────────

class TestDetection(Fixture):
    def test_content_dir_is_found(self):
        self.pages("content")
        self.assertEqual(install.detect_content_dir(self.dir),
                         os.path.join(".", "content"))

    def test_unusual_content_dir_is_found_by_page_count(self):
        self.pages("veb-stranicy", count=8)
        self.assertIn("veb-stranicy", install.detect_content_dir(self.dir))

    def test_site_from_sitemap(self):
        self.write("public/sitemap.xml",
                   '<?xml version="1.0"?><urlset><url>'
                   '<loc>https://moysite.example/a/</loc></url></urlset>')
        self.assertEqual(install.detect_site(self.dir), "https://moysite.example/")

    def test_site_from_robots(self):
        self.write("public/robots.txt",
                   "User-agent: *\nSitemap: https://izrobots.example/sitemap.xml\n")
        self.assertEqual(install.detect_site(self.dir), "https://izrobots.example/")

    def test_site_from_package_json(self):
        self.write("package.json", '{"name":"x","homepage":"https://izpackage.example"}')
        self.assertEqual(install.detect_site(self.dir), "https://izpackage.example/")

    def test_site_from_cname(self):
        self.write("CNAME", "izcname.example\n")
        self.assertEqual(install.detect_site(self.dir), "https://izcname.example/")

    def test_schema_org_is_not_mistaken_for_the_site(self):
        self.write("package.json", '{"x":"https://schema.org/Thing"}')
        self.assertEqual(install.detect_site(self.dir), "")

    def test_dataset_is_found_by_the_keyword_column(self):
        self.write("prosto-tablica.csv", "a,b\n1,2\n")
        self.write("semantika.csv", "keyword,city\nремонт,Москва\n")
        self.assertIn("semantika.csv", install.detect_dataset(self.dir))

    def test_profile_events_from_dates(self):
        self.pages("content", count=6, dated=True)
        profile, why = install.detect_profile(self.dir, "content", "")
        self.assertEqual(profile, "events")
        self.assertIn("дата", why)

    def test_profile_ugc_without_dataset_and_short_pages(self):
        self.pages("content", count=8, short=True)
        profile, _ = install.detect_profile(self.dir, "content", "")
        self.assertEqual(profile, "ugc")

    def test_profile_product_for_a_few_html_pages(self):
        self.pages("site", count=5, html=True)
        profile, _ = install.detect_profile(self.dir, "site", "")
        self.assertEqual(profile, "product")

    def test_profile_catalog_when_a_dataset_is_there(self):
        self.pages("content", count=8)
        profile, _ = install.detect_profile(self.dir, "content", "./keywords.csv")
        self.assertEqual(profile, "catalog")

    def test_every_guess_is_explained(self):
        self.pages("content")
        _, why = install.detect_profile(self.dir, "content", "")
        self.assertTrue(why.strip())


# ── что устанавливается ───────────────────────────────────────────────────────

class TestInstall(Fixture):
    def test_skills_land_where_the_agent_looks(self):
        self.pages()
        result = install.run(self.dir)
        for rel in result["skills"]:
            self.assertTrue(rel.startswith(os.path.join(".claude", "skills")), rel)
            self.assertTrue(os.path.isfile(os.path.join(self.dir, rel)))
        self.assertGreaterEqual(len(result["skills"]), 4)

    def test_installed_skill_keeps_its_frontmatter(self):
        self.pages()
        result = install.run(self.dir)
        text = open(os.path.join(self.dir, result["skills"][0]), encoding="utf-8").read()
        self.assertTrue(text.startswith("---"))
        self.assertIn("name:", text)
        self.assertIn("description:", text)

    def test_skill_directory_name_matches_frontmatter_name(self):
        self.pages()
        result = install.run(self.dir)
        for rel in result["skills"]:
            folder = os.path.basename(os.path.dirname(rel))
            text = open(os.path.join(self.dir, rel), encoding="utf-8").read()
            declared = [l.split(":", 1)[1].strip()
                        for l in text.splitlines()[:8] if l.startswith("name:")]
            self.assertEqual(declared[0], folder)

    def test_config_records_what_was_detected(self):
        self.pages()
        self.write("package.json", '{"homepage":"https://p.example"}')
        self.write("keywords.csv", "keyword\nремонт\n")
        install.run(self.dir)
        config = json.load(open(os.path.join(self.dir, "indexgap.json"), encoding="utf-8"))
        self.assertEqual(config["site"], "https://p.example/")
        self.assertIn("content", config["pages"])
        self.assertIn("keywords.csv", config["dataset"])

    def test_path_key_does_not_collide_with_the_settings_section(self):
        """`content` — раздел настроек, путь пишется в `pages`. Столкновение роняло check."""
        self.pages()
        install.run(self.dir)
        config = json.load(open(os.path.join(self.dir, "indexgap.json"), encoding="utf-8"))
        self.assertIsInstance(config["content"], dict)
        self.assertIsInstance(config["pages"], str)

    def test_existing_config_is_not_clobbered(self):
        self.pages()
        self.write("indexgap.json", '{"profile": "ugc", "checks": {"thin_words": 42}}')
        result = install.run(self.dir)
        self.assertFalse(result["config_written"])
        config = json.load(open(os.path.join(self.dir, "indexgap.json"), encoding="utf-8"))
        self.assertEqual(config["checks"]["thin_words"], 42)

    def test_force_overwrites_the_config(self):
        self.pages()
        self.write("indexgap.json", '{"profile": "ugc"}')
        result = install.run(self.dir, force=True)
        self.assertTrue(result["config_written"])

    def test_gitignore_is_extended_once(self):
        self.pages()
        install.run(self.dir)
        first = open(os.path.join(self.dir, ".gitignore"), encoding="utf-8").read()
        install.run(self.dir)
        second = open(os.path.join(self.dir, ".gitignore"), encoding="utf-8").read()
        self.assertEqual(first, second)
        self.assertIn(".indexgap-manifest.json", first)

    def test_agents_md_is_updated_not_duplicated(self):
        self.pages()
        self.write("AGENTS.md", "# Проект\n\nСайт на Astro.\n")
        install.run(self.dir)
        install.run(self.dir)
        text = open(os.path.join(self.dir, "AGENTS.md"), encoding="utf-8").read()
        self.assertEqual(text.count(install.AGENTS_START), 1)
        self.assertIn("Сайт на Astro.", text)

    def test_agents_md_is_not_created_uninvited(self):
        self.pages()
        install.run(self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "AGENTS.md")))

    def test_repeated_install_refreshes_skills(self):
        self.pages()
        result = install.run(self.dir)
        target = os.path.join(self.dir, result["skills"][0])
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("испорчено")
        install.run(self.dir)
        self.assertIn("name:", open(target, encoding="utf-8").read())


# ── ключ IndexNow ─────────────────────────────────────────────────────────────

class TestKeyIsPerProject(Fixture):
    def test_install_never_writes_a_key_into_the_config(self):
        self.pages()
        install.run(self.dir)
        text = open(os.path.join(self.dir, "indexgap.json"), encoding="utf-8").read()
        self.assertNotIn("key", json.loads(text))

    def test_generated_keys_differ_between_projects(self):
        keys = {install.new_indexnow_key() for _ in range(20)}
        self.assertEqual(len(keys), 20)

    def test_generated_key_is_accepted_by_the_protocol_check(self):
        from indexgap import publish
        for _ in range(5):
            key = install.new_indexnow_key()
            self.assertEqual(publish.check_key(key), key)

    def test_no_key_file_is_copied_into_the_project(self):
        self.pages()
        install.run(self.dir)
        stray = [f for f in os.listdir(self.dir) if f.endswith(".txt")]
        self.assertEqual(stray, [])


# ── ежедневная команда ────────────────────────────────────────────────────────

class TestProjectDefaults(Fixture):
    def _run_cli(self, argv, cwd):
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(cwd)
        try:
            with mock.patch.object(sys, "stdout", out):
                code = cli.main(argv)
        finally:
            os.chdir(old)
        return code, out.getvalue()

    def test_check_without_arguments_works_after_init(self):
        self.pages()
        self.write("package.json", '{"homepage":"https://p.example"}')
        install.run(self.dir)
        code, out = self._run_cli(["check", "--no-aeo",
                                   "--out", os.path.join(self.dir, "r.html")], self.dir)
        self.assertEqual(code, 0)
        self.assertIn("Разобрано страниц", out)

    def test_explicit_argument_beats_the_config(self):
        self.pages("content")
        self.pages("drugoy")
        install.run(self.dir)
        code, out = self._run_cli(
            ["check", os.path.join(self.dir, "drugoy"), "--site", "https://x.example",
             "--no-aeo", "--out", os.path.join(self.dir, "r.html")], self.dir)
        self.assertEqual(code, 0)

    def test_missing_project_data_is_explained_not_crashed(self):
        code, out = self._run_cli(["check"], self.dir)
        self.assertEqual(code, 2)

    def test_broken_project_file_is_explained(self):
        self.pages()
        self.write("indexgap.json", "{битый json")
        code, _ = self._run_cli(["check", "--out", os.path.join(self.dir, "r.html")],
                                self.dir)
        self.assertEqual(code, 2)

    def test_path_in_the_settings_section_is_explained_not_crashed(self):
        self.pages()
        self.write("indexgap.json",
                   '{"site":"https://x.example","pages":"./content","content":"./content"}')
        code, _ = self._run_cli(["check", "--out", os.path.join(self.dir, "r.html")],
                                self.dir)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
