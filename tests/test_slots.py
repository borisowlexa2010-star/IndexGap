# -*- coding: utf-8 -*-
"""
Незаполненные слоты шаблона: самая программная из ошибок программных страниц.

Три ревьюера из четырёх пришли к одному: `{{city}}`, `{city}`, `%CITY%`,
`undefined`, `NaN`, `[object Object]`, «Plumbing in , TX», lorem ipsum и
«As an AI language model» проходили молча. Описание пакета обещает «швы
шаблона», а ловились только его собственные метки брифа.

Ложные тревоги здесь легко устроить, и тесты на них — половина файла: код
в `<pre>`/`<code>`, формулы TeX, слово «None» в обычной фразе, документация
по JavaScript, где «undefined» — предмет текста, и исходники Markdown, в
которых `{{ }}` — законный синтаксис Hugo и Jekyll.
"""

import json
import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import content, core

SITE = "https://example.com"
TEXT = ("Plumbers in Austin fix leaks, unclog drains and install water heaters. "
        "Most visits take under two hours, and every job comes with a written quote.")


def html(body, title="Plumbers in Austin, TX", description="Licensed plumbers in Austin",
         h1="Plumbers in Austin", jsonld=None):
    ld = (f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
          if jsonld else "")
    return (f"<!doctype html><html lang=\"en\"><head><title>{title}</title>"
            f"<meta name=\"description\" content=\"{description}\">{ld}</head>"
            f"<body><main><h1>{h1}</h1>{body}</main></body></html>")


