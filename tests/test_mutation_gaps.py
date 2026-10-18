# -*- coding: utf-8 -*-
"""
Поведение, которое не держал ни один тест: каждый класс ниже убивает мутанты,
пережившие весь набор (ручной мутационный прогон, октябрь 2026).
"""

import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import checks, content, core, doctor, hreflang, publish

SITE = "https://example.com"


def page(url, text="слово " * 300, **kw):
    path = kw.pop("path", url.replace(SITE, "/site") + "index.html")
    return core.Page(path=path, url=url, text=text, **kw)


class OutDir(unittest.TestCase):
    def out(self):
        d = tempfile.mkdtemp(prefix="indexgap-mut-")
        self.addCleanup(shutil.rmtree, d, True)
        return d


# ── publish: lastmod, манифест, шарды ─────────────────────────────────────────

class TestLastmodFollowsTheText(OutDir):
    def test_changed_text_gets_todays_lastmod(self):
        p = page(f"{SITE}/a/")
        old = {p.url: {"hash": "0000000000000000", "lastmod": "2026-01-01"}}
        result = publish.build_sitemap([p], self.out(), SITE, manifest=old, today="2026-10-01")
        self.assertEqual(result["manifest"][p.url]["lastmod"], "2026-10-01")
        self.assertEqual(result["manifest"][p.url]["hash"], p.content_hash)

    def test_unchanged_text_keeps_its_lastmod(self):
        p = page(f"{SITE}/a/")
        old = {p.url: {"hash": p.content_hash, "lastmod": "2026-01-01"}}
        result = publish.build_sitemap([p], self.out(), SITE, manifest=old, today="2026-10-01")
        self.assertEqual(result["manifest"][p.url]["lastmod"], "2026-01-01")

    def test_excluded_counts_pages_left_out(self):
        pages = [page(f"{SITE}/a/"), page(f"{SITE}/b/", robots="noindex")]
        result = publish.build_sitemap(pages, self.out(), SITE, today="2026-10-01")
        self.assertEqual((result["included"], result["excluded"]), (1, 1))


class TestMissingSince(OutDir):
    def build(self, pages, manifest):
        return publish.build_sitemap(pages, self.out(), SITE, manifest=manifest,
                                     today="2026-10-01")["manifest"]

    def test_a_live_closed_page_is_not_counted_as_missing(self):
        closed = page(f"{SITE}/closed/", robots="noindex")
        manifest = self.build([closed], {closed.url: {"notified": "x",
                                                      "missing_since": "2020-01-01"}})
        self.assertEqual(manifest[closed.url], {"notified": "x"})

    def test_a_returning_page_forgets_when_it_went_missing(self):
        back = page(f"{SITE}/back/", "текст вернувшейся страницы " * 30)
        manifest = self.build([back], {back.url: {"hash": "old", "lastmod": "2026-08-01",
                                                  "missing_since": "2026-08-01"}})
        self.assertNotIn("missing_since", manifest[back.url])

    def test_thirty_days_is_kept_thirty_one_is_pruned(self):
        manifest = self.build([], {f"{SITE}/kept/": {"missing_since": "2026-09-01"},
                                   f"{SITE}/gone/": {"missing_since": "2026-08-31"}})
        self.assertIn(f"{SITE}/kept/", manifest)
        self.assertNotIn(f"{SITE}/gone/", manifest)


class TestShardedSitemap(OutDir):
    def setUp(self):
        saved = publish.MAX_URLS_PER_FILE
        publish.MAX_URLS_PER_FILE = 2
        self.addCleanup(setattr, publish, "MAX_URLS_PER_FILE", saved)

    def pages_with_dates(self):
        pages = [page(f"{SITE}/p{i}/", f"текст номер {i} " * 50) for i in range(3)]
        dates = ["2026-03-01", "2026-05-01", "2026-04-01"]
        manifest = {p.url: {"hash": p.content_hash, "lastmod": d} for p, d in zip(pages, dates)}
        return pages, manifest

    def test_exactly_the_limit_is_one_file(self):
        out = self.out()
        result = publish.build_sitemap([page(f"{SITE}/a/"), page(f"{SITE}/b/")], out, SITE)
        self.assertEqual([os.path.basename(f) for f in result["files"]], ["sitemap.xml"])

    def test_index_lists_every_shard_with_its_newest_date(self):
        out = self.out()
        pages, manifest = self.pages_with_dates()
        result = publish.build_sitemap(pages, out, SITE, manifest=manifest, today="2026-10-01")
        with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
            index = fh.read()
        self.assertEqual(re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", index),
                         [(f"{SITE}/sitemap-1.xml", "2026-05-01"),
                          (f"{SITE}/sitemap-2.xml", "2026-04-01")])
        self.assertTrue(index.rstrip().endswith("</sitemapindex>"))
        self.assertEqual(sorted(os.listdir(out)), ["sitemap-1.xml", "sitemap-2.xml", "sitemap.xml"])
        self.assertEqual(result["manifest"]["_shards"],
                         ["sitemap-1.xml", "sitemap-2.xml", "sitemap.xml"])

    def test_rebuild_keeps_the_shards_it_just_wrote(self):
        out = self.out()
        pages, manifest = self.pages_with_dates()
        first = publish.build_sitemap(pages, out, SITE, manifest=manifest)
        second = publish.build_sitemap(pages, out, SITE, manifest=first["manifest"])
        self.assertEqual(second["removed"], [])
        self.assertTrue(os.path.exists(os.path.join(out, "sitemap-1.xml")))
        self.assertTrue(os.path.exists(os.path.join(out, "sitemap-2.xml")))
        self.assertEqual(publish.foreign_sitemap(out, second["manifest"]), "")


class TestLimitsOfTheProtocol(unittest.TestCase):
    def test_limits_stay_inside_the_protocol(self):
        self.assertLessEqual(publish.MAX_URLS_PER_FILE, 50000)
        self.assertLessEqual(publish.INDEXNOW_BATCH, 10000)

    def test_dry_run_reports_every_batch_with_a_sample(self):
        urls = [f"{SITE}/p{i}/" for i in range(10001)]
        out = publish.submit_indexnow(urls, SITE, "k" * 32, dry_run=True)
        self.assertEqual([r["batch"] for r in out["results"]], [10000, 1])
        self.assertEqual(out["results"][0]["sample"], urls[:3])
        self.assertEqual((out["accepted"], out["pending"]), ([], False))


# ── publish: что считается изменившимся и что уходит в IndexNow ───────────────

class TestDiffChanged(unittest.TestCase):
    def test_changed_text_is_in_the_queue(self):
        p = page(f"{SITE}/a/")
        diff = publish.diff_changed([p], {p.url: {"notified": "0000000000000000"}})
        self.assertEqual((diff["new"], diff["changed"], diff["unchanged"]), ([], [p.url], []))

    def test_unknown_url_is_not_marked(self):
        p = page(f"{SITE}/a/")
        manifest = publish.mark_notified({}, [p], [f"{SITE}/gone/", p.url])
        self.assertEqual(manifest, {p.url: {"notified": p.content_hash}})


class TestIsDraft(unittest.TestCase):
    def draft(self, value):
        return publish.is_draft(page(f"{SITE}/a/", meta={"publishDate": value}), today="2026-10-01")

    def test_future_publish_date_with_time_is_a_draft(self):
        self.assertTrue(self.draft("2026-12-01T09:00:00+03:00"))

    def test_publish_date_today_is_published(self):
        self.assertFalse(self.draft("2026-10-01"))

    def test_a_publish_date_that_is_not_a_date_is_ignored(self):
        self.assertFalse(self.draft("soon"))


class TestIndexNowAnswers(unittest.TestCase):
    def submit(self, status, urls=(f"{SITE}/a/", f"{SITE}/b/"), key_location=None):
        import urllib.error
        calls = []

        class Opener:
            def open(self, request, timeout=None):
                import json
                calls.append(json.loads(request.data))
                if status >= 300:
                    raise urllib.error.HTTPError(request.full_url, status, "x", {}, None)
                response = mock.MagicMock()
                response.status = status
                response.__enter__.return_value = response
                return response

        saved = publish.INDEXNOW_BATCH
        publish.INDEXNOW_BATCH = 1
        try:
            with mock.patch("urllib.request.build_opener", lambda *a: Opener()):
                out = publish.submit_indexnow(list(urls), SITE, "k" * 32, key_location,
                                              dry_run=False)
        finally:
            publish.INDEXNOW_BATCH = saved
        return out, calls

    def test_200_is_accepted_and_not_pending(self):
        out, calls = self.submit(200)
        self.assertEqual(out["accepted"], [f"{SITE}/a/", f"{SITE}/b/"])
        self.assertFalse(out["pending"])
        self.assertEqual([r["status"] for r in out["results"]], [200, 200])
        self.assertNotIn("error", out["results"][0])
        self.assertEqual(calls[0]["keyLocation"], f"{SITE}/{'k' * 32}.txt")
        self.assertEqual(calls[0]["host"], "example.com")

    def test_fatal_answers_stop_after_the_first_batch(self):
        for status in (300, 307, 400, 403, 422, 429, 500, 503):
            out, calls = self.submit(status)
            self.assertEqual(len(calls), 1, status)
            self.assertEqual([r["status"] for r in out["results"]], [status, "stopped"], status)
            self.assertEqual(out["results"][1]["batch"], 0)
            self.assertTrue(out["results"][0]["error"], status)

    def test_other_errors_do_not_stop_the_queue(self):
        for status in (401, 404, 410, 499):
            out, calls = self.submit(status)
            self.assertEqual(len(calls), 2, status)
            self.assertEqual(out["accepted"], [], status)


# ── hreflang ──────────────────────────────────────────────────────────────────

def version(lang, path, cluster, **kw):
    """Страница `SITE + path` на языке `lang`, объявляющая `cluster` [(код, путь)]."""
    return page(SITE + path, lang=lang,
                alternates=[(c, SITE + h if h else "") for c, h in cluster], **kw)


def pair(en=None, de=None):
    cluster = [("en", "/en/"), ("de", "/de/")]
    return [version("en", "/en/", en or cluster), version("de", "/de/", de or cluster)]


def found(pages):
    return {(i[1].replace(SITE, ""), i[2]): i[0] for i in hreflang.check(pages)["issues"]}


