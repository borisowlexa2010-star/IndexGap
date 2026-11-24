# -*- coding: utf-8 -*-
"""
1.27: настройки проекта действуют целиком или названы.

* indexgap.json, записанный `init` для сборки Next.js (`.next/server/app`),
  применялся наполовину: адрес и профиль — да, пороги и ignore — нет.
* Два конфига (в текущем каталоге и рядом со страницами) смешивались.
* Пороги разделов `content`, `aeo`, `freshness` не проверялись: доля 70
  вместо 0.7 молча выключала находки, число строкой роняло прогон.
* `"vague_anchors": null` ронял прогон; свой near_duplicate под профилем
  падал на `similar`, которого никто не писал; правило ignore адресом целиком
  ни с чем не совпадало; опечатка в имени поля молчала.
* `--lang xx` при INDEXGAP_LANG=ru давал английскую ошибку.
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
from indexgap import checks, cli, freshness, i18n, portfolio, profiles, settings
from indexgap.core import SourceError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def run(argv, cwd=None):
    """cli.main в каталоге `cwd`; возвращает код, JSON отчёта и вывод."""
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
    finally:
        os.chdir(old)
    data = None
    if out and code != 2 and os.path.isfile(out.replace(".html", ".json")):
        with open(out.replace(".html", ".json"), encoding="utf-8") as fh:
            data = json.load(fh)
    return code, data, printed.getvalue() + errors.getvalue()


def kinds(data, code):
    return sum(1 for i in data["issues"] if i["code"] == code) if data else 0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="indexgap-127-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def site(self, *parts):
        path = os.path.join(self.tmp, *parts)
        shutil.copytree(DEMO, path)
        return path


class DeepConfig(Base):
    """Конфиг тремя уровнями выше страниц — как его пишет `init` для Next.js."""

    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp, "project")
        self.pages = self.site("project", ".next", "server", "app")
        shutil.move(os.path.join(self.pages, "cities.csv"),
                    os.path.join(self.project, "cities.csv"))
        write_json(os.path.join(self.project, "indexgap.json"), {
            "site": SITE, "pages": "./.next/server/app", "dataset": "./cities.csv",
            "checks": {"thin_words": 2000}, "ignore": {"near-duplicate": True}})

    def test_plain_check_applies_the_whole_file(self):
        out = os.path.join(self.tmp, "o1", "r.html")
        code, plain, text = run(["check", "--out", out], cwd=self.project)
        self.assertNotEqual(code, 2, text)
        out = os.path.join(self.tmp, "o2", "r.html")
        _, explicit, _ = run(["check", "--config", "indexgap.json", "--out", out],
                             cwd=self.project)
        self.assertEqual(kinds(plain, "thin"), kinds(explicit, "thin"))
        self.assertGreater(kinds(plain, "thin"), 1)
        self.assertEqual(kinds(plain, "near-duplicate"), 0)
        self.assertTrue(plain["accepted"])
        self.assertIn("indexgap.json", text)

    def test_find_config_reaches_a_config_that_owns_the_pages(self):
        self.assertEqual(settings.find_config(self.pages),
                         os.path.join(self.project, "indexgap.json"))

    def test_a_foreign_config_far_above_is_not_taken(self):
        write_json(os.path.join(self.project, "indexgap.json"),
                   {"site": SITE, "pages": "./content"})
        self.assertEqual(settings.find_config(self.pages), "")

    def test_portfolio_finds_the_dataset_of_such_a_project(self):
        result = portfolio.run_one({"name": "nx", "root": self.pages, "site": SITE},
                                   quiet=True)
        self.assertEqual(result["error"], "")
        self.assertGreater(result.get("matched_rows", 0), 0)
        self.assertGreater(result["accepted"], 0)


class OneConfigOnly(Base):
    """Конфиг текущего каталога и конфиг рядом со страницами не смешиваются."""

    def test_settings_come_from_the_same_file_as_the_profile(self):
        proj = os.path.join(self.tmp, "projA")
        os.makedirs(proj)
        write_json(os.path.join(proj, "indexgap.json"),
                   {"profile": "ugc", "site": "https://other.example"})
        other = self.site("siteB")
        write_json(os.path.join(other, "indexgap.json"),
                   {"profile": "catalog", "ignore": {"near-duplicate": True}})
        out = os.path.join(self.tmp, "o", "r.html")
        code, data, text = run(["check", other, "--site", SITE, "--out", out], cwd=proj)
        self.assertNotEqual(code, 2, text)
        self.assertIn("(ugc)", text)
        # ignore из siteB не подмешан к профилю из projA.
        self.assertEqual(data["accepted"], [])


class SectionValidation(Base):
    """content, aeo и freshness проверяются так же, как checks."""

    def check_with(self, config):
        folder = self.site("s")
        write_json(os.path.join(folder, "indexgap.json"), config)
        out = os.path.join(self.tmp, "o", "r.html")
        return run(["check", folder, "--site", SITE, "--dataset",
                    os.path.join(folder, "cities.csv"), "--out", out])

    def test_share_on_the_wrong_scale_is_an_error(self):
        code, _, text = self.check_with({"content": {"template_share": 70}})
        self.assertEqual(code, 2)
        self.assertIn("content.template_share", text)

    def test_a_number_as_a_string_is_a_worded_error(self):
        for config in ({"aeo": {"answer_min": "40"}},
                       {"content": {"template_share": "0.7"}},
                       {"profile": "events", "freshness": {"grace_days": "1"}}):
            shutil.rmtree(os.path.join(self.tmp, "s"), True)
            code, _, text = self.check_with(config)
            self.assertEqual(code, 2, config)
            self.assertIn("должна быть числом", text)
            self.assertNotIn("Traceback", text)

    def test_unknown_keys_get_a_note(self):
        code, data, _ = self.check_with({"content": {"template_shar": 0.5},
                                         "aeo": {"answer_mn": 10},
                                         "chekcs": {"thin_words": 10}})
        self.assertNotEqual(code, 2)
        notes = " ".join(data["notes"])
        self.assertIn("content.template_shar", notes)
        self.assertIn("template_share", notes)
        self.assertIn("aeo.answer_mn", notes)
        self.assertIn("«chekcs»", notes)
        self.assertIn("«checks»", notes)

    def test_known_keys_get_no_note(self):
        self.assertEqual(settings.check_section("content", {"template_share": 0.6}), [])
        self.assertEqual(settings.unknown_keys(
            {"_user_keys": ["profile", "site", "pages", "checks", "_comment"]}), [])

    def test_null_vague_anchors_means_the_default(self):
        code, _, text = self.check_with({"vague_anchors": None})
        self.assertNotEqual(code, 2, text)
        self.assertNotIn("Traceback", text)
        folder = os.path.join(self.tmp, "s")
        self.assertEqual(settings.load_config(folder)["vague_anchors"],
                         settings.PROJECT_DEFAULTS["vague_anchors"])


class Freshness(Base):
    def test_check_reads_freshness_from_the_config(self):
        folder = self.site("s")
        write_json(os.path.join(folder, "indexgap.json"),
                   {"profile": "events", "freshness": {"grace_days": 1}})
        seen = []
        real = freshness.check

        def spy(pages, cfg=None, today=None):
            seen.append(cfg)
            return real(pages, cfg, today)

        out = os.path.join(self.tmp, "o", "r.html")
        with mock.patch.object(freshness, "check", spy):
            run(["check", folder, "--site", SITE, "--out", out])
        self.assertEqual(seen, [{"grace_days": 1}])

    def test_a_bad_portfolio_value_fails_one_project_only(self):
        folder = self.site("s")
        result = portfolio.run_one({"name": "ev", "root": folder, "site": SITE,
                                    "profile": "events",
                                    "freshness": {"grace_days": "1"}}, quiet=True)
        self.assertIn("grace_days", result["error"])


class ProfileSimilar(unittest.TestCase):
    def test_own_near_duplicate_lowers_the_profile_similar(self):
        for name, nd in (("ugc", 0.75), ("product", 0.6)):
            project = profiles.apply({"checks": {"near_duplicate": nd}}, name)
            checks.validate_config(project["checks"])
            self.assertLessEqual(project["checks"]["similar"], nd)
            self.assertEqual(project["checks"]["near_duplicate"], nd)

    def test_explicit_similar_is_still_checked(self):
        project = profiles.apply({"checks": {"near_duplicate": 0.6, "similar": 0.7}}, "ugc")
        with self.assertRaises(SourceError):
            checks.validate_config(project["checks"])

    def test_profile_alone_is_unchanged(self):
        project = profiles.apply({}, "ugc")
        self.assertEqual(project["checks"]["similar"],
                         profiles.PROFILES["ugc"]["checks"]["similar"])


class IgnorePatterns(unittest.TestCase):
    ISSUES = [("critical", SITE + "/rent/cologne/", "noindex", "x"),
              ("critical", SITE + "/rent/leipzig/", "orphan", "x"),
              ("critical", SITE + "/rent/bonn/", "orphan", "x")]

    def test_full_address_and_missing_slash_match(self):
        kept, accepted = checks.apply_ignore(
            list(self.ISSUES), {"noindex": [SITE + "/rent/cologne/"],
                                "orphan": ["rent/leipzig/"]}, SITE)
        self.assertEqual([i[1] for i in accepted],
                         [SITE + "/rent/cologne/", SITE + "/rent/leipzig/"])
        self.assertEqual([i[1] for i in kept], [SITE + "/rent/bonn/"])

    def test_wildcards_keep_working(self):
        kept, accepted = checks.apply_ignore(list(self.ISSUES), {"orphan": ["*/bonn/"]}, SITE)
        self.assertEqual([i[1] for i in accepted], [SITE + "/rent/bonn/"])


class LangPreset(unittest.TestCase):
    def tearDown(self):
        os.environ["INDEXGAP_LANG"] = "ru"
        i18n.set_lang("ru")

    def test_unknown_lang_keeps_the_environment_language(self):
        os.environ["INDEXGAP_LANG"] = "ru"
        self.assertEqual(cli.preset_language(["check", "--lang", "xx"]), "ru")
        self.assertEqual(cli.preset_language(["check", "--lang=xx"]), "ru")
        self.assertEqual(cli.preset_language(["check", "--lang", "en"]), "en")


if __name__ == "__main__":
    unittest.main()
