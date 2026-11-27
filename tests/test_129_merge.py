"""Регрессии, найденные при сведении веток 1.29 и калибровке на большой сборке."""
import os
import shutil
import tempfile
import unittest

from indexgap import content, core

SITE = "https://demo.example/"


def page_html(country, topic):
    title = f"How does {topic} work for {country.title()} passport holders?"
    crumbs = "".join(f'<li><a href="{href}">{name}</a><span aria-hidden="true">›</span></li>'
                     for href, name in (("/", "Home"), ("/visa/", "Visa"),
                                        (f"/visa/{country}/", country.title())))
    crumbs = (f'<nav aria-label="Breadcrumb"><ol>{crumbs}'
              f'<li><span aria-current="page">{title}</span></li></ol></nav>')
    return (f'<!doctype html><html lang="en"><head><title>{title}</title></head>'
            f'<body><main>{crumbs}<article><h1>{title}</h1>'
            f'<p>Every {country.title()} visa question about {topic} starts with the passport '
            f'and the visa route that the traveller actually uses.</p></article></main>'
            f'</body></html>')


class OneWordCrumbs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-129-merge-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def load(self, country, topic):
        path = os.path.join(self.dir, f"{country}-{topic}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page_html(country, topic))
        return core.load_page(path, self.dir, SITE)

    def test_one_word_crumb_is_not_cut_out_of_the_text(self):
        # «Visa ›» и «Kazakhstan ›» — крошки из одного слова. Раньше они
        # вырезались из всего начала текста, и у страниц разных тем
        # оставалось одинаковое «начало».
        opening = content._opening(self.load("kazakhstan", "fees"))
        self.assertIn("visa", opening[:12])
        self.assertIn("kazakhstan", opening[:12])

    def test_the_h1_crumb_keeps_the_marker(self):
        opening = content._opening(self.load("algeria", "transit"))
        start = opening.index("every")
        self.assertEqual(opening[start:start + 3], ["every", "algeria", "visa"])


class WideCount(unittest.TestCase):
    def test_cjk_description_names_its_real_length(self):
        from indexgap import checks
        self.assertEqual(checks._wide_note("plain text", 10), "")
        self.assertIn("4", checks._wide_note("短期赴新", 8))



class UnderscoreCode(unittest.TestCase):
    def test_an_underscore_code_is_the_same_language(self):
        from indexgap import hreflang
        self.assertTrue(hreflang._same_language("de_DE", "de"))
        self.assertTrue(hreflang._same_language("de-DE", "de"))
        self.assertFalse(hreflang._same_language("uk", "de"))
        self.assertFalse(hreflang._same_language("", "de"))



class OtherDrive(unittest.TestCase):
    def test_config_on_another_windows_drive_does_not_crash(self):
        import contextlib
        import io
        from unittest import mock
        from indexgap import cli

        def relpath(*_a, **_k):
            raise ValueError("path is on mount 'C:', start on mount 'D:'")
        buf = io.StringIO()
        with mock.patch.object(cli.os.path, "relpath", relpath), contextlib.redirect_stdout(buf):
            cli._describe_project({"_path": "/elsewhere/indexgap.json", "lang": "en"}, [])
        self.assertIn("indexgap.json", buf.getvalue())



class IsoDateTime(unittest.TestCase):
    def test_iso_datetime_is_not_a_quantity(self):
        self.assertEqual(content._generic_numbers_in("Doors open 2027-02-20T09:00 sharp."), {})
        self.assertEqual(content._generic_numbers_in("Starts 2027-02-20T09:00:00Z online"), {})
        self.assertEqual(content._generic_numbers_in("Deposit 3 months"), {"3": "months"})


if __name__ == "__main__":
    unittest.main()