class TestHreflangVerdicts(unittest.TestCase):
    def test_each_finding_has_its_level(self):
        self.assertEqual(found(pair(de=[("en", "/en/")]))[("/de/", "hreflang-no-self")], "critical")
        self.assertEqual(found(pair(de=[("de", "/de/")]))[("/en/", "hreflang-no-return")], "critical")
        conflict = pair()
        conflict[1].canonical = SITE + "/en/"
        self.assertEqual(found(conflict)[("/de/", "hreflang-canonical-conflict")], "critical")
        blocked = pair()
        blocked[1].robots = "noindex"
        self.assertEqual(found(blocked)[("/en/", "hreflang-target-blocked")], "warning")
        unknown = pair(en=[("en", "/en/"), ("de", "/de/"), ("fr", "/fr/")])
        self.assertEqual(found(unknown)[("/en/", "hreflang-unknown-target")], "info")
        missing = pair() + [page(SITE + "/en/a/", lang="en", alternates=[]),
                            page(SITE + "/de/a/", lang="de", alternates=[])]
        self.assertEqual(found(missing)[("/en/a/", "hreflang-missing")], "warning")
        static = [version("en" if i % 2 else "ru", f"/p{i}/", [("en", "/"), ("ru", "/?lang=ru")])
                  for i in range(20)]
        self.assertEqual(found(static)[("", "hreflang-static-cluster")], "critical")

    def test_check_tag_names_the_right_code(self):
        self.assertEqual(hreflang.check_tag("uk"), "")
        self.assertEqual(hreflang.check_tag("uk-UA"), "")
        self.assertIn("en-GB", hreflang.check_tag("gb"))
        self.assertIn("ja", hreflang.check_tag("jp"))
        self.assertIn("en-GB", hreflang.check_tag("en-UK"))
        self.assertNotIn("вероятно", hreflang.check_tag("en-EU"))

    def test_regional_pairs_use_the_self_declared_code(self):
        cluster = [("de", "/de/"), ("en-US", "/us/"), ("en-GB", "/gb/")]
        pages = [version("de", "/de/", cluster), version("en", "/us/", cluster),
                 version("en", "/gb/", cluster)]
        result = hreflang.check(pages)
        self.assertEqual(result["regional_pairs"], [(SITE + "/gb/", SITE + "/us/")])
        self.assertTrue(any(n.startswith("региональных пар (один язык, разные страны): 1")
                            for n in result["notes"]), result["notes"])
        self.assertIn("языков на сайте: 2 (de, en).", " ".join(result["notes"]))

    def test_without_a_self_link_the_page_language_decides_the_region(self):
        cluster = [("en-US", "/us/"), ("en-GB", "/gb/")]
        pages = [version("en-US", "/us/", cluster),
                 version("en-GB", "/gb/", [("en-US", "/us/")])]
        self.assertEqual(hreflang.check(pages)["regional_pairs"], [(SITE + "/gb/", SITE + "/us/")])

    def test_a_bad_code_is_reported(self):
        issues = found(pair(en=[("en-UK", "/en/"), ("de", "/de/")]))
        self.assertEqual(issues[("/en/", "hreflang-bad-code")], "warning")

    def test_an_empty_href_is_reported_and_skipped(self):
        result = hreflang.check(pair(en=[("en", "/en/"), ("de", "/de/"), ("fr", "")]))
        empty = [i for i in result["issues"] if i[2] == "hreflang-bad-code"]
        self.assertEqual([(i[0], i[1]) for i in empty], [("warning", SITE + "/en/")])
        self.assertIn("пустой href", empty[0][3])
        self.assertNotIn("hreflang-unknown-target", [i[2] for i in result["issues"]])

    def test_self_reference_of_a_closed_page_is_not_a_blocked_target(self):
        pages = pair()
        pages[1].robots = "noindex"
        self.assertNotIn(("/de/", "hreflang-target-blocked"), found(pages))

    def test_self_canonical_and_same_language_canonical_are_not_conflicts(self):
        pages = pair()
        pages[0].canonical = SITE + "/en/"
        self.assertNotIn(("/en/", "hreflang-canonical-conflict"), found(pages))

    def test_self_code_must_match_the_page_language(self):
        pages = pair(de=[("en", "/en/"), ("fr", "/de/")])
        self.assertEqual(found(pages)[("/de/", "hreflang-lang-mismatch")], "warning")
        pages = pair(de=[("en", "/en/"), ("x-default", "/de/"), ("de-AT", "/de/")])
        self.assertNotIn(("/de/", "hreflang-lang-mismatch"), found(pages))

    def test_x_default_note(self):
        notes = " ".join(hreflang.check(pair())["notes"])
        self.assertIn("x-default", notes)
        self.assertNotIn("региональных пар", notes)
        with_default = pair(en=[("en", "/en/"), ("de", "/de/"), ("x-default", "/en/")])
        self.assertNotIn("x-default", " ".join(hreflang.check(with_default)["notes"]))

    def test_a_closed_counterpart_does_not_demand_hreflang(self):
        pages = pair() + [page(SITE + "/en/a/", lang="en", alternates=[]),
                          page(SITE + "/de/a/", lang="de", alternates=[], robots="noindex")]
        self.assertNotIn(("/en/a/", "hreflang-missing"), found(pages))

    def test_lonely_pages_are_counted_in_the_note(self):
        pages = pair() + [page(SITE + f"/en/only{i}/", lang="en", alternates=[]) for i in range(3)]
        notes = hreflang.check(pages)["notes"]
        self.assertTrue(any(n.startswith("3 открыт") for n in notes), notes)
        self.assertFalse(any("открыт(ых) страниц без hreflang" in n
                             for n in hreflang.check(pair())["notes"]))


class TestStaticClusterBounds(unittest.TestCase):
    """n страниц; `shared` из них объявляют один набор S, `inside` из них в S входят."""

    def site(self, n, shared, inside=0):
        pages = []
        s_paths = [f"/p{i}/" for i in range(inside)] or ["/", "/?lang=ru"]
        if inside:
            s_paths = s_paths + ["/?lang=ru"]
        for i in range(n):
            lang = "en" if i % 2 else "ru"
            if i < shared:
                cluster = [(f"x{j}", p) for j, p in enumerate(s_paths)]
            else:
                cluster = [(lang, f"/p{i}/"), ("de", f"/de/p{i}/"), ("fr", f"/fr/p{i}/")]
            pages.append(version(lang, f"/p{i}/", cluster))
        return [i[2] for i in hreflang.check(pages)["issues"]]

    def test_ninety_percent_of_twenty_pages_is_a_static_cluster(self):
        codes = self.site(20, 18)
        self.assertEqual(codes.count("hreflang-static-cluster"), 1)

    def test_eighty_five_percent_is_not(self):
        self.assertNotIn("hreflang-static-cluster", self.site(20, 17))

    def test_ninety_percent_orphaned_is_a_static_cluster(self):
        self.assertIn("hreflang-static-cluster", self.site(20, 20, inside=2))

    def test_eighty_five_percent_orphaned_is_not(self):
        self.assertNotIn("hreflang-static-cluster", self.site(20, 20, inside=3))

    def test_a_full_cluster_on_every_page_is_not_static(self):
        """Двадцать языковых версий, и каждая объявляет все двадцать — это верно."""
        langs = sorted(hreflang.LANGUAGES)[:20]
        cluster = [(lang, f"/{lang}/") for lang in langs]
        pages = [version(lang, f"/{lang}/", cluster) for lang in langs]
        self.assertNotIn("hreflang-static-cluster", [i[2] for i in hreflang.check(pages)["issues"]])


class TestIsMultilingualBounds(unittest.TestCase):
    def test_one_page_with_alternates_is_not_a_multilingual_site(self):
        pages = [page(f"{SITE}/a/", alternates=[("en", f"{SITE}/a/")]),
                 page(f"{SITE}/b/", alternates=[])]
        self.assertFalse(hreflang.is_multilingual(pages))

    def test_regions_of_one_language_are_one_language(self):
        pages = [page(f"{SITE}/a/", lang="en-US", alternates=[]),
                 page(f"{SITE}/b/", lang="en-GB", alternates=[])]
        self.assertFalse(hreflang.is_multilingual(pages))

    def test_two_paths_under_two_prefixes_are_enough(self):
        pages = [page(f"{SITE}/{lang}/{p}/", alternates=[]) for lang in ("en", "de")
                 for p in ("a", "b")]
        self.assertTrue(hreflang.is_multilingual(pages))
        self.assertFalse(hreflang.is_multilingual(pages[:1] + pages[2:3]))

    def test_one_prefix_is_not_a_second_language(self):
        pages = [page(f"{SITE}/en/{p}/", alternates=[]) for p in ("a", "b", "c")]
        self.assertFalse(hreflang.is_multilingual(pages))

    def test_alternates_are_read_from_raw_html_when_not_collected(self):
        raw = ('<html><head><link rel="alternate" type="application/rss+xml" href="/feed">'
               '<link rel="alternate" hreflang="de" href="/de/">'
               '<link rel="canonical" href="/en/"></head>'
               '<body><a rel="alternate" hreflang="fr" href="/fr/">fr</a></body></html>')
        p = page(f"{SITE}/en/", raw=raw)
        self.assertEqual(hreflang.read_alternates(p), [("de", "/de/")])
        self.assertEqual(hreflang.read_alternates(page(f"{SITE}/x/", raw="<p>alternate</p>")), [])


# ── checks: пороги CONFIG и почти-дубли ───────────────────────────────────────

def words(prefix, n, start=0):
    return [f"{prefix}{i}" for i in range(start, start + n)]


def twins(shared, differ, lang=""):
    """Две страницы: общий префикс из `shared` слов и по `differ` своих слов в хвосте.
    При шингле 5 их Jaccard = (shared-4) / (shared-4 + 2*differ)."""
    common = words("общ", shared)
    a = page(f"{SITE}/a/", " ".join(common + words("левый", differ)), lang=lang)
    b = page(f"{SITE}/b/", " ".join(common + words("правый", differ)), lang=lang)
    return [a, b]


def similarity(pages, cfg=None):
    pairs = checks.find_near_duplicates(pages, cfg)["pairs"]
    return [round(j, 4) for _, _, j in pairs]


