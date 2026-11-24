# -*- coding: utf-8 -*-
"""
1.27: `indexgap diff` и правила редиректов, которые он понимал не так, как хостинг.

* `redirects` в vercel.json и `301!` у Netlify срабатывают раньше файлов:
  раздел, уведённый на главную, оставался «без изменений».
* `_redirects` читается только из каталога публикации.
* Правило 404/410 — ответ, а не редирект; перезапись 200 на главную для одного
  раздела — мягкий 404, как и запасной вход SPA.
* Условные правила (has, Language=, параметр запроса) у обхода не срабатывают.
* canonical на другой хост и смена формы адреса — правка шаблона.
* Заглушка в пустоту — то же, что редирект в пустоту.
* Раздел, уехавший редиректом, не приносит старые находки как новые.
* `:slug(regex)`, `routes`, `redirects = [{…}]` — тоже правила.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import cli, diff

SITE = "https://demo.example"
CITIES = 8


def page(title, words=120, head="", prefix=""):
    body = " ".join(f"word{i} text" for i in range(words))
    links = "".join(f'<a href="{prefix}/rent/c{i}/">City {i}</a> ' for i in range(CITIES))
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            f'<meta name="description" content="Rent things in the city, prices and tips for '
            f'{title}">{head}</head><body><main><h1>{title}</h1><p>{body}</p>'
            f'<a href="{prefix}/">Home</a> {links}</main></body></html>')


class Build:
    def __init__(self, root, prefix="", head=lambda url: ""):
        self.root = root
        base = prefix.strip("/") + "/" if prefix else ""
        self.write(base + "index.html", page("Rent home", head=head(prefix + "/"), prefix=prefix))
        for i in range(CITIES):
            url = f"{prefix}/rent/c{i}/"
            self.write(f"{base}rent/c{i}/index.html",
                       page(f"Rent in city {i}", head=head(url), prefix=prefix))

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def remove(self, name):
        shutil.rmtree(os.path.join(self.root, name))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-127-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old = Build(os.path.join(self.dir, "old"))
        self.new = Build(os.path.join(self.dir, "new"))
        self.out = os.path.join(self.dir, "d.html")

    def run_diff(self, *extra, new=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["diff", self.old.root, new or self.new.root, "--site", SITE,
                             "--out", self.out, *extra])
        with open(os.path.join(self.dir, "d.json"), encoding="utf-8") as fh:
            return code, json.load(fh)

    def level(self, data, url, code=None):
        got = [i["level"] for i in data["items"]
               if i["url"] == url and (code is None or i["code"] == code)]
        return got[0] if got else None


class ForcedRedirects(Base):
    """#43: правило раньше файла уводит страницу, которая есть в сборке."""

    def test_vercel_redirect_of_a_built_section_to_home_is_critical(self):
        self.new.write("vercel.json", json.dumps({"redirects": [
            {"source": "/rent/:slug", "destination": "/", "permanent": True}]}))
        code, data = self.run_diff("--strict", "--no-checks")
        self.assertEqual(code, 1)
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-redirected"), "critical")

    def test_forced_netlify_rule_to_another_host_is_a_warning(self):
        self.new.write("_redirects", "/rent/*  https://shop.example/:splat  301!\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-redirected"), "warning")

    def test_unforced_rule_does_not_shadow_a_built_page(self):
        self.new.write("_redirects", "/rent/*  /  301\n")
        code, data = self.run_diff("--strict", "--no-checks")
        self.assertEqual((code, data["summary"]["critical"], data["summary"]["warning"]), (0, 0, 0))

    def test_trailing_slash_and_host_redirects_are_not_findings(self):
        self.new.write("vercel.json", json.dumps({"redirects": [
            {"source": "/:path*/", "destination": "/:path*", "permanent": True},
            {"source": "/:path*", "has": [{"type": "host", "value": "www.demo.example"}],
             "destination": "https://demo.example/:path*", "permanent": True}]}))
        code, data = self.run_diff("--strict", "--no-checks")
        self.assertEqual((code, data["summary"]["critical"], data["summary"]["warning"]), (0, 0, 0))

    def test_forced_404_closes_a_built_page(self):
        self.new.write("_redirects", "/rent/c2  /404.html  404!\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c2/", "page-closed"), "critical")


class RedirectFilePlaces(Base):
    """#44: `_redirects` — только в каталоге публикации."""

    def test_redirects_next_to_the_publish_dir_are_not_deployed(self):
        proj = os.path.join(self.dir, "proj")
        dist = Build(os.path.join(proj, "dist"))
        dist.remove("rent/c1")
        with open(os.path.join(proj, "_redirects"), "w", encoding="utf-8") as fh:
            fh.write("/rent/c1/ /rent/c0/ 301\n")
        _, data = self.run_diff("--no-checks", new=dist.root)
        self.assertEqual(data["redirects"], [])
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-removed"), "critical")

    def test_netlify_toml_one_level_up_is_still_read(self):
        proj = os.path.join(self.dir, "proj")
        dist = Build(os.path.join(proj, "dist"))
        dist.remove("rent/c1")
        with open(os.path.join(proj, "netlify.toml"), "w", encoding="utf-8") as fh:
            fh.write('[[redirects]]\nfrom = "/rent/c1/"\nto = "/rent/c0/"\nstatus = 301\n')
        _, data = self.run_diff("--no-checks", new=dist.root)
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-redirected"), "info")


