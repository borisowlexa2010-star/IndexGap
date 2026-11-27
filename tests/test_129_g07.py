# -*- coding: utf-8 -*-
"""
1.29 (g07): noindex и canonical.

* X-Robots-Tag: директива после `max-image-preview:large` не теряется.
* Правило заголовков для www-зеркала не закрывает голый домен.
* netlify.toml: `[[ headers ]]`, `values.X-Robots-Tag`, литерал в '''…'''.
* `<meta property="robots">` — не директива.
* diff называет заголовок источником noindex.
* `/город/*` в _headers совпадает с %-кодированным путём страницы.
* Закрытые разделы: половина сайта и больше — не «решение»; ветки 101…108 — не
  версии документации; половина закрытых веток — тоже noindex-group.
* Несколько разных canonical, canonical в <body>.
* `//www.host/a/` и относительные canonical в голосовании за адрес сайта.
* Шаблонные копии под другой запрос с canonical на одну страницу.
* canonical-form: 404/410 и условные правила, `.git`, `.htm` и `index.md`.
* NFD-canonical не становится адресом страницы.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unicodedata
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import cli, core

SITE = "https://demo.example"


def html(title, head="", body="", h1=None, words=150):
    text = " ".join(f"{title.split()[0].lower()} word{i} text{i}" for i in range(words))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{title}</title>{head}</head><body><h1>{h1 or title}</h1>'
            f'<p>{text}</p>{body}<a href="/">home</a></body></html>')


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-129g07-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.site = os.path.join(self.dir, "site")
        os.makedirs(self.site)

    def write(self, rel, text, root=None):
        path = os.path.join(root or self.site, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def page(self, url_path, title=None, head="", body="", h1=None):
        rel = url_path.strip("/")
        rel = (rel + "/index.html") if rel else "index.html"
        self.write(rel, html(title or ("Page " + (url_path.strip("/") or "home")).replace("/", " "),
                             head, body, h1))

    def check(self, *extra, site=None):
        out = os.path.join(self.dir, "out", "r.json")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", site or self.site, "--site", SITE, "--out", out, *extra])
        with open(out, encoding="utf-8") as fh:
            return code, json.load(fh)

    @staticmethod
    def found(data, code):
        return sorted((i["level"], i["url"]) for i in data["issues"] if i["code"] == code)


class HeaderDirectives(unittest.TestCase):
    def test_directive_after_valued_directive(self):
        self.assertTrue(core._closes("max-image-preview:large, noindex"))
        self.assertTrue(core._closes("max-snippet:-1, noindex"))
        self.assertTrue(core._closes("unavailable_after: 2030-01-01, noindex"))
        self.assertTrue(core._unfollows("max-snippet:-1, noindex, nofollow"))
        self.assertTrue(core._hides_snippet("max-image-preview:large, nosnippet"))
        self.assertTrue(core._hides_snippet("max-video-preview: -1, nosnippet"))

    def test_bot_prefix_still_scopes(self):
        self.assertFalse(core._closes("otherbot: max-image-preview:large, noindex"))
        self.assertTrue(core._closes("googlebot: max-image-preview:large, noindex"))
        self.assertFalse(core._closes("max-image-preview:large, max-snippet:-1"))
        self.assertTrue(core._hides_snippet("max-snippet:0"))

    def test_www_rule_is_another_host(self):
        self.assertFalse(core._same_host("www.demo.example", "demo.example"))
        self.assertTrue(core._same_host("DEMO.example", "demo.example"))


class HeaderRules(Base):
    def build(self, files):
        self.page("/")
        for p in ("/a/one/", "/b/one/", "/c/one/"):
            self.page(p)
        for name, text in files.items():
            self.write(name, text)

    def test_headers_with_valued_directive_close(self):
        self.build({"_headers": "/a/*\n  X-Robots-Tag: max-image-preview:large, noindex\n"})
        _, data = self.check("--no-content", "--no-aeo")
        self.assertEqual(self.found(data, "noindex"), [("critical", SITE + "/a/one/")])

    def test_www_mirror_rule_leaves_apex_open(self):
        self.build({"_headers": "https://www.demo.example/*\n  X-Robots-Tag: noindex\n"})
        _, data = self.check("--no-content", "--no-aeo")
        self.assertEqual(self.found(data, "noindex"), [])

    def test_vercel_www_host_condition_leaves_apex_open(self):
        self.build({"vercel.json": json.dumps({"headers": [{
            "source": "/(.*)", "has": [{"type": "host", "value": "www.demo.example"}],
            "headers": [{"key": "X-Robots-Tag", "value": "noindex"}]}]})})
        _, data = self.check("--no-content", "--no-aeo")
        self.assertEqual(self.found(data, "noindex"), [])

    def test_netlify_toml_spelling_variants(self):
        self.build({"netlify.toml": (
            '[[ headers ]]\n  for = "/a/*"\n  [headers.values]\n    X-Robots-Tag = "noindex"\n\n'
            '[[headers]]\n  for = "/b/*"\n  values.X-Robots-Tag = "noindex"\n\n'
            "[[headers]]\n  for = \"/c/*\"\n  [headers.values]\n    X-Robots-Tag = '''noindex'''\n")})
        _, data = self.check("--no-content", "--no-aeo")
        self.assertEqual(self.found(data, "noindex"),
                         [("critical", SITE + p) for p in ("/a/one/", "/b/one/", "/c/one/")])

    def test_unicode_rule_matches_encoded_page_path(self):
        self.page("/")
        self.page("/город/один/", title="Город один")
        self.write("_headers", "/город/*\n  X-Robots-Tag: noindex\n")
        _, data = self.check("--no-content", "--no-aeo")
        urls = [u for _, u in self.found(data, "noindex")]
        self.assertEqual(len(urls), 1)
        self.assertIn("%D0%B3%D0%BE%D1%80%D0%BE%D0%B4", urls[0])

    def test_meta_property_robots_is_not_a_directive(self):
        self.page("/")
        self.page("/p/", head='<meta property="robots" content="noindex">')
        self.page("/i/", head='<meta itemprop="robots" content="noindex">')
        self.page("/n/", head='<meta name="robots" content="noindex">')
        _, data = self.check("--no-content", "--no-aeo")
        self.assertEqual(self.found(data, "noindex"), [("critical", SITE + "/n/")])


class DiffHeaderSource(Base):
    def test_diff_names_the_header(self):
        new = os.path.join(self.dir, "new")
        for root in (self.site, new):
            self.write("index.html", html("Home page"), root)
            self.write("a/one/index.html", html("Alpha one"), root)
        self.write("_headers", "/a/*\n  X-Robots-Tag: noindex\n", new)
        out = os.path.join(self.dir, "d.html")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["diff", self.site, new, "--site", SITE, "--no-checks", "--out", out])
        with open(os.path.join(self.dir, "d.json"), encoding="utf-8") as fh:
            items = json.load(fh)["items"]
        closed = [i for i in items if i["code"] == "page-closed"]
        self.assertEqual(len(closed), 1)
        self.assertIn("X-Robots-Tag", closed[0]["message"])
        self.assertNotIn("meta robots", closed[0]["message"])
        self.assertIn("/a/*", closed[0]["message"])


class ClosedBranches(Base):
    NAMES = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")

    def build(self, names, closed, per=20):
        self.write("index.html", "<!doctype html><html><head><title>Home</title></head>"
                                 "<body><h1>Home</h1></body></html>")
        for i, name in enumerate(names):
            head = '<meta name="robots" content="noindex">' if i < closed else ""
            for q in range(per):
                self.write(f"city/{name}/q{q}/index.html",
                           f"<!doctype html><html><head><title>{name} {q}</title>{head}</head>"
                           f"<body><h1>{name} {q}</h1></body></html>")

    def critical(self, closed, names=NAMES):
        self.build(names, closed)
        code, data = self.check("--strict", "--no-content", "--no-aeo")
        crit = [i for i in data["issues"] if i["level"] == "critical"
                and i["code"] in ("noindex", "noindex-group")]
        return code, crit

    def test_more_closed_branches_never_greener(self):
        for closed in (3, 4, 7):
            with self.subTest(closed=closed):
                shutil.rmtree(self.site)
                os.makedirs(self.site)
                code, crit = self.critical(closed)
                self.assertTrue(crit)
                self.assertEqual(code, 1)

    def test_numeric_branch_names_are_catalogue(self):
        code, crit = self.critical(3, names=tuple(str(n) for n in range(101, 109)))
        self.assertEqual([i["code"] for i in crit], ["noindex-group"])
        self.assertEqual(code, 1)

    def test_version_names_still_match(self):
        from indexgap.checks import _VERSION_BRANCH
        for name in ("v3", "1.2", "3", "2.x", "2019", "next"):
            self.assertTrue(_VERSION_BRANCH.match(name), name)
        for name in ("101", "1234", "alpha"):
            self.assertFalse(_VERSION_BRANCH.match(name), name)


class CanonicalPlacement(Base):
    def test_conflicting_canonicals_are_reported_and_ignored(self):
        self.page("/")
        self.page("/b/")
        self.page("/a/", head=f'<link rel="canonical" href="{SITE}/b/">'
                              f'<link rel="canonical" href="{SITE}/a/">')
        _, data = self.check("--no-content", "--no-aeo")
        notes = [i for i in data["issues"] if i["url"] == SITE + "/a/"
                 and i["code"] == "source-note" and "canonical" in i["message"]]
        self.assertEqual(len(notes), 1)
        self.assertEqual(self.found(data, "canonical-elsewhere"), [])

    def test_same_canonical_twice_is_fine(self):
        self.page("/")
        self.page("/a/", head=f'<link rel="canonical" href="{SITE}/a/">'
                              '<link rel="canonical" href="/a/">')
        _, data = self.check("--no-content", "--no-aeo")
        self.assertFalse([i for i in data["issues"] if i["code"] == "source-note"
                          and "canonical" in i["message"]])

    def test_head_canonical_wins_over_body(self):
        self.page("/")
        self.page("/b/")
        self.page("/a/", head=f'<link rel="canonical" href="{SITE}/b/">',
                  body=f'<link rel="canonical" href="{SITE}/a/">')
        _, data = self.check("--no-content", "--no-aeo")
        self.assertIn(SITE + "/a/", [u for _, u in self.found(data, "canonical-elsewhere")])

    def test_body_only_canonical_is_ignored(self):
        self.page("/")
        self.page("/c/")
        self.page("/d/", body=f'<link rel="canonical" href="{SITE}/c/">')
        _, data = self.check("--no-content", "--no-aeo")
        self.assertEqual(self.found(data, "canonical-elsewhere"), [])
        notes = [i for i in data["issues"] if i["url"] == SITE + "/d/"
                 and i["code"] == "source-note" and "<body>" in i["message"]]
        self.assertEqual(len(notes), 1)

    def test_noscript_pixel_in_head_keeps_canonical(self):
        ex = core._Extractor()
        ex.feed('<html><head><noscript><img src="/p.gif"></noscript>'
                '<link rel="canonical" href="/a/"></head><body></body></html>')
        ex.close()
        self.assertEqual((ex.canonical, ex.canonicals_in_body), ("/a/", []))


class CanonicalOrigin(Base):
    CITIES = ("a", "b", "c", "d", "e", "f", "g")

    def build(self, canon):
        self.page("/", head='<link rel="canonical" href="/">')
        for c in self.CITIES:
            self.page(f"/{c}/", head=f'<link rel="canonical" href="{canon.get(c, f"/{c}/")}">')

    def flagged(self):
        _, data = self.check("--no-content", "--no-aeo")
        return [u for _, u in self.found(data, "canonical-elsewhere")], data

    def test_protocol_relative_www(self):
        self.build({"a": "//www.demo.example/a/", "b": f"{SITE}/b/"})
        urls, _ = self.flagged()
        self.assertEqual(urls, [SITE + "/a/"])

    def test_protocol_relative_same_host_is_fine(self):
        self.build({"a": "//demo.example/a/"})
        urls, _ = self.flagged()
        self.assertEqual(urls, [])

    def test_relative_canonicals_vote_for_the_site(self):
        self.build({"a": "http://demo.example/a/", "b": "http://demo.example/b/",
                    "c": f"{SITE}/c/"})
        urls, data = self.flagged()
        self.assertEqual(urls, [SITE + "/a/", SITE + "/b/"])
        self.assertFalse([n for n in data["notes"] if "--site" in str(n)])

    def test_single_http_among_relative(self):
        self.build({"a": "http://demo.example/a/"})
        urls, _ = self.flagged()
        self.assertEqual(urls, [SITE + "/a/"])


class TemplateClones(Base):
    CITIES = ("berlin", "hamburg", "munich", "cologne", "dresden")

    def test_clones_with_own_titles_are_not_variants(self):
        self.page("/")
        body = ("A flat costs about the usual price a month. Landlords ask for a deposit of "
                "three months of rent and a folder with payslips and a passport. ") * 8
        for c in self.CITIES:
            self.write(f"rent/{c}/index.html",
                       f'<!doctype html><html lang="en"><head><title>Renting in {c.title()}</title>'
                       f'<link rel="canonical" href="{SITE}/rent/berlin/"></head>'
                       f'<body><h1>Renting in {c.title()}</h1><p>{body}</p>'
                       '<a href="/">home</a></body></html>')
        _, data = self.check("--no-aeo")
        found = self.found(data, "canonical-elsewhere")
        self.assertEqual(len(found), 4)
        self.assertTrue(all(level == "critical" for level, _ in found))

    def test_same_title_copy_is_still_a_variant(self):
        self.page("/")
        body = ("A flat costs about the usual price a month. Landlords ask for a deposit of "
                "three months of rent and a folder with payslips and a passport. ") * 8
        for c in ("berlin", "berlin-old"):
            self.write(f"rent/{c}/index.html",
                       '<!doctype html><html lang="en"><head><title>Renting in Berlin</title>'
                       f'<link rel="canonical" href="{SITE}/rent/berlin/"></head>'
                       f'<body><h1>Renting in Berlin</h1><p>{body}</p>'
                       '<a href="/">home</a></body></html>')
        _, data = self.check("--no-aeo")
        self.assertEqual(self.found(data, "canonical-elsewhere"),
                         [("info", SITE + "/rent/berlin-old/")])


class CanonicalForms(Base):
    def flat(self, name, canonical):
        self.write(name, html("Page " + name.split(".")[0].replace("/", " "),
                              head=f'<link rel="canonical" href="{canonical}">'))

    def forms(self, *extra):
        _, data = self.check("--no-content", "--no-aeo", *extra)
        return [u for _, u in self.found(data, "canonical-form")]

    def test_closing_and_conditional_redirects_do_not_serve(self):
        self.page("/", head='<link rel="canonical" href="/">')
        for n in ("team", "jobs", "news", "info"):
            self.flat(f"{n}.html", f"/{n}/")
        self.write("_redirects", "/team/ /404.html 404\n/jobs/ /gone.html 410\n"
                                 "/news/ /news.html 301 Country=de\n/info/ /info.html 301\n")
        self.assertEqual(self.forms(), [SITE + f"/{n}/" for n in ("jobs", "news", "team")])

    def test_git_folder_is_not_a_generator(self):
        self.page("/", head='<link rel="canonical" href="/">')
        self.flat("team.html", "/team/")
        os.makedirs(os.path.join(self.site, ".git"))
        self.assertEqual(self.forms(), [SITE + "/team/"])

    def test_other_extensions_are_not_served(self):
        self.page("/", head='<link rel="canonical" href="/">')
        self.flat("about.html", "/about.htm")
        self.flat("x/index.html", "/x/index.htm")
        self.flat("z/index.html", "/z/index.md")
        self.flat("ok.html", "/ok.html")
        self.flat("y/index.html", "/y/index.html")
        self.assertEqual(self.forms(),
                         [SITE + p for p in ("/about.htm", "/x/index.htm", "/z/index.md")])


class NfdCanonical(Base):
    def test_nfd_canonical_keeps_file_address(self):
        self.page("/")
        folder = unicodedata.normalize("NFC", "köln")
        nfd = "ko%CC%88ln"
        self.write(f"rent/{folder}/index.html",
                   html("Rent koeln", head=f'<link rel="canonical" href="{SITE}/rent/{nfd}/">'))
        pages, _ = core.load_pages(self.site, SITE)
        urls = [p.url for p in pages if "rent" in p.url]
        self.assertEqual(urls, [SITE + "/rent/k%C3%B6ln/"])


if __name__ == "__main__":
    unittest.main()