class TestDuplicateThresholds(unittest.TestCase):
    def test_exactly_the_near_duplicate_threshold(self):
        self.assertEqual(similarity(twins(60, 7)), [0.8])           # 56 / 70
        result = checks.run_all(twins(60, 7))
        self.assertIn("near-duplicate", [i[2] for i in result["issues"]])

    def test_just_below_the_near_duplicate_threshold_is_similar(self):
        self.assertEqual(similarity(twins(59, 7)), [0.797])         # 55 / 69
        codes = [i[2] for i in checks.run_all(twins(59, 7))["issues"]]
        self.assertIn("similar", codes)
        self.assertNotIn("near-duplicate", codes)
        self.assertEqual(similarity(twins(64, 8)), [0.789])         # 60 / 76

    def test_exactly_the_similar_threshold(self):
        self.assertEqual(similarity(twins(26, 9)), [0.55])          # 22 / 40
        self.assertEqual(similarity(twins(26, 10)), [])             # 22 / 42

    def test_one_substituted_word_does_not_inflate_a_high_score(self):
        """0.8 без подстановки — это 0.8, а не 1.0: проверка слотов только ниже порога."""
        self.assertEqual(similarity(twins(12, 1)), [0.8])            # 8 / 10


class TestTemplateSlots(unittest.TestCase):
    def slotted(self, length, slots):
        """Одинаковый текст, в котором `slots` разных слов стоят каждое в своём месте."""
        base = words("текст", length)
        a, b = list(base), list(base)
        for n in range(slots):
            pos = 3 + n * (length // (slots + 1))
            a[pos], b[pos] = f"город{n}", f"село{n}"
        return [page(f"{SITE}/a/", " ".join(a)), page(f"{SITE}/b/", " ".join(b))]

    def test_six_slots_on_a_short_page_are_one_text(self):
        self.assertEqual(similarity(self.slotted(60, 6)), [1.0])

    def test_seven_slots_on_a_short_page_are_different_texts(self):
        j = similarity(self.slotted(60, 7))
        self.assertTrue(not j or j[0] < 0.8, j)

    def test_on_a_long_page_the_share_decides(self):
        """300 слов: предел — 4% от длины, то есть 12 подстановок."""
        self.assertEqual(similarity(self.slotted(300, 12)), [1.0])
        j = similarity(self.slotted(300, 13))
        self.assertTrue(not j or j[0] < 0.8, j)

    def test_dense_script_uses_double_shingles(self):
        han = [chr(0x4E00 + i) for i in range(400)]
        common = han[:30]
        a = page(f"{SITE}/a/", "".join(common + han[100:110]))
        b = page(f"{SITE}/b/", "".join(common + han[200:210]))
        # шингл 10 знаков: 21 / 41 — ниже «похожих»; шингл 5 дал бы 26 / 46.
        self.assertEqual(similarity([a, b]), [])
        a = page(f"{SITE}/a/", "".join(han[:60] + han[100:107]))
        b = page(f"{SITE}/b/", "".join(han[:60] + han[200:207]))
        self.assertEqual(similarity([a, b]), [0.785])                # 51 / 65


class TestLshPath(unittest.TestCase):
    def test_method_switches_after_exact_below(self):
        pages = [page(f"{SITE}/p{i}/", " ".join(words(f"т{i}x", 12))) for i in range(401)]
        self.assertEqual(checks.find_near_duplicates(pages)["method"], "LSH")
        self.assertEqual(checks.find_near_duplicates(pages[:400])["method"], "попарное сравнение")

    def test_lsh_finds_the_same_twins_as_the_exact_method(self):
        pages = []
        for n in range(220):
            common = words(f"тема{n}x", 60)                 # Jaccard пары — 0.8
            pages.append(page(f"{SITE}/t{n}a/", " ".join(common + words(f"л{n}x", 7))))
            pages.append(page(f"{SITE}/t{n}b/", " ".join(common + words(f"п{n}x", 7))))
        lsh = checks.find_near_duplicates(pages)
        exact = checks.find_near_duplicates(pages, {"exact_below": 1000})
        self.assertEqual(lsh["method"], "LSH")
        key = lambda r: sorted((a.url, b.url, j) for a, b, j in r["pairs"])
        self.assertGreaterEqual(len(key(lsh)), 0.95 * len(key(exact)))
        self.assertTrue(set(key(lsh)) <= set(key(exact)))
        self.assertFalse([a for a, b, _ in lsh["pairs"] if a is b])

    def test_a_full_bucket_is_compared_pairwise_and_a_bigger_one_against_a_sample(self):
        body = " ".join(words("одинаково", 40))
        full = [page(f"{SITE}/p{i:03}/", body) for i in range(200)]
        result = checks.find_near_duplicates(full, {"exact_below": 50})
        self.assertEqual(len(result["pairs"]), 200 * 199 // 2)
        self.assertEqual(result["notes"], [])
        bigger = full + [page(f"{SITE}/p200/", body)]
        result = checks.find_near_duplicates(bigger, {"exact_below": 50})
        self.assertEqual(len(result["pairs"]), 200)
        self.assertIn("сравнивались с образцом", result["notes"][0])


class TestTechnicalThresholds(unittest.TestCase):
    def codes(self, **kw):
        p = page(f"{SITE}/a/", **kw)
        return {i[2]: i[0] for i in checks.technical_issues([p])}

    def test_title_bounds(self):
        self.assertNotIn("title-short", self.codes(title="t" * 20))
        self.assertEqual(self.codes(title="t" * 19)["title-short"], "warning")
        self.assertNotIn("title-long", self.codes(title="t" * 65))
        self.assertEqual(self.codes(title="t" * 66)["title-long"], "info")

    def test_description_bounds(self):
        for n in (70, 165):
            self.assertNotIn("description-length", self.codes(title="t" * 30, description="d" * n), n)
        for n in (69, 166):
            self.assertEqual(self.codes(title="t" * 30, description="d" * n)["description-length"],
                             "info", n)

    def test_thin_bound(self):
        self.assertNotIn("thin", self.codes(text=" ".join(words("с", 250))))
        self.assertEqual(self.codes(text=" ".join(words("с", 249)))["thin"], "warning")

    def test_levels_of_page_findings(self):
        codes = self.codes(robots="noindex, nosnippet", canonical=SITE + "/b/")
        self.assertEqual((codes["noindex"], codes["nosnippet"], codes["no-title"],
                          codes["no-description"], codes["no-headings"]),
                         ("critical", "critical", "critical", "warning", "warning"))
        # noindex и canonical на одной странице — одно решение, одна находка.
        self.assertNotIn("canonical-elsewhere", codes)
        self.assertEqual(self.codes(canonical=SITE + "/b/")["canonical-elsewhere"], "critical")
        self.assertEqual(self.codes(headings=[(2, "x")])["no-h1"], "warning")
        self.assertEqual(self.codes(headings=[(1, "x"), (1, "y")])["many-h1"], "info")

    def test_duplicate_titles_and_descriptions(self):
        pages = [page(f"{SITE}/{n}/", title="Один и тот же заголовок страницы",
                      description="Одно и то же описание") for n in "ab"]
        issues = [i for i in checks.technical_issues(pages) if i[2].startswith("duplicate-")]
        self.assertEqual(sorted((i[0], i[1], i[2]) for i in issues),
                         [("info", SITE + "/a/", "duplicate-description"),
                          ("info", SITE + "/b/", "duplicate-description"),
                          ("warning", SITE + "/a/", "duplicate-title"),
                          ("warning", SITE + "/b/", "duplicate-title")])
        self.assertTrue(all("ещё у 1 страниц" in i[3] for i in issues), issues)

    def test_pages_without_a_title_are_not_duplicates_of_each_other(self):
        pages = [page(f"{SITE}/{n}/") for n in "ab"]
        codes = [i[2] for i in checks.technical_issues(pages)]
        self.assertNotIn("duplicate-title", codes)
        self.assertNotIn("duplicate-description", codes)

    def test_source_notes_are_warnings(self):
        codes = self.codes(notes=["битый фронтматтер"])
        self.assertEqual(codes["source-note"], "warning")


class TestClickDepth(unittest.TestCase):
    def test_three_clicks_is_fine_four_is_deep(self):
        chain = ["", "a", "b", "c", "d"]
        pages = [page(f"{SITE}/{name}/" if name else f"{SITE}/",
                      links=[f"{SITE}/{chain[i + 1]}/"] if i + 1 < len(chain) else [])
                 for i, name in enumerate(chain)]
        deep = [i for i in checks.run_all(pages, SITE + "/")["issues"] if i[2] == "deep"]
        self.assertEqual([(i[0], i[1]) for i in deep], [("warning", SITE + "/d/")])


class TestSlotFloor(unittest.TestCase):
    def test_below_the_floor_a_pair_is_not_rechecked(self):
        """Одно подставленное слово 11 раз: сходство 45/155 = 0.29 — ниже 0.30."""
        base = words("текст", 104)
        a, b = list(base), list(base)
        for n in range(11):
            a[4 + n * 9], b[4 + n * 9] = "москва", "казань"
        self.assertEqual(similarity([page(f"{SITE}/a/", " ".join(a)),
                                     page(f"{SITE}/b/", " ".join(b))]), [])


class TestBoilerplateShares(unittest.TestCase):
    def cohort(self, n, build, lang="ru"):
        return [page(f"{SITE}/{lang}/p{i}/", " ".join(build(i)), lang=lang, chrome="меню")
                for i in range(n)]

    def test_the_ninety_percent_bigram_is_template_and_eighty_five_is_not(self):
        def build(i):
            return ((["x", "y"] if i < 18 else [f"p{i}", f"q{i}"])
                    + (["z", "w"] if i < 17 else [f"r{i}", f"s{i}"]) + words(f"u{i}x", 3))
        shares = checks.boilerplate_profile(self.cohort(20, build))["shares"]
        self.assertEqual(shares[f"{SITE}/ru/p0/"], round(5 / 6, 3))

    def test_eight_pages_are_enough_seven_are_not(self):
        build = lambda i: ["общий", "текст"] + words(f"u{i}x", 3)
        eight = checks.boilerplate_profile(self.cohort(8, build))
        self.assertEqual((len(eight["shares"]), eight["skipped"]), (8, ""))
        self.assertEqual(eight["shares"][f"{SITE}/ru/p0/"], 0.75)
        self.assertEqual(checks.boilerplate_profile(self.cohort(7, build))["shares"], {})

    def test_a_small_language_is_named_not_judged(self):
        build = lambda i: ["общий", "текст"] + words(f"u{i}x", 3)
        pages = self.cohort(10, build) + self.cohort(3, build, lang="en")
        result = checks.boilerplate_profile(pages)
        self.assertEqual(sorted(result["shares"]), sorted(p.url for p in pages[:10]))
        self.assertTrue(result["skipped"].startswith("у 3 страниц"), result["skipped"])

    def test_language_regions_share_a_template(self):
        build = lambda i: ["общий", "текст"] + words(f"u{i}x", 3)
        pages = self.cohort(4, build, lang="ru") + [
            page(f"{SITE}/ru/q{i}/", " ".join(build(i + 10)), lang="ru-RU", chrome="меню")
            for i in range(4)]
        self.assertEqual(len(checks.boilerplate_profile(pages)["shares"]), 8)

    def test_low_uniqueness_bound(self):
        def site(common):
            return [page(f"{SITE}/p{i}/", " ".join(words("шаблон", common) + words(f"u{i}x", 10)),
                         chrome="меню") for i in range(10)]
        codes = lambda pages: [i[2] for i in checks.run_all(pages)["issues"]]
        self.assertNotIn("low-uniqueness", codes(site(31)))         # 10 / 40 = 0.25
        self.assertIn("low-uniqueness", codes(site(41)))            # 10 / 50 = 0.20
        levels = {i[0] for i in checks.run_all(site(41))["issues"] if i[2] == "low-uniqueness"}
        self.assertEqual(levels, {"critical"})


class TestTrimmedWords(unittest.TestCase):
    HEAD, TAIL = ["меню", "главная", "каталог", "контакты"], ["подвал", "права", "год"]

    def site(self, n=10, head=True, tail=True, body=20):
        return [page(f"{SITE}/p{i}/", " ".join((self.HEAD if head else [f"h{i}"])
                                               + words(f"т{i}x", body)
                                               + (self.TAIL if tail else [f"e{i}"])))
                for i in range(n)]

    def test_shared_head_and_tail_are_cut(self):
        pages = self.site()
        pages[9].text = "другое " + pages[9].text.split(" ", 1)[1]
        pages[1].text = pages[1].text.replace("т1x0", "т0x0")
        trimmed = checks.trimmed_words(pages)
        self.assertEqual(trimmed[pages[0].url], words("т0x", 20))
        self.assertEqual(trimmed[pages[9].url][:4], ["другое", "главная", "каталог", "контакты"])
        self.assertEqual(trimmed[pages[9].url][-1], "т9x19")

    def test_only_a_tail(self):
        trimmed = checks.trimmed_words(self.site(head=False))
        self.assertEqual(trimmed[f"{SITE}/p0/"], ["h0"] + words("т0x", 20))

    def test_three_plain_pages_are_enough_two_are_not(self):
        self.assertEqual(checks.trimmed_words(self.site(3))[f"{SITE}/p0/"], words("т0x", 20))
        self.assertEqual(len(checks.trimmed_words(self.site(2))[f"{SITE}/p0/"]), 27)

    def test_identical_pages_lose_at_most_half(self):
        pages = [page(f"{SITE}/p{i}/", " ".join(words("слово", 21))) for i in range(10)]
        self.assertEqual(checks.trimmed_words(pages)[f"{SITE}/p0/"], words("слово", 11, 10))

    def test_one_short_page_does_not_set_the_budget(self):
        pages = self.site()
        pages[0].text = " ".join(self.HEAD + ["коротко"] + self.TAIL)
        self.assertEqual(checks.trimmed_words(pages)[f"{SITE}/p1/"], words("т1x", 20))


class TestShellAndParked(unittest.TestCase):
    def test_three_scripts_make_a_shell_two_do_not(self):
        shell = lambda n: page(f"{SITE}/a/", " ".join(words("с", 10)), blocks={"script": n})
        self.assertTrue(checks.is_shell(shell(3)))
        self.assertFalse(checks.is_shell(shell(2)))

    def test_five_parked_translations_are_a_rule_four_are_not(self):
        def parked(n):
            return [page(f"{SITE}/de/p{i}/", robots="noindex", canonical=f"{SITE}/en/p{i}/")
                    for i in range(n)]
        self.assertEqual(len(checks.parked_translations(parked(5))), 5)
        self.assertEqual(checks.parked_translations(parked(4)), {})


class TestRedirectStubs(unittest.TestCase):
    def target(self, raw, text=""):
        return checks.redirect_target(page(f"{SITE}/a/", text, raw=raw))

    def test_next_redirect_in_a_page_with_text_is_not_a_stub(self):
        raw = '<script>self.__next_f.push("NEXT_REDIRECT;replace;/en;307")</script>'
        self.assertEqual(self.target(raw, " ".join(words("с", 30))), "")
        self.assertEqual(self.target(raw, " ".join(words("с", 29))), f"{SITE}/en")

    def test_the_rsc_script_need_not_be_the_first(self):
        raw = ('<script>gtag("js")</script>'
               '<script>self.__next_f.push("NEXT_REDIRECT;push;/ru;308")</script>')
        self.assertEqual(self.target(raw), f"{SITE}/ru")

    def test_meta_refresh_in_capitals_and_delay_bound(self):
        self.assertEqual(self.target('<META HTTP-EQUIV="REFRESH" CONTENT="0; URL=/x/">'), f"{SITE}/x/")
        self.assertEqual(self.target('<meta Http-Equiv="Refresh" content="1;url=/y/">'), f"{SITE}/y/")
        self.assertEqual(self.target('<meta http-equiv="refresh" content="2; url=/z/">'), "")


class TestSelfHreflangIsNotInbound(unittest.TestCase):
    def test_a_page_that_names_only_itself_is_still_an_orphan(self):
        pages = [page(f"{SITE}/", links=[]),
                 page(f"{SITE}/a/", alternates=[("ru", f"{SITE}/a/")])]
        self.assertEqual(checks.link_graph(pages, SITE + "/")["orphans"], [f"{SITE}/a/"])


class TestShellBounds(unittest.TestCase):
    def shell(self, volume, scripts=3, raw="", **kw):
        return checks.is_shell(page(f"{SITE}/a/", " ".join(words("с", volume)), raw=raw,
                                    blocks={"script": scripts}, **kw))

    def test_volume_bound(self):
        self.assertFalse(self.shell(25))
        self.assertTrue(self.shell(24))

    def test_an_empty_mount_needs_one_script(self):
        mount = '<div id="root"></div>'
        self.assertTrue(self.shell(10, scripts=1, raw=mount))
        self.assertFalse(self.shell(10, scripts=0, raw=mount))
        self.assertFalse(self.shell(10, scripts=1))

    def test_headings_or_rendered_menu_mean_static(self):
        self.assertFalse(self.shell(10, headings=[(2, "Раздел")]))
        self.assertFalse(self.shell(10, chrome=" ".join(words("меню", 10))))
        self.assertTrue(self.shell(10, chrome=" ".join(words("меню", 9))))

    def test_almost_no_text_and_one_script(self):
        self.assertTrue(self.shell(4, scripts=1))
        self.assertFalse(self.shell(5, scripts=1))

    def test_shells_are_critical_and_skip_depth(self):
        pages = [page(f"{SITE}/", links=[f"{SITE}/a/"]),
                 page(f"{SITE}/a/", links=[f"{SITE}/b/"]), page(f"{SITE}/b/", links=[f"{SITE}/c/"]),
                 page(f"{SITE}/c/", links=[f"{SITE}/d/"]),
                 page(f"{SITE}/d/", "пусто", blocks={"script": 3})]
        issues = {(i[1], i[2]): i[0] for i in checks.run_all(pages, SITE + "/")["issues"]}
        self.assertEqual(issues[(f"{SITE}/d/", "js-shell")], "critical")
        self.assertNotIn((f"{SITE}/d/", "deep"), issues)


class TestLinkGraphEdges(unittest.TestCase):
    def test_a_redirect_loop_behind_the_home_page_ends(self):
        stub = lambda to: f'<meta http-equiv="refresh" content="0; url={to}">'
        pages = [page(f"{SITE}/", "", raw=stub("/b/")), page(f"{SITE}/b/", "", raw=stub("/c/")),
                 page(f"{SITE}/c/", "", raw=stub("/b/"))]
        graph = checks.link_graph(pages, SITE + "/")
        self.assertEqual(graph["home_redirected_from"], f"{SITE}/")

    def test_orphans_and_unreachable_are_critical(self):
        pages = [page(f"{SITE}/"), page(f"{SITE}/a/", links=[f"{SITE}/b/"]),
                 page(f"{SITE}/b/", links=[f"{SITE}/a/"])]
        issues = {(i[1], i[2]): i[0] for i in checks.run_all(pages, SITE + "/")["issues"]}
        self.assertEqual(issues[(f"{SITE}/a/", "unreachable")], "critical")
        self.assertNotIn((f"{SITE}/a/", "orphan"), issues)
        lone = pages + [page(f"{SITE}/c/")]
        issues = {(i[1], i[2]): i[0] for i in checks.run_all(lone, SITE + "/")["issues"]}
        self.assertEqual(issues[(f"{SITE}/c/", "orphan")], "critical")

    def test_hreflang_twins_are_not_orphans(self):
        pages = [page(f"{SITE}/", links=[f"{SITE}/en/"]),
                 page(f"{SITE}/en/", alternates=[("en", f"{SITE}/en/"), ("de", f"{SITE}/de/")]),
                 page(f"{SITE}/de/", alternates=[("en", f"{SITE}/en/"), ("de", f"{SITE}/de/")])]
        graph = checks.link_graph(pages, SITE + "/")
        self.assertEqual(graph["orphans"], [])
        self.assertEqual(graph["only_hreflang"], [f"{SITE}/de/"])
        self.assertEqual(graph["depth"], {f"{SITE}/": 0, f"{SITE}/en/": 1, f"{SITE}/de/": 2})


class TestRootMismatch(unittest.TestCase):
    def site(self, n):
        """Каталог на уровень выше корня: адреса /content/pN/, ссылки — /pN/."""
        return [page(f"{SITE}/content/p{i}/", links=[f"{SITE}/p{(i + 1) % n}/"],
                     path=f"/proj/content/p{i}/index.html") for i in range(n)]

    def test_shifted_links_are_named(self):
        pages = self.site(4)
        note = checks.root_mismatch(pages, checks.link_graph(pages))
        self.assertIn("каталог не соответствует корню", note)
        self.assertIn("сейчас это /proj/content", note)
        self.assertIn("корень example.com", note)

    def test_two_pages_are_too_few_to_say(self):
        pages = self.site(2)
        self.assertEqual(checks.root_mismatch(pages, checks.link_graph(pages)), "")

    def test_links_that_do_not_resolve_after_the_shift_are_not_a_mismatch(self):
        pages = [page(f"{SITE}/content/p{i}/", links=[f"{SITE}/elsewhere/x{i}/"],
                      path=f"/proj/content/p{i}/index.html") for i in range(4)]
        self.assertEqual(checks.root_mismatch(pages, checks.link_graph(pages)), "")

    def test_a_minority_of_orphans_is_not_a_mismatch(self):
        pages = [page(f"{SITE}/", links=[f"{SITE}/content/p{i}/" for i in range(6)])]
        pages += [page(f"{SITE}/content/p{i}/", links=[f"{SITE}/p{i}/"] if i < 3 else [],
                       path=f"/proj/content/p{i}/index.html") for i in range(6)]
        self.assertEqual(checks.root_mismatch(pages, checks.link_graph(pages, SITE + "/")), "")


class TestTemplateWide(unittest.TestCase):
    def issues(self, hit, code="vague-anchor"):
        return [("info", f"{SITE}/p{i}/", code, "") for i in range(hit)]

    def test_ninety_percent_of_twenty_pages(self):
        self.assertEqual(len(checks.template_wide(self.issues(18), 20)), 1)
        self.assertEqual(checks.template_wide(self.issues(17), 20), [])
        self.assertEqual(checks.template_wide(self.issues(19), 19), [])

    def test_one_language_of_two(self):
        pages = ([page(f"{SITE}/p{i}/", lang="zh") for i in range(20)]
                 + [page(f"{SITE}/q{i}/", lang="en") for i in range(30)])
        notes = checks.template_wide(self.issues(18, "description-length"), 50, pages=pages)
        self.assertEqual(len(notes), 1)
        self.assertIn("«zh» из 20", notes[0])
        self.assertIn("36%", notes[0])
        self.assertEqual(checks.template_wide(self.issues(17, "description-length"), 50,
                                              pages=pages), [])
        small = pages[1:]
        self.assertEqual(checks.template_wide(self.issues(19, "x")[1:], 49, pages=small), [])
        self.assertEqual(checks.template_wide(self.issues(18), 50, pages=pages[:20]), [])


class TestSortIssues(unittest.TestCase):
    def test_level_then_weight_then_code_then_url(self):
        issues = [("info", "/b", "similar", ""), ("warning", "/a", "thin", ""),
                  ("critical", "/z", "near-duplicate", ""), ("critical", "/a", "orphan", ""),
                  ("critical", "/b", "orphan", ""), ("critical", "/a", "zzz-unknown", ""),
                  ("odd", "/a", "orphan", ""), ("warning", "/a", "no-h1", "")]
        self.assertEqual([(i[0], i[1], i[2]) for i in checks.sort_issues(issues)],
                         [("critical", "/a", "orphan"), ("critical", "/b", "orphan"),
                          ("critical", "/z", "near-duplicate"), ("critical", "/a", "zzz-unknown"),
                          ("warning", "/a", "thin"), ("warning", "/a", "no-h1"),
                          ("info", "/b", "similar"), ("odd", "/a", "orphan")])


class TestParkedRules(unittest.TestCase):
    def test_only_the_same_path_in_another_language_is_parked(self):
        pages = [page(f"{SITE}/de/p{i}/", robots="noindex", canonical=f"{SITE}/en/other{i}/")
                 for i in range(5)]
        self.assertEqual(checks.parked_translations(pages), {})

    def test_original_in_the_root_is_the_main_language(self):
        pages = [page(f"{SITE}/de/p{i}/", robots="noindex", canonical=f"{SITE}/p{i}/")
                 for i in range(5)]
        self.assertEqual(set(checks.parked_translations(pages).values()), {("de", "основной")})

    def test_the_collapsed_finding_counts_what_it_folded(self):
        pages = [page(f"{SITE}/en/p{i}/", links=[f"{SITE}/en/p{(i + 1) % 6}/"],
                      alternates=[("en", f"{SITE}/en/p{i}/"), ("de", f"{SITE}/de/p{i}/")])
                 for i in range(6)]
        pages += [page(f"{SITE}/de/p{i}/", robots="noindex", canonical=f"{SITE}/en/p{i}/",
                       alternates=[("en", f"{SITE}/en/p{i}/"), ("de", f"{SITE}/de/p{i}/")]
                       if i < 2 else []) for i in range(5)]
        pages.append(page(f"{SITE}/de/p9/", robots="noindex", canonical=f"{SITE}/en/p9/"))
        result = checks.run_all(pages, SITE + "/en/p0/")
        parked = [i for i in result["issues"] if i[2] == "translations-parked"]
        self.assertEqual(len(parked), 1)
        level, url, _, message = parked[0]
        self.assertEqual((level, url), ("critical", "hreflang"))
        self.assertIn("6 страниц(ы) на 1 язык(ах)", message)
        self.assertIn("«en»", message)
        self.assertIn("По языкам: de 6.", message)
        self.assertIn("2 из них всё ещё объявляют hreflang", message)
        self.assertIn("5 открыт(ых) страниц всё ещё называют их", message)
        self.assertIn("У 1 из них canonical ведёт на страницу, которой среди файлов нет.", message)
        self.assertFalse([i for i in result["issues"] if i[1].startswith(f"{SITE}/de/")
                          and i[2] in checks.PARKED_ECHOES])


class TestClosedNoise(unittest.TestCase):
    def test_closed_page_keeps_closure_findings_only(self):
        # hreflang закрытой страницы поисковик не читает: его находки тоже шум.
        issues = [("warning", "/c", "thin", ""), ("critical", "/c", "noindex", ""),
                  ("warning", "/c", "hreflang-missing", ""), ("warning", "/o", "thin", "")]
        pages = [page(f"{SITE}/c/", robots="noindex"), page(f"{SITE}/o/")]
        pages[0].url, pages[1].url = "/c", "/o"
        self.assertEqual([i[2] + i[1] for i in checks.drop_closed_noise(issues, pages)],
                         ["noindex/c", "thin/o"])


class TestValidateConfigBounds(unittest.TestCase):
    def test_edges_that_are_allowed(self):
        self.assertEqual(checks.validate_config({"near_duplicate": 1, "similar": 1,
                                                 "shingle_size": 1, "lsh_bands": 32,
                                                 "_comment": "x"}), [])

    def test_edges_that_are_refused(self):
        for bad in ({"near_duplicate": 0}, {"slot_share": 1.01}, {"shingle_size": 0},
                    {"title_min": 65}, {"description_min": 165}, {"lsh_bands": 33},
                    {"similar": 0.81}, {"thin_words": True}):
            with self.assertRaises(core.SourceError, msg=bad):
                checks.validate_config(bad)

    def test_a_typo_is_named_with_a_suggestion(self):
        notes = checks.validate_config({"near_duplicat": 0.8, "zzz": 1})
        self.assertEqual(len(notes), 2)
        self.assertIn("near_duplicate", notes[0])
        self.assertNotIn("возможно", notes[1])


class TestRunAllDuplicates(unittest.TestCase):
    def test_the_closest_partner_decides_the_level(self):
        common = words("общ", 60)
        a = page(f"{SITE}/a/", " ".join(common + words("а", 7)), chrome="меню")
        b = page(f"{SITE}/b/", " ".join(common + words("б", 7)), chrome="меню")   # a~b = 0.8
        c = page(f"{SITE}/c/", " ".join(common[:50] + words("в", 10)), chrome="меню")  # ≈ 0.63
        result = checks.run_all([a, b, c])
        near = {i[1]: i for i in result["issues"] if i[2] in ("near-duplicate", "similar")}
        self.assertEqual(near[a.url][2], "near-duplicate")
        self.assertEqual(near[a.url][0], "critical")
        self.assertIn("со страницей " + b.url + " и ещё 1", near[a.url][3])
        self.assertEqual(near[c.url][0], "info")
        self.assertTrue(any(n.startswith("почти-дубли образуют 1 групп(ы), в самой большой 2")
                            for n in result["notes"]), result["notes"])

    def test_bare_pages_are_left_out_of_duplicates(self):
        tiny = [page(f"{SITE}/t{i}/", "один и тот же короткий текст страницы") for i in range(2)]
        full = twins(60, 7)
        result = checks.run_all(tiny + full)
        self.assertEqual(sorted((a.url, b.url) for a, b, _ in result["duplicates"]),
                         [(f"{SITE}/a/", f"{SITE}/b/")])


# ── doctor: воронка, сравнение индексов, разбор потерь ────────────────────────

def site_pages(*names, closed=()):
    return [page(f"{SITE}/{n}/", robots="noindex" if n in closed else "") for n in names]


def urls(*names):
    return [f"{SITE}/{n}/" for n in names]


class TestFunnelArithmetic(unittest.TestCase):
    def test_index_step_counts_only_what_the_sitemap_lists(self):
        pages = site_pages("a", "b", "c")
        result = doctor.funnel(pages, sitemap_urls=urls("a", "b"), indexed_urls=urls("a", "c"))
        index = result["steps"][3]
        self.assertEqual((index["count"], index["lost"]), (1, 1))
        self.assertEqual(result["not_indexed"], urls("b"))
        self.assertEqual(result["missing_from_sitemap"], urls("c"))
        self.assertTrue(result["has_sitemap"])
        self.assertFalse(doctor.funnel(pages, indexed_urls=urls("a"))["has_sitemap"])

    def test_a_page_with_a_query_is_its_own_page_when_it_exists(self):
        pages = [page(f"{SITE}/a/"), page(f"{SITE}/a/?p=2")]
        result = doctor.funnel(pages, sitemap_urls=[f"{SITE}/a/?p=2", f"{SITE}/a/?utm=x"])
        self.assertEqual(result["missing_from_sitemap"], [])
        self.assertEqual(result["stale_in_sitemap"], [])
        result = doctor.funnel([page(f"{SITE}/a/")], sitemap_urls=[f"{SITE}/b/?utm=x"])
        self.assertEqual(result["stale_in_sitemap"], ["//example.com/b?utm=x"])

    def test_non_panel_sources_count_and_are_named(self):
        pages = site_pages("a", "b")
        result = doctor.funnel(pages, by_engine={"google": urls("a")},
                               by_source={"screamingfrog": urls("b")})
        self.assertEqual(result["steps"][2]["count"], 2)
        self.assertTrue(any("индексом не являются (screamingfrog)" in f for f in result["foreign"]),
                        result["foreign"])
        only = doctor.funnel(pages, by_source={"screamingfrog": urls("b")})
        self.assertTrue(only["has_index"])
        self.assertTrue(any(f.startswith("панели вебмастера среди выгрузок нет") for f in only["foreign"]),
                        only["foreign"])
        self.assertFalse(any("панели вебмастера среди" in f or "не являются" in f
                             for f in doctor.funnel(pages, by_engine={"google": urls("a")})["foreign"]))

    def test_engine_rows_name_the_kind_of_source(self):
        result = doctor.funnel(site_pages("a"), by_engine={"google": urls("a")},
                               by_source={"ga4": urls("a")})
        names = [s["name"] for s in result["steps"] if s.get("engine")]
        self.assertIn("  из них в google", names)
        self.assertIn("  из них в ga4 (аналитика)", names)

    def test_cited_pages_outside_the_site_are_unknown(self):
        result = doctor.funnel(site_pages("a"), cited={"copilot": {f"{SITE}/a/": 2,
                                                                  f"{SITE}/x/": 1}})
        self.assertEqual(result["cited_unknown"], ["//example.com/x"])
        self.assertEqual(result["cited_top"], [(f"{SITE}/a/", 2), ("//example.com/x", 1)])


class TestCrossEngine(unittest.TestCase):
    def test_everywhere_only_in_one_and_nowhere(self):
        pages = site_pages("a", "b", "c", "d", closed=("d",))
        result = doctor.funnel(pages, by_engine={"google": urls("a", "b"), "yandex": urls("a")})
        rows = {r["kind"]: (r["count"], r["urls"]) for r in doctor.cross_engine(result, pages)}
        self.assertEqual(rows, {"везде": (1, []), "нет только в yandex": (1, urls("b")),
                                "нигде": (1, urls("c"))})

    def test_one_panel_is_not_a_comparison(self):
        pages = site_pages("a")
        self.assertEqual(doctor.cross_engine(doctor.funnel(pages, by_engine={"google": urls("a")}),
                                             pages), [])

    def test_lists_are_capped_at_fifty(self):
        names = [f"p{i}" for i in range(60)]
        pages = site_pages(*names)
        result = doctor.funnel(pages, by_engine={"google": urls(*names[:55]), "bing": urls("p0")})
        rows = {r["kind"]: r for r in doctor.cross_engine(result, pages)}
        self.assertEqual(rows["нет только в bing"]["count"], 54)
        self.assertEqual(len(rows["нет только в bing"]["urls"]), 50)


class TestExplain(unittest.TestCase):
    def analysis(self, pages, depth=None, pairs=(), orphans=()):
        return {"graph": {"orphans": list(orphans), "unreachable": [], "depth": depth or {}},
                "config": dict(checks.CONFIG), "duplicates": list(pairs), "pages": pages}

    def test_every_cause_is_named_and_the_rest_too(self):
        names = ["orph", "dup", "dup2", "thin", "deep", "untitled", "rest", "sim"]
        pages = site_pages(*names)
        for p in pages:
            p.title = "Заголовок"
            p.text = " ".join(words("т", 250))
        pages[3].text = " ".join(words("т", 249))
        pages[5].title = ""
        funnel = {"not_indexed": urls(*names), "display": {}}
        a = self.analysis(pages, depth={f"{SITE}/deep/": 4, f"{SITE}/rest/": 3},
                          pairs=[(pages[1], pages[2], 0.8), (pages[7], pages[6], 0.79)],
                          orphans=[f"{SITE}/orph/"])
        out = {o["cause"]: o["urls"] for o in doctor.explain(funnel, a)}
        self.assertEqual(out, {
            "сироты и недостижимые от главной": ["//example.com/orph"],
            "почти-дубли других страниц": ["//example.com/dup", "//example.com/dup2"],
            "тонкие страницы": ["//example.com/thin"],
            "глубже допустимого клика": ["//example.com/deep"],
            "без title": ["//example.com/untitled"],
            "причина не установлена локально": ["//example.com/rest", "//example.com/sim"],
        })

    def test_without_impressions_the_rest_is_called_by_its_name(self):
        pages = site_pages("a")
        pages[0].title, pages[0].text = "Заголовок", " ".join(words("т", 300))
        funnel = {"not_indexed": urls("a"), "impressions_only": True}
        causes = [o["cause"] for o in doctor.explain(funnel, self.analysis(pages))]
        self.assertEqual(causes, ["показов за период нет, других причин локально не видно"])

    def test_lists_are_capped_at_fifty(self):
        names = [f"p{i}" for i in range(60)]
        pages = site_pages(*names)
        funnel = {"not_indexed": urls(*names)}
        out = doctor.explain(funnel, self.analysis(pages, orphans=urls(*names)))
        self.assertEqual([(o["count"], len(o["urls"])) for o in out], [(60, 50), (60, 50)])


class TestReadSitemap(OutDir):
    def write(self, d, name, body):
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    XHTML = 'xmlns:xhtml="http://www.w3.org/1999/xhtml"'

    def index(self, *children):
        return (f'<sitemapindex {self.NS}>' + "".join(
            f"<sitemap><loc>{c}</loc></sitemap>" for c in children) + "</sitemapindex>")

    def test_hreflang_from_a_child_sitemap_reaches_the_result(self):
        d = self.out()
        self.write(d, "child.xml", f'<urlset {self.NS} {self.XHTML}><url><lastmod>2026-01-01</lastmod>'
                   f'<loc>{SITE}/en/</loc><xhtml:link rel="alternate" hreflang="de" href="{SITE}/de/"/>'
                   f'<xhtml:link rel="canonical" hreflang="fr" href="{SITE}/fr/"/></url></urlset>')
        result = doctor.read_sitemap(self.write(d, "sitemap.xml", self.index(f"{SITE}/child.xml")))
        self.assertEqual(result["urls"], [f"{SITE}/en/"])
        self.assertEqual(result["alternates"], {f"{SITE}/en/": [("de", f"{SITE}/de/")]})
        self.assertEqual(result["error"], "")

    def test_nesting_is_limited_to_four_levels(self):
        d = self.out()
        self.write(d, "s4.xml", f'<urlset {self.NS}><url><loc>{SITE}/deep/</loc></url></urlset>')
        for n in (3, 2, 1, 0):
            self.write(d, f"s{n}.xml", self.index(f"{SITE}/s{n + 1}.xml"))
        self.assertEqual(doctor.read_sitemap(os.path.join(d, "s1.xml"))["urls"], [f"{SITE}/deep/"])
        result = doctor.read_sitemap(os.path.join(d, "s0.xml"))
        self.assertEqual(result["urls"], [])
        self.assertIn("вложенность", result["error"])

    def test_an_index_that_gives_nothing_says_so(self):
        d = self.out()
        result = doctor.read_sitemap(self.write(d, "sitemap.xml",
                                                f'<sitemapindex {self.NS}><sitemap/></sitemapindex>'))
        self.assertIn("индекс не дал ни одного адреса", result["error"])
        empty = doctor.read_sitemap(self.write(d, "u.xml", f'<urlset {self.NS}><url><loc></loc></url></urlset>'))
        self.assertIn("нет ни одного <loc>", empty["error"])


class TestReadIndexed(OutDir):
    def csv(self, text):
        path = os.path.join(self.out(), "export.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_relative_paths_are_completed_and_counted(self):
        result = doctor.read_indexed(self.csv("Page,Views\n/a/,3\n/b/,2\n,1\nmailto:x,1\n"), SITE)
        self.assertEqual(result["urls"], [f"{SITE}/a/", f"{SITE}/b/"])
        self.assertEqual(result["notes"], [f"export.csv: 2 адресов были относительными путями — "
                                           f"достроены до {SITE}/…"])

    def test_without_site_relative_paths_are_skipped_aloud(self):
        result = doctor.read_indexed(self.csv(f"Page,Views\n/a/,3\n{SITE}/b/,2\n"))
        self.assertEqual(result["urls"], [f"{SITE}/b/"])
        self.assertTrue(result["notes"][0].startswith("export.csv: 1 строк"), result["notes"])

    def test_not_indexed_statuses_are_excluded_with_their_reason(self):
        text = ("URL,Coverage state\n/a/,Submitted and indexed\n/b/,Excluded by noindex\n"
                f"{SITE}/c/,\n{SITE}/d/,Indexed\n")
        result = doctor.read_indexed(self.csv(text), SITE, index_status=True)
        self.assertEqual(result["urls"], [f"{SITE}/a/", f"{SITE}/d/"])
        self.assertEqual(result["excluded"], {f"{SITE}/b/": "Excluded by noindex",
                                              f"{SITE}/c/": "статус не указан"})

    def test_a_list_without_header_keeps_its_first_row(self):
        result = doctor.read_indexed(self.csv(f"/locations/berlin/\n/b/\n"), SITE)
        self.assertEqual(result["urls"], [f"{SITE}/locations/berlin/", f"{SITE}/b/"])

    def test_the_header_settles_a_tie_between_columns(self):
        text = f"Referrer,Landing page\n{SITE}/r1/,{SITE}/a/\n{SITE}/r2/,{SITE}/b/\n"
        self.assertEqual(doctor.read_indexed(self.csv(text))["urls"], urls("a", "b"))


# ── content: выдуманные числа ─────────────────────────────────────────────────

class TestNumberForms(unittest.TestCase):
    def test_separators(self):
        cases = {"1.299,99": "1299.99", "1,299.99": "1299.99", "1.500": "1500", "1,500": "1500",
                 "100,000": "100000", "100.000": "100000", "1234,567": "1234.567",
                 "1234.567": "1234.567", "0,500": "0.5", "0.500": "0.5", "1.234.567": "1234567",
                 "1,234,567": "1234567", "12,5": "12.5", "1.5": "1.5", "12.50": "12.5"}
        for raw, want in cases.items():
            self.assertEqual(content._norm_number(raw), want, raw)


def facts(text, row, rows=None, units=None, url=f"{SITE}/a/"):
    p = page(url, text)
    rows = rows if rows is not None else [row]
    return content.check_facts([p], {p.url: row} if row is not None else {}, rows,
                               fact_units=units)


class TestInventedNumbers(unittest.TestCase):
    def test_a_percent_in_the_data_is_supported(self):
        self.assertEqual(facts("скидка 15% на всё", {"discount": "15"}), [])

    def test_the_finding_shows_the_number_as_written(self):
        issue = facts("билет стоит $95, вес 25 тонн, налог 7%, сбор EUR 40",
                      {"price": "60"}, units=["тонн"])
        self.assertEqual(len(issue), 1)
        level, _, code, message = issue[0]
        self.assertEqual((level, code), ("critical", "unsupported-number"))
        self.assertEqual(message, "в тексте есть числа, которых нет в данных: "
                                  "25 тонн, EUR 40, 7 %, $95")

    def test_more_than_six_are_shortened(self):
        text = ", ".join(f"{n}%" for n in range(11, 18))
        message = facts(text, {"x": "1"})[0][3]
        self.assertTrue(message.endswith(" и ещё"), message)
        self.assertEqual(message.count("%"), 6)
        six = facts(", ".join(f"{n}%" for n in range(11, 17)), {"x": "1"})[0][3]
        self.assertFalse(six.endswith(" и ещё"), six)

    def test_weak_numbers_are_listed_longest_first_and_capped(self):
        text = " ".join(f"{n} коробок" for n in (5, 12345, 77, 9, 31, 400, 18, 66, 8))
        issue = facts(text, {"x": "1"})
        self.assertEqual([(i[0], i[2]) for i in issue], [("info", "check-by-eye")])
        self.assertTrue(issue[0][3].endswith("5 коробок, 8 коробок и ещё 1"), issue[0][3])
        self.assertIn("просмотри глазами: 12345 коробок, 400 коробок", issue[0][3])

    def test_a_strong_number_is_not_repeated_as_weak(self):
        issue = facts("налог 7% и ещё 7 процентов сверху", {"x": "1"})
        self.assertEqual([i[2] for i in issue], ["unsupported-number"])

    def test_years_are_not_facts_but_their_neighbours_are(self):
        self.assertEqual(content._generic_numbers_in("модель 1900 года и выпуск 2100 Toyota"), {})
        self.assertEqual(sorted(content._generic_numbers_in("1899 рублей и 2101 рублей")),
                         ["1899", "2101"])
        self.assertEqual(content._generic_numbers_in("всего 1,900 рублей"), {"1900": "рублей"})

    def test_an_unmatched_page_is_not_checked(self):
        p, q = page(f"{SITE}/a/", "цена 777 рублей"), page(f"{SITE}/b/", "цена 555 рублей")
        out = content.check_facts([p, q], {q.url: {"price": "555"}}, [{"price": "555"}])
        self.assertEqual(out, [])


class TestSiteConstants(unittest.TestCase):
    def rows(self, having, total, value="500"):
        return [{"fee": value if i < having else str(1000 + i)} for i in range(total)]

    def test_half_of_the_rows_make_a_constant(self):
        self.assertIn("500", content._site_constants(self.rows(5, 10)))
        self.assertNotIn("500", content._site_constants(self.rows(4, 10)))
        self.assertNotIn("500", content._site_constants(self.rows(3, 10)))

    def test_on_a_tiny_dataset_two_rows_are_needed(self):
        self.assertIn("500", content._site_constants(self.rows(2, 2)))
        self.assertNotIn("500", content._site_constants(self.rows(1, 2)))
        self.assertNotIn("500", content._site_constants(self.rows(1, 1)))


class TestMatchRows(OutDir):
    def pages(self, root, files):
        out = []
        for rel, (title, meta) in files.items():
            out.append(page(f"{SITE}/{rel}/", title=title, meta=meta,
                            path=os.path.join(root, rel, "index.md")))
        return out

    def test_slug_of_a_nested_page_is_its_last_segment(self):
        root = self.out()
        pages = self.pages(root, {"cities/moskva": ("Москва", {})})
        result = content.match_rows(pages, [{"keyword": "Москва"}], "keyword", root)
        self.assertEqual(list(result["matched"]), [f"{SITE}/cities/moskva/"])

    def test_a_row_without_keyword_is_nobodys(self):
        root = self.out()
        pages = [page(f"{SITE}/", title="Главная", path=os.path.join(root, "index.md"))]
        result = content.match_rows(pages, [{"keyword": ""}, {"keyword": "  "}], "keyword", root)
        self.assertEqual(result["matched"], {})

    def test_two_rows_with_one_slug_make_the_page_ambiguous(self):
        root = self.out()
        pages = self.pages(root, {"moskva": ("Что угодно", {})})
        rows = [{"keyword": "Москва"}, {"keyword": "москва!"}]
        result = content.match_rows(pages, rows, "keyword", root)
        self.assertEqual((result["matched"], result["ambiguous"]), ({}, [f"{SITE}/moskva/"]))

    def test_frontmatter_keyword_wins_over_the_slug(self):
        root = self.out()
        pages = self.pages(root, {"moskva": ("Что угодно", {"keyword": "Казань"})})
        rows = [{"keyword": "Москва", "n": "1"}, {"keyword": "Казань", "n": "2"}]
        result = content.match_rows(pages, rows, "keyword", root)
        self.assertEqual(result["matched"][f"{SITE}/moskva/"]["n"], "2")

    def test_four_of_five_key_words_are_enough_three_of_four_are_not(self):
        root = self.out()
        rows = [{"keyword": "alpha bravo charlie delta echo", "n": "5"},
                {"keyword": "foxtrot golf hotel india", "n": "4"}]
        pages = self.pages(root, {"p1": ("alpha bravo charlie delta", {}),
                                  "p2": ("foxtrot golf hotel", {})})
        matched = content.match_rows(pages, rows, "keyword", root)["matched"]
        self.assertEqual({u: r["n"] for u, r in matched.items()}, {f"{SITE}/p1/": "5"})

    def test_title_match_needs_the_whole_key_and_a_clear_winner(self):
        root = self.out()
        rows = [{"keyword": "аренда виллы остин", "n": "1"}, {"keyword": "аренда виллы", "n": "2"},
                {"keyword": "аренда яхты остин", "n": "3"}]
        pages = self.pages(root, {"p1": ("Аренда виллы в Остине", {}),
                                  "p2": ("Аренда в Остине", {})})
        result = content.match_rows(pages, rows, "keyword", root)
        self.assertEqual(result["matched"][f"{SITE}/p1/"]["n"], "1")
        self.assertNotIn(f"{SITE}/p2/", result["matched"])
        tie = self.pages(root, {"p3": ("Аренда виллы и яхты в Остине", {})})
        result = content.match_rows(tie, rows[:1] + rows[2:], "keyword", root)
        self.assertEqual((result["matched"], result["ambiguous"]), ({}, [f"{SITE}/p3/"]))


class TestTemplateSeams(unittest.TestCase):
    def site(self, n, shared, opening=0):
        pages = []
        for i in range(n):
            heads = ([(1, f"Город {i}"), (2, "Цены"), (3, "Как добраться")] if i < shared
                     else [(2, f"Свой раздел {i}"), (2, f"Ещё раздел {i}")])
            text = (" ".join(words("начало", 12)) + f" хвост{i}" if i < opening
                    else " ".join(words(f"т{i}x", 20)))
            pages.append(page(f"{SITE}/p{i}/", text, headings=heads))
        return pages

    def test_seventy_percent_share_one_skeleton(self):
        result = content.check_template_seams(self.site(10, 7))
        found = [i for i in result["issues"] if i[2] == "template-skeleton"]
        self.assertEqual(len(found), 7)
        self.assertEqual(found[0][0], "warning")
        self.assertIn("те же 2 заголовков в том же порядке ещё у 6 страниц", found[0][3])
        self.assertEqual(result["repeated"], [{"headings": ["цены", "как добраться"], "count": 7}])
        self.assertEqual(content.check_template_seams(self.site(10, 6))["repeated"], [])

    def test_share_and_floor_of_the_threshold(self):
        self.assertEqual(len(content.check_template_seams(self.site(20, 14))["repeated"]), 1)
        self.assertEqual(content.check_template_seams(self.site(20, 13))["repeated"], [])
        pages = self.site(5, 3)
        for p in pages[3:]:
            p.headings = []
        self.assertEqual(len(content.check_template_seams(pages)["repeated"]), 1)
        pages[2].headings = []
        self.assertEqual(content.check_template_seams(pages)["repeated"], [])

    def test_eight_words_are_an_opening(self):
        pages = self.site(10, 0)
        for p in pages[:3]:
            p.text = " ".join(words("начало", 8))
        self.assertEqual(len([i for i in content.check_template_seams(pages)["issues"]
                              if i[2] == "same-opening"]), 3)

    def test_the_share_is_of_pages_that_have_a_skeleton(self):
        pages = self.site(10, 4)
        for p in pages[4:8]:
            p.headings = [(2, "Один")]
        self.assertEqual(len(content.check_template_seams(pages)["repeated"]), 1)

    def test_five_pages_are_enough_four_are_not(self):
        self.assertEqual(len(content.check_template_seams(self.site(5, 5))["repeated"]), 1)
        four = content.check_template_seams(self.site(4, 4))
        self.assertEqual((four["issues"], four["skipped"]), ([], "страниц 4 — мало для оценки шаблонности"))

    def test_same_opening_needs_three_pages_and_eight_words(self):
        result = content.check_template_seams(self.site(10, 0, opening=3))
        found = [i for i in result["issues"] if i[2] == "same-opening"]
        self.assertEqual([(i[0], i[1]) for i in found],
                         [("warning", f"{SITE}/p{i}/") for i in range(3)])
        self.assertIn("ещё у 2 страниц", found[0][3])
        self.assertEqual([i for i in content.check_template_seams(self.site(10, 0, opening=2))["issues"]
                          if i[2] == "same-opening"], [])
        short = self.site(10, 0)
        for p in short[:3]:
            p.text = " ".join(words("начало", 7))
        self.assertEqual([i for i in content.check_template_seams(short)["issues"]
                          if i[2] == "same-opening"], [])

    def test_opening_is_twelve_words(self):
        pages = self.site(10, 0)
        for n, p in enumerate(pages[:3]):
            p.text = " ".join(words("начало", 11)) + f" разное{n} " + " ".join(words("х", 5))
        self.assertEqual([i for i in content.check_template_seams(pages)["issues"]
                          if i[2] == "same-opening"], [])
        for n, p in enumerate(pages[:3]):
            p.text = " ".join(words("начало", 12)) + f" разное{n}"
        self.assertEqual(len([i for i in content.check_template_seams(pages)["issues"]
                              if i[2] == "same-opening"]), 3)

    def test_thirty_percent_of_a_large_site(self):
        pages = self.site(20, 0, opening=6)
        self.assertEqual(len([i for i in content.check_template_seams(pages)["issues"]
                              if i[2] == "same-opening"]), 6)
        pages = self.site(20, 0, opening=5)
        self.assertEqual([i for i in content.check_template_seams(pages)["issues"]
                          if i[2] == "same-opening"], [])


class TestBrief(unittest.TestCase):
    def test_levels_and_vague_anchors(self):
        p = page(f"{SITE}/a/", meta={"status": "Draft"},
                 anchors=["тут", "→", "2", "en", "подробнее о визе", "ок", "да", "вот", "здесь", "ну"])
        issues = {i[2]: i for i in content.check_brief([p])}
        self.assertEqual(issues["still-draft"][0], "critical")
        self.assertEqual(issues["vague-anchor"][0], "info")
        self.assertEqual(issues["vague-anchor"][3],
                         "неинформативные анкоры: «тут», «ок», «да», «вот»")

    def test_run_names_what_it_did_not_check(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        pages = [page(f"{SITE}/moskva/", path=os.path.join(root, "moskva", "index.md")),
                 page(f"{SITE}/other/", path=os.path.join(root, "other", "index.md"))]
        result = content.run(pages, [{"keyword": "Москва"}, {"keyword": "москва!"}], root=root)
        self.assertEqual(result["ambiguous"], [f"{SITE}/moskva/"])
        self.assertEqual(result["unmatched"], [f"{SITE}/moskva/", f"{SITE}/other/"])
        self.assertTrue(any(n.startswith("1 страниц(ы) подошли сразу") for n in result["notes"]))
        self.assertTrue(any(n.startswith("швы шаблона не оценивались: страниц 2") for n in result["notes"]))
        five = [page(f"{SITE}/p{i}/", path=os.path.join(root, f"p{i}.md")) for i in range(5)]
        result = content.run(five, [{"keyword": "x"}], root=root)
        self.assertFalse(any("не оценивались" in n or "подошли сразу" in n for n in result["notes"]))

    def test_run_without_rows_checks_no_facts(self):
        result = content.run([page(f"{SITE}/a/", "цена 777 рублей")])
        self.assertEqual((result["facts_checked"], result["unmatched"], result["matched_rows"]),
                         (False, [], 0))


# ── core: адреса, хэш, плотная письменность, разбор ───────────────────────────

def parsed(html):
    ex = core._Extractor()
    ex.feed(html)
    ex.close()
    return ex


class TestCoreBasics(unittest.TestCase):
    def test_is_dense_bounds(self):
        han = [chr(0x4E00 + i) for i in range(10)]
        self.assertFalse(core.is_dense([]))
        self.assertTrue(core.is_dense(han[:6] + ["ab"] * 5))
        self.assertFalse(core.is_dense(han[:5] + ["ab"] * 5))            # ровно половина — нет
        self.assertTrue(core.is_dense(["぀", "﫿", "x"]))
        self.assertFalse(core.is_dense(["中文", "日本", "x"]))             # не по одному знаку
        self.assertFalse(core.is_dense(["word"] * 400 + han * 100))      # смотрятся первые 400
        self.assertTrue(core.is_dense(han * 40 + ["word"] * 401))

    def test_description_is_part_of_the_hash(self):
        a = core.Page(path="a", url=SITE + "/a/", title="T", description="раз", text="текст")
        b = core.Page(path="a", url=SITE + "/a/", title="T", description="два", text="текст")
        self.assertNotEqual(a.content_hash, b.content_hash)

    def test_nosnippet_directive(self):
        self.assertTrue(page(f"{SITE}/a/", robots="index, nosnippet").nosnippet)
        self.assertFalse(page(f"{SITE}/a/", robots="max-snippet:10").nosnippet)

    def test_default_ports_and_empty_address(self):
        self.assertEqual(core.url_key(""), "")
        self.assertEqual(core.url_key("//example.com:443/a"), "//example.com/a")
        self.assertEqual(core.url_key("https://example.com:80/a"), "//example.com:80/a")
        self.assertEqual(core.url_key("http://example.com:80/a"), "//example.com/a")

    def test_normalize_url_decides_the_slash_by_the_last_segment(self):
        self.assertEqual(core.normalize_url("https://example.com/a"), "https://example.com/a/")
        self.assertEqual(core.normalize_url("https://example.com/v2.0"), "https://example.com/v2.0")
        self.assertEqual(core.normalize_url("https://example.com/v2.0", directory=True),
                         "https://example.com/v2.0/")


class TestParserBlocks(unittest.TestCase):
    def test_paragraph_in_a_layout_table_is_prose_and_cells_are_not(self):
        ex = parsed("<main><table><tr><td><p>Абзац в ячейке.</p></td><td>данные</td></tr>"
                    "</table><p>После таблицы.</p></main>")
        self.assertEqual(ex.paragraphs, ["Абзац в ячейке.", "После таблицы."])

    def test_breadcrumbs_inside_main_are_not_the_first_paragraph(self):
        ex = parsed('<main><div class="breadcrumbs"><a href="/">Главная</a> / Раздел</div>'
                    "<p>Ответ на вопрос.</p></main>")
        self.assertEqual(ex.paragraphs, ["Ответ на вопрос."])
        self.assertEqual(ex.main_text, "Главная / Раздел Ответ на вопрос.")

    def test_text_after_a_closed_table_is_prose_again(self):
        ex = parsed("<main><div><table><tr><td>ячейка</td></tr></table></div>"
                    "<div>Текст после таблицы.</div></main>")
        self.assertIn("Текст после таблицы.", ex.paragraphs)
        self.assertNotIn("ячейка", ex.paragraphs)



class TestParserFields(unittest.TestCase):
    HTML = ('<html lang="ru"><head><base href="/root/"><title>Т</title>'
            '<meta name="author" content="Иван"><meta name="robots" content="noindex">'
            '<meta name="googlebot" content="nosnippet"><meta property="og:x" content="">'
            '<meta content="без имени"><link rel="alternate" hreflang="de" href="/de/">'
            '<link rel="alternate" href="/feed"><link rel="stylesheet" hreflang="fr" href="/x.css">'
            '</head><body><main><h1>Заголовок</h1><p>Раз<b>два</b> три <i>четыре</i>.</p>'
            '<ul><li>a</li><li>b</li></ul><img src=x><img src=y alt="  "><img src=z alt="ок">'
            '<time datetime="2026-01-02">2 янв</time><a href="/n" rel="nofollow">n</a>'
            '<a>без ссылки</a><a href="/ok">хорошая</a><svg><path d="M0"/></svg>'
            '<p>после иконки</p><script>var x="скрипт";</script><style>.a{}</style>'
            '<script type="application/ld+json">{"@type":"X"}</script><br/><p>конец</p></main>'
            '<footer><ul><li>подвал</li></ul></footer></body></html>')

    def test_fields(self):
        ex = parsed(self.HTML)
        self.assertEqual((ex.lang, ex.base, ex.title, ex.robots),
                         ("ru", "/root/", "Т", "noindex,nosnippet"))
        self.assertEqual(ex.alternates, [("de", "/de/")])
        self.assertEqual((ex.hrefs, ex.anchors, ex.headings), (["/ok"], ["хорошая"], [(1, "Заголовок")]))
        self.assertEqual(ex.blocks, {"li": 2, "table": 0, "img": 3, "img_no_alt": 2,
                                     "script": 1, "p": 3})
        self.assertEqual(ex.jsonld, ['{"@type":"X"}'])
        self.assertEqual(ex.meta, {"author": "Иван", "datemodified": "2026-01-02"})
        self.assertEqual(ex.main_text, "Заголовок Раздва три четыре. a b 2 янв n без ссылки "
                                       "хорошая после иконки конец")
        self.assertEqual(ex.chrome_text, "подвал")

    def test_unclosed_p_and_li_close_themselves(self):
        ex = parsed('<main><p class="byline">Автор<p>Первый абзац.<ul><li>раз<li>два</ul>'
                    '<p>Второй <span>абзац</span>.</main><footer>подвал</footer>')
        self.assertEqual(ex.chrome_text, "подвал")
        self.assertEqual(ex.blocks["li"], 2)
        self.assertTrue(ex.paragraphs[0].startswith("Первый абзац."), ex.paragraphs)
        self.assertFalse(any("Автор" in p for p in ex.paragraphs), ex.paragraphs)

    def test_without_main_everything_is_the_text(self):
        ex = parsed("<body><div>меню</div><p>Текст страницы.</p></body>")
        self.assertEqual((ex.main_text, ex.chrome_text), ("меню Текст страницы.", ""))


class TestDropSpansAndEssence(unittest.TestCase):
    def test_drop_spans(self):
        self.assertEqual(core.drop_spans("a <!-- x --> b <PRE>c</pre> d <preview>e</preview> "
                                         "<pre>не закрыт", core.NOT_LIVE),
                         "a   b   d <preview>e</preview> <pre>не закрыт")
        self.assertEqual(core.drop_spans("x <code>a <!-- b </code> c --> y", core.NOT_LIVE),
                         "x   c --> y")
        self.assertEqual(core.drop_spans("<pre-wrap>оставить</pre-wrap>", core.NOT_LIVE),
                         "<pre-wrap>оставить</pre-wrap>")
        self.assertEqual(core.drop_spans("", core.NOT_LIVE), "")

    def test_essence_of_a_large_page_keeps_what_the_checks_read(self):
        filler = "<p>" + "слово " * 1000 + "</p>"
        raw = ('<html amp lang="en"><head><META HTTP-EQUIV="refresh" content="0; url=/x/">'
               '<!-- <meta http-equiv="refresh" content="0; url=/old/"> --></head><body>'
               '<div id="root"></div><time datetime="2026-01-02"></time>'
               '<script>self.__next_f.push("NEXT_REDIRECT;replace;/en;307")</script>'
               '<script>// TODO: убрать</script><p>TODO: дописать</p>' + filler + "</body></html>")
        kept = core.essence(raw)
        self.assertLess(len(kept), 1000)
        for part in ('<html amp lang="en">', 'url=/x/', '<div id="root"></div>',
                     '<time datetime="2026-01-02">', "NEXT_REDIRECT;replace;/en;307", "TODO:"):
            self.assertIn(part, kept)
        self.assertNotIn("/old/", kept)
        self.assertEqual(core.essence("<p>коротко</p>"), "<p>коротко</p>")


class TestMarkdownBlocks(unittest.TestCase):
    def test_tables_are_cells_and_headings_are_skipped(self):
        body = ("Текст\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n# Заголовок\n\n"
                "Абзац\n| c | d |\n|---|---|\n| 3 | 4 |")
        self.assertEqual(core._md_blocks(body),
                         (["Текст", "Абзац"], ["a", "b", "1", "2", "c", "d", "3", "4"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestConfirmedBugs(unittest.TestCase):
    def test_mixed_case_http_equiv_is_a_redirect(self):
        stub = page(f"{SITE}/a/", raw='<html><head><meta HTTP-equiv="Refresh" '
                                      'content="0; url=/b/"></head><body></body></html>')
        self.assertTrue(checks.redirect_target(stub))

    def test_a_menu_before_main_is_not_a_list_of_the_article(self):
        root = tempfile.mkdtemp(prefix="indexgap-nav-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html><head><title>T</title></head><body><nav><ul><li>a</li><li>b</li>"
                     "</ul></nav><main><p>text</p></main></body></html>")
        self.assertEqual(core.load_pages(root, SITE)[0][0].blocks["li"], 0)
