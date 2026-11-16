# -*- coding: utf-8 -*-
"""
1.25: многоязычные случаи, где отчёт молчал или ошибался.

* `fact-drift`: процент и цена в явной валюте не «пересчитываются» — 85% →
  42% и €35 → €70 больше не принимаются за смену валюты;
* x-default на общую страницу выбора языка не склеивает все кластеры сайта;
* `&rlm;` рядом с числом, турецкое «%85» и «35 TL» — тоже факты;
* японский текст под lang="zh" и китайский под lang="ja"/"ko";
* один `<code>` на странице прозы не выключает проверку языка текста;
* ширина тайского заголовка — не ширина иероглифов;
* греческий `;` и тайские вопросительные слова — вопросы.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import aeo, core, facts, settings, signals

SITE = "https://demo.example"
LANGS = ("en", "de", "fr")
FILLER = {
    "en": "Applicants prepare the passport, a recent photo and the hotel booking. "
          "The form is filled in online and the answer is sent by email.",
    "de": "Antragsteller bereiten den Reisepass, ein aktuelles Foto und die Buchung "
          "des Hotels vor. Das Formular wird online ausgefüllt.",
    "fr": "Les demandeurs préparent le passeport, une photo récente et la réservation "
          "de l'hôtel. Le formulaire est rempli en ligne.",
}
FACT = {
    "en": "The visa fee is {price} and about {pct} of applications are approved.",
    "de": "Die Visagebühr beträgt {price} und etwa {pct} der Anträge werden genehmigt.",
    "fr": "Les frais de visa sont de {price} et environ {pct} des demandes sont approuvées.",
}


class Site(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="indexgap-125-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def city(self, city, overrides=None, xdefault=None, langs=LANGS):
        overrides = overrides or {}
        for lang in langs:
            price, pct = overrides.get(lang, ("$35", "85%"))
            alts = "".join(f'<link rel="alternate" hreflang="{code}" '
                           f'href="{SITE}/{code}/visa/{city}/">' for code in langs)
            target = xdefault or f"{SITE}/en/visa/{city}/"
            alts += f'<link rel="alternate" hreflang="x-default" href="{target}">'
            body = FACT[lang].format(price=price, pct=pct) + " " + FILLER[lang]
            self.write(f"{lang}/visa/{city}/index.html",
                       f'<!doctype html><html lang="{lang}"><head><title>Visa {city} {lang}'
                       f'</title><link rel="canonical" href="{SITE}/{lang}/visa/{city}/">'
                       f"{alts}</head><body><main><h1>Visa {city}</h1><p>{body}</p>"
                       "</main></body></html>")

    def drift(self):
        pages, _ = core.load_pages(self.root, SITE)
        return sorted(i[1].replace(SITE, "") for i in facts.drift(pages))


class TestDriftNotConversion(Site):
    def test_percent_and_explicit_currency_are_never_conversions(self):
        self.city("paris", {"de": ("$35", "42%")})
        self.city("rome", {"de": ("$35", "8.5%")})
        self.city("lisbon", {"de": ("€70", "85%"), "en": ("€35", "85%"),
                             "fr": ("€35", "85%")})
        self.city("vienna", {"de": ("350 USD", "85%"), "en": ("35 USD", "85%"),
                             "fr": ("35 USD", "85%")})
        self.assertEqual(self.drift(), ["/de/visa/lisbon/", "/de/visa/paris/",
                                        "/de/visa/rome/", "/de/visa/vienna/"])

    def test_bare_dollar_conversion_is_still_localisation(self):
        # «$700» под тем же знаком — пересчёт в песо, а не расхождение.
        self.city("madrid", {"de": ("$700", "85%")})
        self.assertEqual(self.drift(), [])


class TestXDefaultSelector(Site):
    def test_shared_language_selector_does_not_merge_clusters(self):
        self.write("index.html", '<!doctype html><html lang="en"><head><title>Choose a '
                   'language</title></head><body><main><h1>Language</h1><p><a href="/en/">'
                   "English</a></p></main></body></html>")
        self.city("paris", {"de": ("$53", "85%")}, xdefault=SITE + "/")
        self.city("rome", {"fr": ("$35", "58%")}, xdefault=SITE + "/")
        self.city("madrid", xdefault=SITE + "/")
        self.assertEqual(self.drift(), ["/de/visa/paris/", "/fr/visa/rome/"])


class TestNumbersInEveryScript(unittest.TestCase):
    def facts(self, text):
        class Page:
            pass
        page = Page()
        page.text = text
        return facts.facts_of(page)

    def test_bidi_marks_next_to_numbers(self):
        self.assertEqual(self.facts("الإيجار ‏1,450‏ دولارا"),
                         {"USD": {"1450": "1450 دولارا"}})
        self.assertEqual(set(self.facts("الرسوم 35 ‏دولارا")), {"USD"})
        self.assertEqual(set(self.facts("53‏ דולר")), {"USD"})

    def test_turkish_percent_before_number_and_lira(self):
        self.assertEqual(self.facts("başvuruların yaklaşık %85'i onaylanır"),
                         {"%": {"85": "85 %"}})
        self.assertEqual(self.facts("ücret 35 TL"), {"TRY": {"35": "35 TL"}})

    def test_percent_encoded_urls_are_not_percents(self):
        self.assertEqual(self.facts("see example.com/a%20b and ?q=%20x"), {})


ZH = "这个页面介绍如何在项目中使用组件，以及常见问题的解决方法。我们会一步一步说明配置过程。" * 6
JA = "このページでは、プロジェクトでコンポーネントを使う方法と、よくある質問を説明します。" * 6
KO = "이 글에서는 프로젝트에서 컴포넌트를 사용하는 방법과 자주 묻는 질문을 설명합니다. " * 6
EN = ("This page explains how to apply for the visa, which documents are needed and "
      "how long the review takes for most travellers who apply online. ") * 4
DE = ("Diese Seite erklärt, wie man das Visum beantragt, welche Unterlagen man braucht "
      "und wie lange die Prüfung für die meisten Reisenden dauert. ") * 4


class TestLanguageOfText(Site):
    def found(self, lang, text, extra=""):
        self.write("index.html", f'<!doctype html><html lang="{lang}"><head><title>Page'
                   f"</title></head><body><main><h1>Title</h1><p>{text}</p>{extra}</main>"
                   "</body></html>")
        pages, _ = core.load_pages(self.root, SITE)
        return [i[2] for i in signals.lang_script(pages)]

    def test_cjk_swaps(self):
        self.assertEqual(self.found("zh", JA), ["lang-script-mismatch"])
        self.assertEqual(self.found("ja", ZH), ["lang-script-mismatch"])
        self.assertEqual(self.found("ko", ZH), ["lang-script-mismatch"])

    def test_correct_cjk_pages_are_silent(self):
        self.assertEqual(self.found("zh", ZH), [])
        self.assertEqual(self.found("ja", JA), [])
        self.assertEqual(self.found("ko", KO), [])

    def test_one_inline_code_does_not_hide_untranslated_body(self):
        code = "<p>Form <code>B14</code></p>"
        self.assertEqual(self.found("de", EN, code), ["lang-text-mismatch"])
        self.assertEqual(self.found("ru", EN, code), ["lang-script-mismatch"])
        self.assertEqual(self.found("de", DE, code), [])

    def test_docs_page_with_much_code_stays_silent(self):
        code = "<pre><code>" + "const value = await fetchComponentList(options);\n" * 40
        code += "</code></pre>"
        self.assertEqual(self.found("de", EN, code), [])
        self.assertEqual(self.found("ru", EN, code), [])


class TestWidthAndQuestions(unittest.TestCase):
    def test_thai_is_not_double_width(self):
        title = "ค่าธรรมเนียมวีซ่าสำหรับนักท่องเที่ยวในกรุงเทพ"
        self.assertEqual(settings.display_width(title), 35)
        self.assertEqual(settings.display_width("泰国 Form"), 9)
        self.assertEqual(settings.display_width("ビザ"), 4)

    def test_greek_and_thai_questions(self):
        for heading in ("Πόσο κοστίζει η βίζα;", "Ποια έγγραφα χρειάζονται;",
                        "ค่าวีซ่าเท่าไหร่", "ต้องใช้เอกสารอะไรบ้าง", "ใช้เวลาพิจารณานานแค่ไหน"):
            self.assertTrue(aeo.QUESTION.search(heading), heading)
        for heading in ("Τέλη βίζας", "ค่าธรรมเนียมวีซ่า", "Fees; overview"):
            self.assertFalse(aeo.QUESTION.search(heading), heading)


if __name__ == "__main__":
    unittest.main()