class Answers(Base):
    """#45, #46: ошибка и мягкий 404 — не редирект."""

    def test_404_and_410_rules_stop_a_later_catch_all(self):
        for i in (1, 2, 3):
            self.new.remove(f"rent/c{i}")
        for i in range(4):
            self.new.write(f"flats/c{i}/index.html", page(f"Flat {i}"))
        self.new.write("_redirects", "/rent/c1 /404.html 404\n/rent/c2 /gone.html 410\n"
                                     "/rent/* /flats/:splat 301\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-removed"), "critical")
        self.assertEqual(self.level(data, SITE + "/rent/c2/", "page-removed"), "critical")
        self.assertEqual(self.level(data, SITE + "/rent/c3/", "page-redirected"), "info")
        c2 = [r for r in data["removed"] if r["url"] == SITE + "/rent/c2/"][0]
        self.assertEqual((c2["redirect"], c2["answer"]), (None, "410"))

    def test_section_rewrite_to_home_is_a_soft_404(self):
        for i in (1, 2):
            self.new.remove(f"rent/c{i}")
        self.new.write("_redirects", "/rent/*    /index.html  200\n")
        code, data = self.run_diff("--strict", "--no-checks")
        self.assertEqual(code, 1)
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-removed"), "critical")

    def test_vercel_section_rewrite_to_home_is_a_soft_404(self):
        self.new.remove("rent/c1")
        self.new.write("vercel.json", json.dumps({"rewrites": [
            {"source": "/rent/(.*)", "destination": "/"}]}))
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-removed"), "critical")

    def test_rewrite_to_another_page_is_still_covered(self):
        self.new.remove("rent/c1")
        self.new.write("_redirects", "/rent/c1  /rent/c0/  200\n")
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-redirected"), "info")


class Conditions(Base):
    """#47: условное правило у обхода не срабатывает."""

    def setUp(self):
        super().setUp()
        self.new.remove("rent/c1")

    def removed_level(self):
        _, data = self.run_diff("--no-checks")
        return self.level(data, SITE + "/rent/c1/")

    def test_vercel_has_another_host(self):
        self.new.write("vercel.json", json.dumps({"redirects": [
            {"source": "/rent/:slug", "has": [{"type": "host", "value": "legacy.example"}],
             "destination": "/rent/c0/", "permanent": True}]}))
        self.assertEqual(self.removed_level(), "critical")

    def test_vercel_has_the_site_host_applies(self):
        self.new.write("vercel.json", json.dumps({"redirects": [
            {"source": "/rent/c1", "has": [{"type": "host", "value": "demo.example"}],
             "destination": "/rent/c0/", "permanent": True}]}))
        self.assertEqual(self.removed_level(), "info")

    def test_netlify_language_condition(self):
        self.new.write("_redirects", "/rent/*  /rent/c0/  301  Language=de\n")
        self.assertEqual(self.removed_level(), "critical")

    def test_netlify_query_match(self):
        self.new.write("_redirects", "/rent/c1  id=:id  /rent/c0/?id=:id  301\n")
        self.assertEqual(self.removed_level(), "critical")

    def test_netlify_toml_conditions(self):
        self.new.write("netlify.toml", '[[redirects]]\nfrom = "/rent/c1"\nto = "/rent/c0/"\n'
                                       'status = 301\nconditions = {Country = ["de"]}\n')
        self.assertEqual(self.removed_level(), "critical")

    def test_host_scoped_source_of_another_host(self):
        self.new.write("_redirects", "https://legacy.example/rent/*  /rent/c0/  301!\n")
        self.assertEqual(self.removed_level(), "critical")


class TemplateFields(Base):
    """#48, #49: canonical на другой хост и смена формы адреса."""

    def test_canonical_switched_to_http_www(self):
        self.old = Build(os.path.join(self.dir, "old2"),
                         head=lambda u: f'<link rel="canonical" href="https://demo.example{u}">')
        self.new = Build(os.path.join(self.dir, "new2"),
                         head=lambda u: f'<link rel="canonical" href="http://www.demo.example{u}">')
        _, data = self.run_diff("--no-checks")
        changes = [c for c in data["template_changes"] if c["field"] == "canonical"]
        self.assertTrue(changes and changes[0]["template"])
        self.assertEqual(self.level(data, "/rent/*/", "template-change"), "warning")

    def test_a_new_self_canonical_is_not_a_change(self):
        self.new = Build(os.path.join(self.dir, "new2"),
                         head=lambda u: f'<link rel="canonical" href="https://demo.example{u}">')
        _, data = self.run_diff("--no-checks")
        self.assertEqual([c for c in data["template_changes"] if c["field"] == "canonical"], [])

    def test_url_form_change_across_a_section(self):
        for i in range(CITIES):
            src = os.path.join(self.new.root, "rent", f"c{i}")
            os.rename(os.path.join(src, "index.html"),
                      os.path.join(self.new.root, "rent", f"c{i}.html"))
            os.rmdir(src)
        _, data = self.run_diff("--no-checks")
        changes = [c for c in data["template_changes"] if c["field"] == "url"]
        self.assertTrue(changes and changes[0]["template"])
        self.assertEqual(changes[0]["examples"][0]["old"], "/rent/c0/")

    def test_identical_builds_stay_quiet(self):
        code, data = self.run_diff("--strict", "--no-checks")
        self.assertEqual((code, data["summary"]), (0, {"critical": 0, "warning": 0, "info": 0}))