class Slots(unittest.TestCase):
    def pages(self, files):
        root = tempfile.mkdtemp(prefix="indexgap-slots-")
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return core.load_pages(root, SITE)[0]

    def found(self, text, name="index.html", fields=()):
        issues = content.check_slots(self.pages({name: text}), fields=fields)
        return [(level, code, message) for level, _, code, message in issues]

    def codes(self, *args, **kw):
        return [(level, code) for level, code, _ in self.found(*args, **kw)]

    # -- ловится -----------------------------------------------------------

    def test_template_syntax_in_the_text(self):
        for slot in ("{{city}}", "{{ city.name }}", "{city}", "${city}", "%CITY%",
                     "{% if city %}"):
            with self.subTest(slot=slot):
                got = self.found(html(f"<p>{TEXT} Call our {slot} team today.</p>"))
                self.assertEqual([(l, c) for l, c, _ in got], [("critical", "unfilled-slot")])
                self.assertIn(slot.strip(), got[0][2])

    def test_template_syntax_in_title_description_and_h1(self):
        self.assertIn(("critical", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT}</p>", title="Plumbers in {{city}}")))
        self.assertIn(("critical", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT}</p>", description="Best %SERVICE% near you")))
        self.assertIn(("critical", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT}</p>", h1="Plumbers in {City}")))

    def test_values_the_code_failed_to_fill(self):
        for title in ("Plumbers in undefined", "NaN plumbers in Austin",
                      "Plumbers in Austin, null", "Plumbers in None"):
            with self.subTest(title=title):
                self.assertIn(("critical", "unfilled-slot"),
                              self.codes(html(f"<p>{TEXT}</p>", title=title)))
        self.assertIn(("critical", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT} Price from [object Object].</p>")))
        self.assertIn(("critical", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT} Average cost: $NaN per hour.</p>")))

    def test_an_empty_slot_in_the_title(self):
        self.assertIn(("warning", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT}</p>", title="Plumbers in , TX")))
        self.assertIn(("warning", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT}</p>", title=" | Acme Plumbing")))

    def test_jsonld_values(self):
        ld = {"@context": "https://schema.org", "@type": "LocalBusiness",
              "name": "Acme {{city}}", "address": {"addressLocality": "undefined"}}
        self.assertIn(("critical", "unfilled-slot"),
                      self.codes(html(f"<p>{TEXT}</p>", jsonld=ld)))

    def test_lorem_ipsum(self):
        self.assertIn(("warning", "unfilled-slot"), self.codes(html(
            f"<p>{TEXT}</p><p>Lorem ipsum dolor sit amet, consectetur adipiscing.</p>")))

    def test_column_names_of_the_dataset_in_brackets(self):
        page = html(f"<p>{TEXT} Serving [City] since 1999.</p>")
        self.assertEqual(self.codes(page), [])
        self.assertEqual(self.codes(page, fields=["city", "service"]),
                         [("critical", "unfilled-slot")])

    def test_llm_leftovers(self):
        for phrase in ("As an AI language model, I cannot verify prices.",
                       "Certainly! Here is a rewritten version of the page:",
                       "Конечно! Вот переписанный текст:"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.codes(html(f"<p>{TEXT}</p><p>{phrase}</p>")),
                                 [("warning", "llm-leftover")])

    def test_mojibake(self):
        self.assertEqual(self.codes(html(f"<p>{TEXT} Weâ€™re open daily. CafÃ© nearby.</p>")),
                         [("warning", "mojibake")])

    def test_one_finding_per_page_and_kind(self):
        got = self.found(html(f"<p>{TEXT} {{{{city}}}} and {{{{state}}}} and %ZIP%.</p>",
                              title="Plumbers in {{city}}"))
        self.assertEqual(len(got), 1)

    # -- не ловится --------------------------------------------------------

    def test_code_blocks_are_not_text(self):
        body = (f"<p>{TEXT}</p><pre>{{{{ city }}}} ${{city}} undefined NaN</pre>"
                "<p>Use <code>{{city}}</code> or <code>%CITY%</code> in your template.</p>")
        self.assertEqual(self.codes(html(body)), [])

    def test_scripts_and_templates_are_not_text(self):
        body = (f"<p>{TEXT}</p><script>var t = '{{{{city}}}}'; x = undefined;</script>"
                "<template><p>{{city}}</p></template><!-- {{city}} -->")
        self.assertEqual(self.codes(html(body)), [])

    def test_tex_formulas_are_not_slots(self):
        body = f"<p>{TEXT} The ratio is $\\frac{{a}}{{b}}$ and $x^{{n}}$ for every n.</p>"
        self.assertEqual(self.codes(html(body)), [])

    def test_ordinary_words(self):
        body = (f"<p>{TEXT} None of our plumbers charge for a call-out. "
                "In JavaScript a missing property is undefined, and 0/0 is NaN.</p>")
        self.assertEqual(self.codes(html(body)), [])

    def test_a_preposition_ending_a_question_is_not_an_empty_slot(self):
        # eventiq.io: «Where do non-dues revenue numbers come from?»
        for value in ("Where do non-dues revenue numbers come from?",
                      "What is it made of.", "Pick-up lines to flirt in: a list"):
            with self.subTest(value=value):
                self.assertEqual(self.codes(html(f"<p>{TEXT}</p>", h1=value,
                                                 description=value)), [])

    def test_percent_and_braces_in_prose(self):
        body = (f"<p>{TEXT} Save 20% on repairs, 10% on parts. A set {{1, 2, 3}} "
                "has three items. Ages {18+} only.</p>")
        self.assertEqual(self.codes(html(body)), [])

    def test_markdown_sources_may_hold_template_syntax(self):
        md = ("---\ntitle: Plumbers\n---\n# Plumbers\n\n" + TEXT +
              " {{< figure src=\"a.png\" >}} and {{ site.title }} and {% include x.html %}\n")
        self.assertEqual(self.codes(md, name="plumbers.md"), [])

    def test_markdown_sources_still_get_lorem_and_llm(self):
        md = "---\ntitle: Plumbers\n---\n# Plumbers\n\n" + TEXT + " Lorem ipsum dolor sit amet.\n"
        self.assertEqual(self.codes(md, name="plumbers.md"), [("warning", "unfilled-slot")])

    def test_names_from_the_corpus_are_not_slots(self):
        # graphql-dotnet, dplyr, supplychain-attack-data, evan-moon.github.io
        for title in ("GraphQL for .NET", "Configuration in .editorconfig",
                      "Use pick() or across() in group_by()"):
            with self.subTest(title=title):
                self.assertEqual(self.codes(html(f"<p>{TEXT}</p>", title=title, h1=title)), [])
        body = (f"<p>{TEXT} The payload is written to %LOCALAPPDATA% and %TEMP%. "
                "For sets {C} and {D} the union is {C, D}.</p>")
        self.assertEqual(self.codes(html(body)), [])

    def test_a_clean_page(self):
        self.assertEqual(self.codes(html(f"<p>{TEXT}</p>")), [])


if __name__ == "__main__":
    unittest.main()
