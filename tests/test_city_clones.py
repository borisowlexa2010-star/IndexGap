# -*- coding: utf-8 -*-
"""
Город поменяли, остальное — то же: главное обещание пакета.

Ревьюер полноты собрал каталог, где у каждой страницы одинаковый текст в
340 слов, город и штат, блок фактов из пяти чисел и блок «соседние города».
Шестнадцать таких страниц выходили `similar` (сведения), а не
`near-duplicate`: подставленные значения узнавались по числу разных слов —
не больше шести или 4% словаря, — а факты и соседи давали двенадцать-пятнадцать.
Доля вхождений честнее: у клона разные слова занимают несколько процентов
текста, у действительно разных страниц — десятки.
"""

import os
import shutil
import tempfile
import unittest

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, core

SITE = "https://example.com"
BODY = ("Finding a reliable plumber in {city} does not have to be hard. Our directory lists "
        "licensed and insured professionals who serve every neighbourhood of {city}, {state}. "
        "Each listing shows verified reviews, typical response times and the services offered, "
        "from emergency leak repair to water heater installation and drain cleaning. Before you "
        "hire anyone in {city}, compare at least three quotes, ask about warranties on parts and "
        "labour, and check that the plumber holds a current state licence. Most jobs in {city} "
        "are priced either by the hour or as a flat fee; flat fees are common for routine work "
        "such as unclogging a sink, while larger projects are quoted after an inspection. ")
FACTS = ("<ul><li>Average price: ${price}</li><li>Plumbers listed: {pros}</li>"
         "<li>Rating: {rating} out of 5</li><li>Response time: {minutes} minutes</li>"
         "<li>Reviews: {reviews}</li></ul>")
NEAR = "<p>Nearby: <a href='/{a}/'>{A}</a>, <a href='/{b}/'>{B}</a>, <a href='/{c}/'>{C}</a></p>"
CITIES = [("Austin", "TX", 320, 58, 4.6, 25, 1801, ("Round Rock", "Cedar Park", "Pflugerville")),
          ("Boise", "ID", 290, 31, 4.4, 40, 712, ("Meridian", "Nampa", "Eagle")),
          ("Tulsa", "OK", 260, 44, 4.7, 30, 1240, ("Broken Arrow", "Owasso", "Jenks")),
          ("Omaha", "NE", 275, 39, 4.5, 35, 966, ("Bellevue", "Papillion", "La Vista"))]


def page(city, state, price, pros, rating, minutes, reviews, near):
    slug = lambda s: s.lower().replace(" ", "-")
    body = (BODY * 2).format(city=city, state=state)
    facts = FACTS.format(price=price, pros=pros, rating=rating, minutes=minutes, reviews=reviews)
    links = NEAR.format(a=slug(near[0]), b=slug(near[1]), c=slug(near[2]),
                        A=near[0], B=near[1], C=near[2])
    return (f"<!doctype html><html lang=\"en\"><head><title>Plumbers in {city}, {state}</title>"
            f"</head><body><main><h1>Plumbers in {city}</h1><p>{body}</p>{facts}{links}"
            "</main></body></html>")


class CityClones(unittest.TestCase):
    def build(self, cities, extra=None):
        root = tempfile.mkdtemp(prefix="indexgap-clones-")
        self.addCleanup(shutil.rmtree, root, True)
        for row in cities:
            path = os.path.join(root, row[0].lower(), "index.html")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(page(*row))
        for name, text in (extra or {}).items():
            path = os.path.join(root, name, "index.html")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return core.load_pages(root, SITE)[0]

    def test_city_swapped_pages_are_near_duplicates(self):
        pages = self.build(CITIES)
        dupes = checks.find_near_duplicates(pages, checks.CONFIG)["pairs"]
        near = [(a.url, b.url) for a, b, j in dupes if j >= checks.CONFIG["near_duplicate"]]
        self.assertEqual(len(near), 6, [(a.url, b.url, round(j, 2)) for a, b, j in dupes])

    def test_different_articles_that_share_a_template_are_not(self):
        texts = {
            "guide-a": "Copper pipes last for decades but cost more to install and need a "
                       "skilled plumber with soldering tools. ",
            "guide-b": "Tankless water heaters save space and energy, yet they demand a gas "
                       "line upgrade and yearly descaling in hard water areas. ",
        }
        extra = {}
        for name, text in texts.items():
            words = text * 3 + " ".join(f"{name}-detail-{i}" for i in range(120))
            extra[name] = ("<!doctype html><html lang=\"en\"><head><title>" + name + "</title>"
                           "</head><body><main><h1>" + name + "</h1><p>"
                           + (BODY.format(city="your town", state="your state") * 0) + words
                           + "</p></main></body></html>")
        pages = self.build([], extra)
        dupes = checks.find_near_duplicates(pages, checks.CONFIG)["pairs"]
        self.assertEqual([j for _a, _b, j in dupes if j >= checks.CONFIG["near_duplicate"]], [])


if __name__ == "__main__":
    unittest.main()
