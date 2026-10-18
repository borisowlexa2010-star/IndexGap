# -*- coding: utf-8 -*-
"""
Догадки `init` на настоящих проектах.

Ревьюер прошёл первый запуск на заготовках Next.js, Astro и Hugo:

* при готовой сборке `init` всё равно брал исходники Markdown — на Hugo
  каждая страница становилась сиротой, `no-h1` стоял на 12 из 12;
* адрес сайта брался из строки `"$schema": "https://openapi.vercel.sh/…"`
  любого vercel.json и из `homepage` на gitlab.com;
* демо-сайт из README с датасетом рядом получал профиль «лендинги».
"""

import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import install


def page(title, canonical=""):
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return (f"<!doctype html><html lang=\"en\"><head><title>{title}</title>{link}</head>"
            f"<body><main><h1>{title}</h1><p>{'text of the page ' * 60}</p></main></body></html>")


class Guesses(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-init-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def hugo(self, built=True):
        self.write("hugo.toml", 'title = "Docs"\n')
        for i in range(6):
            self.write(f"content/p{i}.md", f"---\ntitle: P{i}\n---\n\n" + "text " * 80)
        if built:
            self.write("public/index.html", page("Home"))
            for i in range(6):
                self.write(f"public/p{i}/index.html", page(f"P{i}"))

    def test_a_complete_build_beats_the_sources(self):
        self.hugo()
        self.assertEqual(install.detect_content_dir(self.dir), os.path.join(".", "public"))

    def test_sources_without_a_build_are_still_found(self):
        self.hugo(built=False)
        self.assertEqual(install.detect_content_dir(self.dir), os.path.join(".", "content"))

    def test_a_partial_build_does_not_beat_the_sources(self):
        self.hugo(built=False)
        self.write("public/index.html", page("Home"))
        self.assertEqual(install.detect_content_dir(self.dir), os.path.join(".", "content"))

    def test_vercel_schema_is_not_the_site(self):
        self.write("vercel.json", json.dumps({"$schema": "https://openapi.vercel.sh/vercel.json",
                                              "cleanUrls": True}))
        self.assertEqual(install.detect_site(self.dir), "")

    def test_a_git_host_homepage_is_not_the_site(self):
        self.write("package.json", json.dumps({"name": "site",
                                               "homepage": "https://gitlab.com/acme/site"}))
        self.assertEqual(install.detect_site(self.dir), "")

    def test_the_canonical_of_built_pages_names_the_site(self):
        self.write("out/index.html", page("Home", "https://fixright.example/"))
        self.write("vercel.json", json.dumps({"$schema": "https://openapi.vercel.sh/vercel.json"}))
        self.assertEqual(install.detect_site(self.dir, "./out"), "https://fixright.example/")

    def test_a_dataset_beside_built_pages_is_a_catalogue(self):
        for i in range(10):
            self.write(f"site/p{i}/index.html", page(f"City {i}"))
        self.write("data/cities.csv", "keyword,city\nplumber austin,Austin\n")
        profile, _why = install.detect_profile(self.dir, "site", "./data/cities.csv")
        self.assertEqual(profile, "catalog")


if __name__ == "__main__":
    unittest.main()
