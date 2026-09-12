# -*- coding: utf-8 -*-
"""RTL-вопросы: знак U+061F не должен превращать восемь вопросов в ноль.

Фикстуры воспроизводят девять авторских заголовков визового гайда на ar/fa/ur:
восемь вопросов и один пример. Вместе с обвязкой страницы было 23 H2/H3.
Порог 30% остаётся прежним; один вопрос не освобождает всю страницу от проверки.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from html import escape
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import language  # noqa: F401 — фиксирует язык диагностик
from indexgap import aeo, core

BODY_HEADINGS = {
    "ar": [
        "هل يمكن للمرأة السفر إلى سنغافورة بمفردها؟",
        "هل تُرفض طلبات غير المتزوجات بمعدل أعلى؟",
        "هل يلزم زوج مرافق أو موافقة الوالدين أو شهادة زواج؟",
        "ما الذي ينبغي مراجعته قبل تقديم Form 14A؟",
        "كيف يمكن شرح رحلة فردية بوضوح؟",
        "هل ينبغي كتابة خطاب توضيحي؟",
        "ما الذي ينبغي تجهيزه قبل الوصول؟",
        "من رفض: خدمة تقديم الطلب أم ICA أم شركة الطيران؟",
        "مثال: أول عطلة دون مرافق ودون خطاب من جهة العمل"
    ],
    "fa": [
        "آیا یک زن می‌تواند به‌تنهایی به سنگاپور سفر کند؟",
        "آیا درخواست زنان مجرد بیشتر رد می‌شود؟",
        "آیا همراهی همسر، رضایت والدین یا سند ازدواج لازم است؟",
        "پیش از ارسال Form 14A چه چیزهایی را بررسی کنید؟",
        "چگونه سفر تنهایی را روشن توضیح دهید؟",
        "آیا نامه توضیحی بنویسید؟",
        "برای زمان ورود چه چیزهایی آماده داشته باشید؟",
        "چه کسی نپذیرفته است: خدمات ارسال درخواست، ICA یا شرکت هواپیمایی؟",
        "مثال: نخستین سفر تنهایی بدون نامه اشتغال"
    ],
    "ur": [
        "کیا خاتون اکیلے سنگاپور جا سکتی ہیں؟",
        "کیا غیر شادی شدہ خواتین کی درخواستیں زیادہ مسترد ہوتی ہیں؟",
        "کیا شوہر کی ہمراہی، والدین کی اجازت یا شادی کا سرٹیفکیٹ چاہیے؟",
        "Form 14A جمع کرانے سے پہلے کیا جانچیں؟",
        "اکیلے سفر کا منصوبہ واضح کیسے کریں؟",
        "کیا وضاحتی خط لکھنا چاہیے؟",
        "آمد کے لیے کیا تیار رکھیں؟",
        "انکار کس نے کیا: درخواست کی خدمت نے، ICA نے یا فضائی کمپنی نے؟",
        "مثال: پہلی بار اکیلے تعطیلات پر جانا، ملازمت کا خط نہ ہونا"
    ]
}


class TestRtlQuestionHeadings(unittest.TestCase):
    def page(self, headings, lang="en", chrome=0, entity=False):
        with tempfile.TemporaryDirectory(prefix="indexgap-rtl-headings-") as root:
            path = Path(root) / "index.html"
            h2 = "".join("<h2>" + escape(h) + "</h2><p>Answer text.</p>" for h in headings)
            if entity:
                h2 = h2.replace("؟", "&#x061F;")
            path.write_text(
                f'<html lang="{lang}"><head><title>Guide</title></head>'
                f'<body><main><h1>Guide</h1>{h2}</main><footer>'
                + "<h2>Navigation</h2>" * chrome + "</footer></body></html>",
                encoding="utf-8")
            return core.load_page(str(path), root, "https://example.com")

    def codes(self, page):
        return [issue[2] for issue in aeo.check_extractable(page)]

    def test_rendered_rtl_body_questions_clear_the_existing_share_threshold(self):
        for lang, headings in BODY_HEADINGS.items():
            with self.subTest(lang=lang):
                page = self.page(headings, lang, chrome=14)
                subheads = [text for level, text in page.headings if level >= 2]
                self.assertEqual(len(headings), 9)
                self.assertEqual(len(subheads), 23)
                self.assertEqual(sum(bool(aeo.QUESTION.search(h)) for h in subheads), 8)
                self.assertNotIn("no-question-headings", self.codes(page))

    def test_rtl_question_html_entity_is_decoded_before_the_check(self):
        page = self.page(BODY_HEADINGS["ur"], "ur", chrome=14, entity=True)
        self.assertNotIn("no-question-headings", self.codes(page))

    def test_ascii_and_fullwidth_question_marks_remain_supported(self):
        for lang, headings in {
            "en": ["Visa documents?", "Permitted route?", "Who decides entry?"],
            "zh": ["需要哪些文件？", "可以独自旅行吗？", "谁决定入境？"],
        }.items():
            with self.subTest(lang=lang):
                self.assertNotIn("no-question-headings", self.codes(self.page(headings, lang)))

    def test_declarative_rtl_headings_still_report_a_low_question_share(self):
        for lang, headings in BODY_HEADINGS.items():
            with self.subTest(lang=lang):
                page = self.page([h.rstrip("؟") for h in headings], lang)
                self.assertIn("no-question-headings", self.codes(page))

    def test_one_rtl_question_does_not_disable_the_share_check(self):
        for lang, headings in BODY_HEADINGS.items():
            with self.subTest(lang=lang):
                page = self.page([headings[0]] + [h.rstrip("؟") for h in headings[1:]], lang)
                self.assertIn("no-question-headings", self.codes(page))

    def test_question_mark_inside_a_declarative_heading_is_not_enough(self):
        self.assertFalse(aeo.QUESTION.search("علامة ؟ داخل النص وليست في نهايته"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
