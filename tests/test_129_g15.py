# -*- coding: utf-8 -*-
"""
1.29 (g15): title, description и картинки.

* itemprop="description" в теле и второй пустой тег не заменяют описание
  страницы;
* дубли title без lang не делятся по «языку» из `/ca/`, `/de/`, `/pa/`;
* title-h1-mismatch работает на русских title с «в», «с», «и»;
* title из невидимых знаков — no-title;
* ширина считается по East Asian Width: полноширинные знаки и 【】｜;
* картинки после врезки <article> и декоративные role/aria-hidden;
* heavy-images смотрит весь корень сборки и виден в --baseline;
* заготовки шаблона и стоковые имена в alt;
* имена моделей и мест — не «непереведённый alt»;
* Markdown: примеры в блоках кода — не картинки, сырой <img> без alt — да.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, checks, cli, settings, signals
from indexgap.core import load_pages
from indexgap.signals import _title_h1_apart

SITE = "https://demo.example"
WORDS = " ".join(f"word{i} item{i} note{i}" for i in range(120))


def html(title="Plumbing services in the city", head="", body="", lang=' lang="en"'):
    return (f"<!doctype html><html{lang}><head><meta charset='utf-8'><title>{title}</title>"
            f"{head}</head><body>{body}<p>{WORDS}</p></body></html>")


DESC = ("<meta name='description' content='Find trusted local plumbers near you with "
        "prices, reviews and availability for every neighbourhood.'>")


class Site(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-129g15-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, text, mode="w"):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
            fh.write(text)

    def pages(self):
        pages, _ = load_pages(self.dir, SITE)
        return {p.url.replace(SITE, ""): p for p in pages}

    def codes(self, issues, url):
        return [i[2] for i in issues if i[1] == SITE + url]


class Description(Site):
    def test_body_microdata_does_not_replace_the_description(self):
        self.write("index.html", html(body="<div itemscope><meta itemprop='description' "
                                      "content='Widget'></div>"))
        p = self.pages()["/"]
        self.assertEqual(p.description, "")
        self.assertIn("no-description", self.codes(checks.technical_issues([p]), "/"))

    def test_microdata_keeps_the_head_description(self):
        self.write("index.html", html(head=DESC, body="<meta itemprop='description' content=''>"))
        self.assertTrue(self.pages()["/"].description.startswith("Find trusted"))

    def test_an_empty_second_tag_does_not_wipe_the_first(self):
        self.write("index.html", html(head=DESC + "<meta name='description' content=''>"))
        p = self.pages()["/"]
        self.assertTrue(p.description.startswith("Find trusted"))
        self.assertNotIn("no-description", self.codes(checks.technical_issues([p]), "/"))


class InvisibleTitle(Site):
    def test_zero_width_title_is_no_title(self):
        for title in ("&#8203;", "&#xFEFF;", "&shy;"):
            with self.subTest(title=title):
                self.write("index.html", html(title=title, head=DESC))
                codes = self.codes(checks.technical_issues(list(self.pages().values())), "/")
                self.assertIn("no-title", codes)
                self.assertNotIn("title-short", codes)


class StateCodes(Site):
    def test_state_prefixes_are_not_languages(self):
        for rel in ("", "ca/", "ny/", "de/", "pa/", "co/"):
            self.write(rel + "index.html", html(title="Plumbers near you - Example plumbing",
                                                head=DESC, lang=""))
        issues = checks.technical_issues(list(self.pages().values()))
        dupes = [i for i in issues if i[2] == "duplicate-title"]
        self.assertEqual(len(dupes), 6)
        self.assertEqual(len([i for i in issues if i[2] == "duplicate-description"]), 6)

    def test_real_translations_stay_apart(self):
        de = " ".join(["der Klempner und die Preise für das Haus sind nicht zu hoch"] * 8)
        en = " ".join(["the plumber and the prices for the house are not too high"] * 8)
        self.write("index.html", html(title="Example", body=f"<p>{en}</p>", lang=""))
        self.write("de/index.html", html(title="Example", body=f"<p>{de}</p>", lang=""))
        issues = checks.technical_issues(list(self.pages().values()))
        self.assertFalse([i for i in issues if i[2] == "duplicate-title"])


class TitleH1(unittest.TestCase):
    def test_one_letter_cyrillic_words(self):
        self.assertTrue(_title_h1_apart("Купить диван недорого в Москве", "Ремонт ноутбуков Samsung"))
        self.assertTrue(_title_h1_apart("Restaurants à Paris pas chers", "Location voitures Lyon aéroport"))

    def test_cjk_is_still_skipped(self):
        self.assertFalse(_title_h1_apart("東京の配管工 料金", "大阪 修理 案内"))


class Width(unittest.TestCase):
    def test_fullwidth_and_cjk_punctuation(self):
        self.assertEqual(settings.display_width("東京の配管工｜ＡＢＣ"), 20)
        self.assertEqual(settings.display_width("ＡＢＣ１２３"), 12)
        self.assertEqual(settings.display_width("【】、。"), 8)
        self.assertEqual(settings.display_width("\U00020000" * 3), 6)

    def test_latin_and_emoji_unchanged(self):
        self.assertEqual(settings.display_width("abcd"), 4)
        self.assertEqual(settings.display_width("泰国 Form"), 9)
        self.assertEqual(settings.display_width("ok \U0001F600"), 4)


class Images(Site):
    def test_images_after_an_inline_article(self):
        body = ("<header><div>logo</div></header><div><h1>Gallery</h1>"
                "<article class='review'><p>Great</p></article>"
                "<img src='/1.jpg'><img src='/2.jpg'><img src='/3.jpg'></div>")
        self.write("index.html", html(body=body))
        self.assertEqual(self.pages()["/"].blocks["img_no_alt"], 3)

    def test_footer_and_nav_images_still_skipped(self):
        body = ("<main><h1>A</h1><img src='/a.jpg' alt='A harbour at dawn'></main>"
                "<footer><img src='/f.jpg'></footer><nav><img src='/n.jpg'></nav>")
        self.write("index.html", html(body=body))
        self.assertEqual(self.pages()["/"].blocks["img_no_alt"], 0)

    def test_decorative_role_and_aria_hidden(self):
        body = "<main><h1>A</h1><img src='/1.png' role='presentation'><img src='/2.png' aria-hidden='true'></main>"
        self.write("index.html", html(body=body))
        p = self.pages()["/"]
        self.assertEqual(p.blocks["img_no_alt"], 0)
        self.assertNotIn("img-no-alt", [i[2] for i in aeo.check_extractable(p)])


class HeavyImages(Site):
    def test_sibling_asset_folder(self):
        for rel in ("guides/index.html", "guides/a/index.html"):
            self.write(rel, html(head=DESC))
        self.write("images/hero.jpg", b"\0" * (2 * 1024 * 1024), "wb")
        found = signals.heavy_images(list(self.pages().values()))
        self.assertEqual(len(found), 1)
        self.assertIn("images/hero.jpg", found[0][3])

    def test_a_new_heavy_file_is_new_in_the_baseline(self):
        self.write("index.html", html(head=DESC))
        self.write("img/a.jpg", b"\0" * (2 * 1024 * 1024), "wb")
        before = signals.heavy_images(list(self.pages().values()))
        old = [{"level": l, "url": u, "code": c, "message": str(m),
                "subject": list(m.subject)} for l, u, c, m in before]
        self.write("img/b.jpg", b"\0" * (3 * 1024 * 1024), "wb")
        after = signals.heavy_images(list(self.pages().values()))
        self.assertEqual(len(cli.compare_baseline(after, old)["new"]), 1)
        self.assertEqual(len(cli.compare_baseline(before, old)["new"]), 0)


class AltText(unittest.TestCase):
    def test_template_leftovers_and_stock_names(self):
        for alt in ("{{ city_name }}", "{alt}", "%alt%", "undefined", "null",
                    "shutterstock_123456789", "AdobeStock_123456789", "pexels-photo-1234567",
                    "image (1).png", "pic.jpg?w=400", "Screenshot 2024-01-01 at 10.00.00",
                    "Untitled design (3)", "Placeholder image", "product image", "-", "..."):
            with self.subTest(alt=alt):
                self.assertTrue(aeo._alt_is_filler(alt))

    def test_real_descriptions_pass(self):
        for alt in ("WP-500 thermal printer", "Node.js", "Vue.js logo", "Nan with her grandson",
                    "Plumber fixing a sink in Austin", "Red sofa in a bright living room"):
            with self.subTest(alt=alt):
                self.assertFalse(aeo._alt_is_filler(alt))

    def page(self, lang, alts):
        class P:
            url = SITE + "/x/"
        p = P()
        p.lang = lang
        p.alts = [(a, "/x.jpg") for a in alts]
        return p

    def test_model_names_are_not_untranslated(self):
        self.assertFalse(aeo.check_alt_text(self.page("ru", [
            "Apple iPhone 15 Pro Max 256GB Natural Titanium",
            "Samsung Galaxy S24 Ultra Titanium Black", "Google Pixel 8 Pro Obsidian"])))
        self.assertFalse(aeo.check_alt_text(self.page("en", [
            "Museum für Naturkunde", "Haus der Kulturen der Welt", "Gärten der Welt",
            "Platz der Republik"])))

    def test_an_english_sentence_on_a_russian_page_still_counts(self):
        found = aeo.check_alt_text(self.page("ru", [
            "Technician repairing a phone screen in our workshop",
            "Our service center building at night"]))
        self.assertEqual([i[2] for i in found], ["img-alt-language"])


class Markdown(Site):
    def test_fenced_examples_are_not_images(self):
        self.write("docs/images.md", "---\ntitle: Images in Markdown syntax\nlang: en\n---\n"
                   "# Images\n\n" + WORDS + "\n\n```markdown\n![](cat.png)\n![image](bird.png)\n```\n")
        p = self.pages()["/docs/images/"]
        self.assertEqual(p.blocks["img"], 0)
        self.assertEqual(p.alts, [])

    def test_raw_img_and_reference_images(self):
        self.write("docs/gallery.md", "---\ntitle: Gallery of the workshop\nlang: en\n---\n"
                   "# Gallery\n\n" + WORDS + "\n\n<img src=\"/a.jpg\">\n<img src=\"/b.jpg\" alt=\"Bench\">\n\n"
                   "![IMG_2034.jpg][ref]\n\n[ref]: /c.jpg\n")
        p = self.pages()["/docs/gallery/"]
        self.assertEqual(p.blocks["img_no_alt"], 1)
        self.assertEqual(p.blocks["img"], 3)
        self.assertIn("IMG_2034.jpg", [a for a, _ in p.alts])


if __name__ == "__main__":
    unittest.main()
