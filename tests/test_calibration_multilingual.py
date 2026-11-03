# -*- coding: utf-8 -*-
"""
Что нашёл прогон по живому многоязычному сайту (multilingual-site.example,
4000+ страниц на десяти языках), и то, что сделано вслед за ним.

Каждый тест — случай с того сайта или его прямое обобщение:
вопросы без «?» на хинди, арабском и китайском; закрытые и убранные из
sitemap страницы, которые числились критичными; адрес из sitemap, который
отчёт показывал без `www`; журнал запросов Vercel, который разборщик логов
не читал; языки одной письменности — индонезийский и малайский, арабский,
фарси и урду.
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
from indexgap import aeo, checks, cli, core, crawlers, doctor, langid, signals

SITE = "https://www.example.com"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class TestQuestionsInEveryLanguage(unittest.TestCase):
    QUESTIONS = [
        "Apa sebenarnya yang dilihat ICA",           # ms, с сайта
        "ICA वास्तव में क्या देख रहा है",            # hi, слово в середине
        "أين ستقيم",                                 # ar, без ؟
        "您将住在哪里",                               # zh
        "ICA 实际在看什么",
        "কীভাবে আবেদন করবেন",                        # bn
        "Bagaimana cara mengisi formulir",           # id
        "Wie lange dauert das Visum",                # de
        "Cómo pedir la visa",                        # es
        "Сколько стоит виза",
        "ビザはどうやって申請しますか",
        "비자는 어떻게 신청하나요",
        "Tetapi bagaimana jika visa ditolak?",
    ]
    STATEMENTS = [
        "Jawaban singkat", "संक्षिप्त उत्तर", "تذكرة العودة أو المغادرة", "简短回答",
        "Submit within three days of arrival", "Tiket pulang atau tiket sambungan anda",
        "Come prepared", "من الهند إلى سنغافورة", "Documents required", "Kemana saja",
    ]

    def test_questions_are_seen(self):
        for text in self.QUESTIONS:
            with self.subTest(text):
                self.assertTrue(aeo.QUESTION.search(text))

    def test_statements_are_not_questions(self):
        """«من» — и «кто», и «из»; «Come» — английский глагол, а не итальянское «как»."""
        for text in self.STATEMENTS:
            with self.subTest(text):
                self.assertFalse(aeo.QUESTION.search(text))


class TestLanguageId(unittest.TestCase):
    TEXTS = {
        "en": "The application is checked by the team and you will receive the result "
              "within three working days, so please keep your passport ready for the "
              "next step of the process and check the official notice.",
        "de": "Der Antrag wird vom Team geprüft und Sie erhalten das Ergebnis innerhalb "
              "von drei Werktagen, deshalb halten Sie bitte Ihren Reisepass für den "
              "nächsten Schritt bereit und prüfen Sie die Mitteilung.",
        "id": "Permohonan Anda akan diperiksa oleh tim kami dan Anda bisa periksa status "
              "di kantor karena formulir harus lengkap. Silakan siapkan paspor Anda "
              "setelah pembayaran selesai dan tunggu rincian dari tim.",
        "ms": "Permohonan anda akan disemak oleh pasukan kami dan anda boleh semak status "
              "di pejabat kerana borang perlu lengkap. Sila sediakan pasport anda selepas "
              "bayaran selesai dan tunggu butiran daripada pasukan.",
        "ar": "يجب على المسافر أن يتحقق من الشروط التي تحددها السلطات قبل السفر إلى "
              "سنغافورة، كما يمكن أن يطلب منه تقديم ما يثبت الحجز في الفندق عند الوصول "
              "إلى نقطة التفتيش في المطار وهذا مهم.",
        "fa": "مسافر باید پیش از سفر به سنگاپور شرایط را بررسی کند و برای این کار "
              "می تواند از سایت رسمی استفاده کند. شما باید رزرو هتل و بلیط بازگشت را "
              "آماده داشته باشید تا در فرودگاه مشکلی نباشد.",
        "ur": "مسافر کو سنگاپور جانے سے پہلے شرائط کی جانچ کرنی چاہیے اور اس کے لیے "
              "سرکاری ویب سائٹ کا استعمال کیا جا سکتا ہے۔ آپ کو ہوٹل کی بکنگ اور واپسی "
              "کا ٹکٹ ساتھ رکھنا ہے تاکہ ایئرپورٹ پر کوئی مسئلہ نہ ہو۔",
        "hi": "यात्री को सिंगापुर जाने से पहले शर्तों की जांच करनी चाहिए और इसके लिए "
              "आप आधिकारिक वेबसाइट का उपयोग कर सकते हैं। आपको होटल की बुकिंग और वापसी "
              "का टिकट साथ में रखना है ताकि हवाई अड्डे पर कोई समस्या न हो।",
    }

    def test_each_language_is_named(self):
        for lang, text in self.TEXTS.items():
            with self.subTest(lang):
                self.assertEqual(langid.identify(text * 2)[0], lang)

    def test_indic_words_are_whole(self):
        """Знак гласной — отдельный символ: «रुपये» не должно резаться на «र», «प»."""
        self.assertIn("रुपये", langid.tokens("इस योजना की कीमत ३५०० रुपये है"))

    def test_too_little_text_is_no_verdict(self):
        self.assertEqual(langid.identify("Hello world")[0], "")

    def test_mismatch_only_for_known_languages(self):
        self.assertEqual(langid.mismatch("de-DE", self.TEXTS["en"] * 2), "en")
        self.assertEqual(langid.mismatch("de", self.TEXTS["de"] * 2), "")
        self.assertEqual(langid.mismatch("xx", self.TEXTS["en"] * 2), "")


class Pages(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-multi-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def page(self, rel, lang, body, head=""):
        write(os.path.join(self.dir, rel),
              f'<html lang="{lang}"><head><title>{rel} — достаточно длинный заголовок</title>'
              f'{head}</head><body><main>{body}</main></body></html>')

    def load(self):
        pages, _ = core.load_pages(self.dir, SITE)
        return pages


class TestUntranslatedBody(Pages):
    def test_same_script_other_language_is_named(self):
        text = TestLanguageId.TEXTS
        self.page("de/a/index.html", "de", f"<p>{text['en'] * 3}</p>")
        self.page("de/b/index.html", "de", f"<p>{text['de'] * 3}</p>")
        self.page("ms/a/index.html", "ms", f"<p>{text['id'] * 3}</p>")
        self.page("ms/b/index.html", "ms", f"<p>{text['ms'] * 3}</p>")
        self.page("fa/a/index.html", "fa", f"<p>{text['ar'] * 3}</p>")
        got = {p.url: [i[2] for i in signals.lang_script([p])] for p in self.load()}
        flagged = sorted(u for u, codes in got.items() if "lang-text-mismatch" in codes)
        self.assertEqual(flagged, [SITE + "/de/a/", SITE + "/fa/a/", SITE + "/ms/a/"])

    def test_latin_alts_in_another_language(self):
        alt = "Apartment in Berlin near the main station with a view of the river"
        self.page("de/a/index.html", "de",
                  f'<p>x</p><img src=a.jpg alt="{alt}"><img src=b.jpg alt="{alt}">')
        page = self.load()[0]
        self.assertIn("img-alt-language", [i[2] for i in aeo.check_alt_text(page)])


class TestClosedAndOffTheMap(unittest.TestCase):
    def test_closed_and_off_the_sitemap_is_a_decision(self):
        issues = [("critical", SITE + "/legal", "noindex", "закрыта"),
                  ("critical", SITE + "/kept", "noindex", "закрыта")]
        got = checks.closed_off_map(issues, [SITE + "/kept"])
        levels = {i[1]: i[0] for i in got}
        self.assertEqual(levels, {SITE + "/legal": "info", SITE + "/kept": "critical"})

    def test_without_a_sitemap_nothing_changes(self):
        issues = [("critical", SITE + "/legal", "noindex", "закрыта")]
        self.assertEqual(checks.closed_off_map(issues, None), issues)


class TestStaleSitemapShownAsWritten(Pages):
    def test_www_is_kept(self):
        self.page("en/a/index.html", "en", "<p>text</p>")
        pages = self.load()
        result = doctor.funnel(pages, [SITE + "/en/a/", SITE + "/en/start"])
        self.assertEqual(result["stale_in_sitemap_urls"], [SITE + "/en/start"])


class TestVercelLogs(unittest.TestCase):
    def test_log_drain_record(self):
        line = json.dumps({
            "id": "1", "source": "edge", "path": "/api/x", "statusCode": -1,
            "proxy": {"method": "GET", "host": "www.example.com", "path": "/en/guide/a",
                      "userAgent": ["Mozilla/5.0 (compatible; OAI-SearchBot/1.0)"],
                      "statusCode": 200, "clientIp": "20.171.207.1"}})
        hit = crawlers.parse_line(line)
        self.assertEqual((hit["target"], hit["status"], hit["ip"]),
                         ("/en/guide/a", 200, "20.171.207.1"))
        self.assertEqual(crawlers.identify(hit["ua"])[0], "OAI-SearchBot")


class TestVerifyBots(unittest.TestCase):
    def logs(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "a.log")
        write(path, "\n".join([
            '20.171.207.1 - - [x] "GET /a/ HTTP/1.1" 200 1 "-" "Mozilla/5.0; compatible; GPTBot/1.2"',
            '6.6.6.6 - - [x] "GET /b/ HTTP/1.1" 200 1 "-" "Mozilla/5.0; compatible; GPTBot/1.2"',
            '66.249.66.1 - - [x] "GET /c/ HTTP/1.1" 200 1 "-" "Mozilla/5.0 (compatible; Googlebot/2.1)"',
            '1.2.3.4 - - [x] "GET /d/ HTTP/1.1" 200 1 "-" "Mozilla/5.0 (compatible; ClaudeBot/1.0)"',
        ]) + "\n")
        return crawlers.read_logs([path], "https://e.com")

    def test_ranges_dns_and_unverifiable(self):
        def fetch(url):
            if "gptbot" in url:
                return {"prefixes": [{"ipv4Prefix": "20.171.206.0/23"}]}
            raise OSError("offline")
        verdicts = crawlers.verify(self.logs(), fetch=fetch,
                                   rdns=lambda ip, domains: ip == "66.249.66.1")
        spoofed = verdicts.pop("_spoofed")
        self.assertEqual(spoofed, {("GPTBot", "6.6.6.6")})
        self.assertEqual(verdicts["Googlebot"]["method"], "dns")
        self.assertEqual(verdicts["Googlebot"]["genuine"], 1)
        self.assertEqual(verdicts["ClaudeBot"]["unknown"], 1)

    def test_spoofed_requests_are_dropped(self):
        logs = self.logs()
        clean = crawlers.without_spoofed(logs, {("GPTBot", "6.6.6.6")})
        self.assertEqual(sorted(clean["bots"]["GPTBot"]["pages"]), ["//e.com/a"])
        self.assertEqual(len(logs["bots"]["GPTBot"]["pages"]), 2)


class TestDoctorBaseline(Pages):
    def run_doctor(self, sitemap, out, *extra):
        sm = os.path.join(self.dir + "-sm.xml")
        self.addCleanup(lambda: os.path.exists(sm) and os.remove(sm))
        write(sm, '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + "".join(f"<url><loc>{u}</loc></url>" for u in sitemap) + "</urlset>")
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            code = cli.main(["doctor", self.dir, "--site", SITE, "--sitemap", sm,
                             "--out", out, *extra])
        return code, buf.getvalue()

    def test_what_dropped_since_last_run(self):
        for section in ("rent", "buy"):
            for i in range(8):
                self.page(f"{section}/p{i}/index.html", "en", f"<p>{section} {i}</p>")
        self.page("index.html", "en", "<p>home</p>")
        everything = [p.url for p in self.load()]
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        first = os.path.join(root, "r1.html")
        code, _ = self.run_doctor(everything, first)
        self.assertEqual(code, 0)
        dropped = [u for u in everything if "/rent/" in u][:6]
        code, out = self.run_doctor([u for u in everything if u not in dropped],
                                    os.path.join(root, "r2.html"),
                                    "--baseline", os.path.join(root, "r1.json"))
        self.assertEqual(code, 0, out)
        self.assertIn("С прошлого прогона", out)
        self.assertIn("Выпали из sitemap (6)", out)
        self.assertIn("Новые разрывы по разделам: /rent/", out)
        with open(os.path.join(root, "r2.json"), encoding="utf-8") as fh:
            trend = json.load(fh)["baseline"]
        self.assertEqual(len(trend["newly_off_sitemap"]), 6)
        self.assertEqual(trend["segments"]["new_gaps"], ["/rent/"])

    def test_a_file_that_is_not_a_doctor_run(self):
        path = os.path.join(self.dir, "x.json")
        write(path, json.dumps({"issues": []}))
        with self.assertRaises(core.SourceError):
            doctor.load_run(path)

    def test_nothing_changed_is_said(self):
        current = {"site": SITE, "funnel": {"steps": [{"id": "generated", "count": 3}]}}
        trend = doctor.compare_runs(current, current)
        self.assertEqual(trend["steps"], [])
        self.assertEqual(trend["newly_not_indexed"], [])


class TestCountingWordsInOtherLanguages(unittest.TestCase):
    def test_counting_words_are_not_facts(self):
        from indexgap import content
        for text in ("Folgen Sie diesen 3 Schritte", "Siga estos 5 pasos", "Ikuti 4 langkah ini",
                     "Suivez ces 3 étapes", "Termin am 15 Januar"):
            with self.subTest(text):
                self.assertEqual(content._generic_numbers_in(text), {}, text)

    def test_real_facts_still_are(self):
        from indexgap import content
        self.assertIn("12", content._generic_numbers_in("Wir sind seit 12 Jahren am Markt"))


if __name__ == "__main__":
    unittest.main()
