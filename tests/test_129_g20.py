# -*- coding: utf-8 -*-
"""
1.29 (g20): indexgap.json и профили, команда init.

* Глубокий конфиг и конфиг страниц сильнее конфига над рабочим каталогом;
  `home` из конфига действует; путь к конфигу печатается целиком.
* ignore: шаблон `/` не снимает находки о сайте целиком, `robots.txt`
  снимается своим адресом; принятое уходит из сирот, пар и совета о группах.
* freshness: бесконечность и миллиард дней — ошибка со словами; раздел под
  чужим профилем назван.
* init: корень с главной — сам сайт; docs/ не перевешивает сборку; выгрузка
  Search Console — не датасет; .indexgap.json виден; флаги вписываются в
  существующий конфиг и проверяются; профиль читается из конфига; адрес
  сайта ищется дальше после пустого ответа; команда в кавычках; старый блок
  .gitignore чинится.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, cli, install, profiles, settings
from indexgap.core import SourceError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_json(path, data):
    write(path, json.dumps(data))


def run(argv, cwd=None):
    out = None
    for i, item in enumerate(argv):
        if item == "--out":
            out = argv[i + 1]
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with mock.patch.object(sys, "stdout", io.StringIO()) as printed, \
                mock.patch.object(sys, "stderr", io.StringIO()) as errors:
            code = cli.main(argv)
        data = None
        if out and code != 2:
            path = out.replace(".html", ".json")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
    finally:
        os.chdir(old)
    return code, data, printed.getvalue() + errors.getvalue()


HOME = ('<!doctype html><html lang="en"><head><title>Home</title>'
        '<link rel="canonical" href="https://shop.example/"></head>'
        '<body><h1>Home</h1><p>Welcome.</p></body></html>')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-129g20-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def demo(self, *parts):
        path = os.path.join(self.tmp, *parts)
        shutil.copytree(DEMO, path)
        return path


class ProjectConfig(Base):
    def test_deep_config_gives_site_and_dataset(self):
        project = os.path.join(self.tmp, "deep", "project")
        self.demo("deep", "project", "build", "app")
        shutil.copy(os.path.join(DEMO, "cities.csv"), os.path.join(project, "cities.csv"))
        write_json(os.path.join(project, "indexgap.json"),
                   {"site": SITE, "pages": "./build/app", "dataset": "./cities.csv"})
        os.makedirs(os.path.join(self.tmp, "o"))
        code, data, out = run(["check", os.path.join("deep", "project", "build", "app"),
                               "--out", os.path.join("o", "r.html")], cwd=self.tmp)
        self.assertNotEqual(code, 2, out)
        self.assertIn("Сверено с датасетом", out)
        self.assertIn(os.path.join("deep", "project", "indexgap.json"), out)
        self.assertTrue(any(i["code"] == "unsupported-number" for i in data["issues"]))

    def test_pages_config_beats_parent_of_cwd(self):
        site = self.demo("ws", "site")
        write_json(os.path.join(site, "indexgap.json"),
                   {"profile": "catalog", "dataset": "cities.csv", "site": SITE})
        write_json(os.path.join(self.tmp, "ws", "tools", "indexgap.json"),
                   {"profile": "ugc", "site": "https://shop.example"})
        scripts = os.path.join(self.tmp, "ws", "tools", "scripts")
        os.makedirs(scripts)
        code, data, out = run(["check", os.path.join("..", "..", "site"),
                               "--out", os.path.join(self.tmp, "r.html")], cwd=scripts)
        self.assertIn("(catalog)", out)
        self.assertEqual(data["site"], SITE + "/")

    def test_home_from_config(self):
        site = self.demo("hm")
        os.makedirs(os.path.join(site, "en"))
        shutil.move(os.path.join(site, "index.html"), os.path.join(site, "en", "index.html"))
        write_json(os.path.join(site, "indexgap.json"),
                   {"site": SITE, "home": SITE + "/en/"})
        code, data, out = run(["check", "hm", "--out", os.path.join(self.tmp, "r.html")],
                              cwd=self.tmp)
        self.assertNotIn("главной нет среди разобранных", out)
        self.assertNotIn(SITE + "/en/", data["orphans"])


class Ignore(unittest.TestCase):
    def test_home_rule_keeps_site_level_findings(self):
        issues = [("critical", "", "hreflang-no-return", "x"),
                  ("warning", SITE + "/", "no-viewport", "y")]
        kept, accepted = checks.apply_ignore(issues, {"*": ["/"]}, SITE)
        self.assertEqual([i[2] for i in kept], ["hreflang-no-return"])
        self.assertEqual([i[2] for i in accepted], ["no-viewport"])
        kept, accepted = checks.apply_ignore(issues, {"hreflang-no-return": True}, SITE)
        self.assertEqual(len(accepted), 1)

    def test_robots_finding_by_its_address(self):
        issue = ("critical", "robots.txt", "ai-crawler-blocked", "x")
        for rule in ("robots.txt", "/robots.txt", SITE + "/robots.txt"):
            kept, accepted = checks.apply_ignore([issue], {"ai-crawler-blocked": [rule]}, SITE)
            self.assertEqual(accepted, [issue], rule)

    def test_accepted_leave_orphans_pairs_and_group_note(self):
        tmp = tempfile.mkdtemp(prefix="indexgap-129g20-")
        self.addCleanup(shutil.rmtree, tmp, True)
        site = os.path.join(tmp, "s")
        shutil.copytree(DEMO, site)
        write_json(os.path.join(site, "indexgap.json"),
                   {"ignore": {"near-duplicate": True, "orphan": True}})
        code, data, out = run(["check", site, "--site", SITE, "--dataset",
                               os.path.join(site, "cities.csv"),
                               "--out", os.path.join(tmp, "r.html")])
        self.assertTrue(any(i["code"] == "orphan" for i in data["accepted"]))
        self.assertEqual(data["orphans"], [])
        accepted = {i["url"] for i in data["accepted"] if i["code"] == "near-duplicate"}
        for pair in data["duplicates"]:
            self.assertFalse({pair["a"], pair["b"]} <= accepted)
        self.assertNotIn("Чинится по группам", out)


class Freshness(unittest.TestCase):
    def test_huge_grace_days_is_worded_error(self):
        for value in (1000000000, 1e20, float("inf"), float("nan")):
            with self.assertRaises(SourceError):
                settings.check_section("freshness", {"grace_days": value})
        self.assertEqual(settings.check_section("freshness", {"grace_days": 3}), [])

    def test_freshness_under_other_profile_is_named(self):
        config = dict(settings.PROJECT_DEFAULTS)
        config.update({"freshness": {"grace_days": 3}, "_user_keys": ["freshness"]})
        notes = profiles.apply(config, "catalog")["_config_notes"]
        self.assertTrue(any("freshness" in n for n in notes))
        notes = profiles.apply(config, "events")["_config_notes"]
        self.assertFalse(any("freshness" in n for n in notes))


class InitDetect(Base):
    def test_root_with_home_is_the_site(self):
        site = self.demo("site")
        self.assertEqual(install.detect_content_dir(site), ".")
        root = os.path.join(self.tmp, "blogsite")
        write(os.path.join(root, "index.html"), HOME)
        for name in ("a", "b"):
            write(os.path.join(root, "blog", name, "index.html"),
                  HOME.replace("Home", name))
        self.assertEqual(install.detect_content_dir(root), ".")
        self.assertEqual(install.detect_site(root, "."), "https://shop.example/")

    def test_template_home_does_not_win(self):
        root = os.path.join(self.tmp, "jk")
        write(os.path.join(root, "index.html"), "---\nlayout: home\n---\n<p>x</p>\n")
        for name in ("a", "b", "c"):
            write(os.path.join(root, "content", name + ".md"), "# " + name + "\n")
        self.assertEqual(install.detect_content_dir(root), os.path.join(".", "content"))

    def test_docs_notes_do_not_beat_build(self):
        root = os.path.join(self.tmp, "app")
        write(os.path.join(root, "out", "index.html"), HOME)
        for n in range(4):
            write(os.path.join(root, "out", f"p{n}", "index.html"), HOME)
        for n in range(25):
            write(os.path.join(root, "docs", f"adr-{n}.md"), "# note\n")
        self.assertEqual(install.detect_content_dir(root), os.path.join(".", "out"))

    def test_search_console_export_is_not_a_dataset(self):
        root = os.path.join(self.tmp, "ds")
        write(os.path.join(root, "gsc.csv"), "query,clicks,impressions,ctr,position\na,1,2,3,4\n")
        write(os.path.join(root, "data", "cities.csv"), "keyword,price\nberlin,1\n")
        self.assertEqual(install.detect_dataset(root), os.path.join(".", "data", "cities.csv"))

    def test_site_search_goes_on_after_empty_answer(self):
        root = os.path.join(self.tmp, "cn")
        write(os.path.join(root, "robots.txt"), "User-agent: *\nSitemap: /sitemap.xml\n")
        write(os.path.join(root, "CNAME"), "shop.example\n")
        self.assertEqual(install.detect_site(root), "https://shop.example/")
        root = os.path.join(self.tmp, "lh")
        write(os.path.join(root, "public", "sitemap.xml"),
              "<urlset><url><loc>http://localhost:3000/</loc></url></urlset>")
        write(os.path.join(root, "CNAME"), "shop.example\n")
        self.assertEqual(install.detect_site(root), "https://shop.example/")

    def test_package_json_homepage_and_host_blocklist(self):
        root = os.path.join(self.tmp, "pk")
        write_json(os.path.join(root, "package.json"),
                   {"author": "A (https://author-page.example.org)",
                    "homepage": "https://shop.example/"})
        self.assertEqual(install.detect_site(root), "https://shop.example/")
        root = os.path.join(self.tmp, "pk2")
        write_json(os.path.join(root, "package.json"), {"homepage": "https://github.company.example/"})
        self.assertEqual(install.detect_site(root), "https://github.company.example/")
        root = os.path.join(self.tmp, "pk3")
        write_json(os.path.join(root, "package.json"), {"homepage": "https://github.com/x/y"})
        self.assertEqual(install.detect_site(root), "")


class InitWrite(Base):
    def project(self, name="p"):
        root = os.path.join(self.tmp, name)
        for n in range(3):
            write(os.path.join(root, "content", f"p{n}.md"), "# page\n\nshort\n")
        return root

    def init(self, root, *flags, cwd=None):
        return run(["init", root] + list(flags), cwd=cwd)

    def config(self, root, name="indexgap.json"):
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            return json.load(fh)

    def test_dot_config_is_read_not_shadowed(self):
        root = self.project()
        write_json(os.path.join(root, ".indexgap.json"),
                   {"profile": "events", "site": "https://shop.example/", "pages": "./content"})
        code, _, out = self.init(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(root, "indexgap.json")))
        self.assertIn("events", out)

    def test_flags_are_written_into_existing_config(self):
        root = self.project()
        self.init(root)
        cfg = self.config(root)
        cfg["checks"] = {"thin_words": 5}
        write_json(os.path.join(root, "indexgap.json"), cfg)
        code, _, out = self.init(root, "--site", "https://shop.example")
        cfg = self.config(root)
        self.assertEqual(cfg["site"], "https://shop.example")
        self.assertEqual(cfg["checks"], {"thin_words": 5})

    def test_profile_is_read_from_config(self):
        root = self.project()
        self.init(root, "--site", "https://shop.example", "--profile", "events")
        code, _, out = self.init(root, "--agents")
        with open(os.path.join(root, "AGENTS.md"), encoding="utf-8") as fh:
            self.assertIn("`events`", fh.read())

    def test_bad_flags_are_refused(self):
        root = self.project()
        for flags in (["--profile", "blog"], ["--site", "shop.example"],
                      ["--content", "./contnet"], ["--dataset", "./nokeys.csv"]):
            code, _, out = self.init(root, "--site", "https://shop.example", *flags)
            self.assertEqual(code, 2, (flags, out))
            self.assertFalse(os.path.exists(os.path.join(root, "indexgap.json")))

    def test_content_relative_to_cwd(self):
        root = self.project()
        code, _, out = self.init("p", "--content", os.path.join("p", "content"),
                                 "--site", "https://shop.example", cwd=self.tmp)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.config(root)["pages"], os.path.join(".", "content"))

    def test_command_with_space_is_quoted(self):
        root = os.path.join(self.tmp, "q")
        for n in range(3):
            write(os.path.join(root, "my pages", f"p{n}.md"), "# page\n")
        code, _, out = self.init(root, "--content", "./my pages",
                                 "--site", "https://shop.example", "--agents")
        self.assertIn("indexgap check './my pages'", out)
        with open(os.path.join(root, "AGENTS.md"), encoding="utf-8") as fh:
            self.assertIn("indexgap check './my pages'", fh.read())

    def test_old_gitignore_block_is_refreshed(self):
        root = self.project()
        write(os.path.join(root, ".gitignore"),
              "node_modules/\n\n# indexgap\n.indexgap-manifest.json\nindexgap-check.html\n"
              "\n# user\n.indexgap-manifest.json\n")
        self.assertTrue(install.update_gitignore(root))
        with open(os.path.join(root, ".gitignore"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        block = lines[lines.index("# indexgap") + 1:lines.index("# user")]
        self.assertNotIn(".indexgap-manifest.json", block)
        self.assertIn("indexgap-briefs/", block)
        self.assertIn(".indexgap-manifest.json", lines)  # чужая строка не тронута
        self.assertFalse(install.update_gitignore(root))


if __name__ == "__main__":
    unittest.main()