class Stubs(Base):
    """#50: заглушка в пустоту — как редирект в пустоту."""

    def test_stub_to_a_missing_page_is_a_warning(self):
        self.new.write("rent/c1/index.html",
                       '<!doctype html><html><head><meta http-equiv="refresh" '
                       'content="0; url=/flats/c1/"></head><body></body></html>')
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-redirected"), "warning")

    def test_stub_to_a_built_page_is_info(self):
        self.new.write("rent/c1/index.html",
                       '<!doctype html><html><head><meta http-equiv="refresh" '
                       'content="0; url=/rent/c0/"></head><body></body></html>')
        _, data = self.run_diff("--no-checks")
        self.assertEqual(self.level(data, SITE + "/rent/c1/", "page-redirected"), "info")


class MovedSection(Base):
    """#51: раздел под /en/ уносит старые находки с собой."""

    def test_old_findings_follow_the_redirect(self):
        proj = os.path.join(self.dir, "proj")
        moved = Build(os.path.join(proj, "new"), prefix="/en")
        with open(os.path.join(proj, "netlify.toml"), "w", encoding="utf-8") as fh:
            fh.write('[[redirects]]\n  from = "/*"\n  to = "/en/:splat"\n  status = 301\n')
        _, data = self.run_diff(new=moved.root)
        self.assertEqual([i for i in data["items"] if i["code"] == "new-finding"], [])
        c1 = [r for r in data["removed"] if r["url"] == SITE + "/rent/c1/"][0]
        self.assertEqual(c1["redirect_to"], SITE + "/en/rent/c1/")
        self.assertEqual(c1["redirect"], "/en/:splat")


class RuleFormats(unittest.TestCase):
    """#52: правила, которые не читались."""

    def test_regex_constrained_param(self):
        rules = diff._vercel(json.dumps({"redirects": [
            {"source": "/rent/:slug(c[0-9]+)", "destination": "/rent/"}]}), "vercel.json")
        self.assertEqual(diff.redirect_for(rules, SITE + "/rent/c3/"), "/rent/")
        self.assertEqual(diff.redirect_for(rules, SITE + "/rent/x3/"), "")

    def test_netlify_parentheses_are_literal(self):
        rules = diff._netlify_lines("/a(b) /c 301\n", "_redirects")
        self.assertEqual(diff.redirect_for(rules, SITE + "/a(b)"), "/c")
        self.assertEqual(diff.redirect_for(rules, SITE + "/ab"), "")

    def test_vercel_routes(self):
        rules = diff._vercel(json.dumps({"routes": [
            {"handle": "filesystem"},
            {"src": "/rent/c1/?", "status": 301, "headers": {"Location": "/rent/c0/"}},
            {"src": "/rent/(?<slug>[^/]+)", "status": 308, "headers": {"Location": "/flats/$1"}}]}),
            "vercel.json")
        self.assertEqual(diff.redirect_for(rules, SITE + "/rent/c1/"), "/rent/c0/")
        self.assertEqual(diff.destination(rules, SITE + "/rent/c2"), SITE + "/flats/c2")

    def test_netlify_toml_inline_array(self):
        rules = diff._netlify_toml(
            'redirects = [\n  { from = "/rent/c1/", to = "/rent/c0/", status = 301 },\n'
            '  { from = "/rent/c2/", to = "/rent/c0/", conditions = { Country = ["de"] } },\n'
            ']\n', "netlify.toml")
        self.assertEqual(diff.redirect_for(rules, SITE + "/rent/c1/"), "/rent/c0/")
        self.assertEqual(diff.redirect_for(rules, SITE + "/rent/c2/"), "")

    def test_redirects_headers_subtable_keeps_the_block(self):
        rules = diff._netlify_toml('[[redirects]]\nfrom = "/rent/c1/"\n[redirects.headers]\n'
                                   '  X-From = "a"\n\n[[redirects]]\nfrom = "/rent/c2/"\n'
                                   'to = "/rent/c0/"\n', "netlify.toml")
        # Блок без `to` (его ключи — в подтаблице) не правило; следующий — правило.
        self.assertEqual(diff.redirect_for(rules, SITE + "/rent/c1/"), "")
        self.assertEqual(diff.redirect_for(rules, SITE + "/rent/c2/"), "/rent/c0/")


if __name__ == "__main__":
    unittest.main()
