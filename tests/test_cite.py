# -*- coding: utf-8 -*-
"""
Замер цитируемости в ИИ-поиске.

Это единственная часть пакета, которой нужны ключи и деньги, и первая, которая
ходит в чужие платные API. Поэтому здесь проверяется не столько «считает ли»,
сколько три обещания, нарушение которых стоит человеку денег или доверия:

  * без `--send` не уходит ни один запрос;
  * без ключей — понятное объяснение, а не трейсбек и не молчаливый ноль;
  * в отчёте доля прогонов, а не «да/нет»: ответ недетерминирован, и один
    прогон не отличает «нас цитируют» от «повезло».

И отдельно — что нигде не написано «вас цитирует ChatGPT». Замерен API,
а это не то же самое, что приложение.
"""

import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import cite, cli
from indexgap.core import SourceError

NO_KEYS = {k: "" for k in ("OPENAI_API_KEY", "PERPLEXITY_API_KEY",
                           "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY")}


def answer(urls, text=""):
    """Ответ провайдера в общей форме: адреса лежат где угодно в JSON."""
    return {"output": [{"content": [{"text": text, "annotations": [
        {"type": "url_citation", "url": u} for u in urls]}]}]}


class TestNothingLeavesWithoutSend(unittest.TestCase):
    def run_cli(self, argv, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**NO_KEYS, **(env or {})}), \
                mock.patch.object(sys, "stdout", out):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_dry_run_makes_no_request_at_all(self):
        with mock.patch("urllib.request.urlopen") as opened:
            code, out = self.run_cli(
                ["cite", "--domain", "example.com", "--prompt", "вопрос",
                 "--lang", "ru"],
                env={"PERPLEXITY_API_KEY": "x"})
        self.assertEqual(code, 0)
        opened.assert_not_called()
        self.assertIn("пробный прогон", out)

    def test_it_says_how_many_calls_it_would_cost(self):
        _, out = self.run_cli(
            ["cite", "--domain", "example.com", "--prompt", "a", "--prompt", "b",
             "--runs", "4", "--lang", "ru"], env={"XAI_API_KEY": "x"})
        self.assertIn("8", out)          # 2 вопроса × 1 провайдер × 4 прогона

    def test_no_keys_is_explained_not_crashed(self):
        code, out = self.run_cli(
            ["cite", "--domain", "example.com", "--prompt", "вопрос",
             "--lang", "ru"])
        self.assertEqual(code, 2)
        self.assertIn("PERPLEXITY_API_KEY", out)
        self.assertIn("OPENAI_API_KEY", out)

    def test_no_questions_is_explained(self):
        """Без вопросов замерять нечего — и это объяснение, а не пустой отчёт."""
        code, _ = self.run_cli(["cite", "--domain", "example.com", "--lang", "ru"],
                               env={"XAI_API_KEY": "x"})
        self.assertEqual(code, 2)

    def test_a_missing_prompts_file_is_a_message_not_a_traceback(self):
        code, _ = self.run_cli(
            ["cite", "--domain", "example.com", "--prompts", "/nope.txt",
             "--lang", "ru"], env={"XAI_API_KEY": "x"})
        self.assertEqual(code, 2)


class TestMeasurement(unittest.TestCase):
    def setUp(self):
        self.env = {**NO_KEYS, "PERPLEXITY_API_KEY": "x"}

    def test_a_share_not_a_yes_or_no(self):
        """
        Два прогона из четырёх — это 50%, и разница с 4 из 4 видна только так.
        """
        replies = [answer(["https://example.com/a"]), answer(["https://rival.com/"]),
                   answer(["https://example.com/b"]), answer(["https://rival.com/"])]
        with mock.patch.object(cite, "ask", side_effect=[
                {"urls": [u["url"] for u in r["output"][0]["content"][0]["annotations"]],
                 "text": ""} for r in replies]):
            got = cite.measure(["вопрос"], "example.com", providers=["perplexity"],
                               runs=4, env=self.env, pause=0)
        row = got["results"][0]
        self.assertEqual(row["cited"], 2)
        self.assertEqual(row["runs"], 4)
        self.assertAlmostEqual(row["cited_share"], 0.5)

    def test_subdomains_count_as_ours(self):
        with mock.patch.object(cite, "ask", return_value={
                "urls": ["https://blog.example.com/post"], "text": ""}):
            got = cite.measure(["q"], "example.com", providers=["perplexity"],
                               runs=1, env=self.env, pause=0)
        self.assertEqual(got["results"][0]["cited"], 1)

    def test_a_similar_looking_domain_is_not_ours(self):
        """`notexample.com` не наш, хотя и заканчивается на наше имя."""
        with mock.patch.object(cite, "ask", return_value={
                "urls": ["https://notexample.com/"], "text": ""}):
            got = cite.measure(["q"], "example.com", providers=["perplexity"],
                               runs=1, env=self.env, pause=0)
        self.assertEqual(got["results"][0]["cited"], 0)

    def test_who_was_cited_instead(self):
        with mock.patch.object(cite, "ask", return_value={
                "urls": ["https://rival.com/a", "https://other.com/b"], "text": ""}):
            got = cite.measure(["q"], "example.com", providers=["perplexity"],
                               runs=2, env=self.env, pause=0)
        rivals = dict(got["results"][0]["top_competitors"])
        self.assertEqual(rivals["rival.com"], 2)

    def test_brand_mention_without_a_link_is_counted_separately(self):
        """Упомянули без ссылки — это не цитирование, но и не ничто."""
        with mock.patch.object(cite, "ask", return_value={
                "urls": ["https://rival.com/"], "text": "по данным VisatoSingapore…"}):
            got = cite.measure(["q"], "example.com", brand="VisatoSingapore",
                               providers=["perplexity"], runs=1, env=self.env,
                               pause=0)
        row = got["results"][0]
        self.assertEqual(row["cited"], 0)
        self.assertEqual(row["brand_mentions"], 1)

    def test_one_provider_failing_does_not_lose_the_rest(self):
        calls = {"n": 0}

        def flaky(name, prompt, cfg=None, env=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SourceError("сервис прилёг")
            return {"urls": ["https://example.com/a"], "text": ""}

        with mock.patch.object(cite, "ask", side_effect=flaky):
            got = cite.measure(["q"], "example.com", providers=["perplexity"],
                               runs=3, env=self.env, pause=0)
        row = got["results"][0]
        self.assertEqual(row["failed"], 1)
        self.assertEqual(row["runs"], 2)
        self.assertTrue(got["errors"])

    def test_urls_are_found_wherever_the_provider_hides_them(self):
        """
        Форма ответа у четырёх сервисов разная и меняется. Собираем адреса
        отовсюду, а не по четырём путям, которые придётся чинить каждый квартал.
        """
        shapes = [
            {"citations": ["https://example.com/a"]},
            {"output": [{"content": [{"annotations": [
                {"url": "https://example.com/a"}]}]}]},
            {"steps": [{"content": [{"annotations": [
                {"type": "url_citation", "url": "https://example.com/a"}]}]}]},
            {"search_results": [{"url": "https://example.com/a", "title": "t"}]},
        ]
        for shape in shapes:
            self.assertIn("https://example.com/a", cite._urls_anywhere(shape), shape)

    def test_a_domain_is_required(self):
        with self.assertRaises(SourceError):
            cite.measure(["q"], "", providers=["perplexity"], env=self.env)


class TestHonesty(unittest.TestCase):
    def test_the_notes_never_claim_the_product(self):
        text = " ".join(cite.notes_for(sorted(cite.PROVIDERS)))
        self.assertIn("API, а не приложение", text)
        self.assertIn("недетерминирован", text)
        # Ни одна оговорка не должна обещать цитирование как результат правок.
        self.assertIn("0,19", text)

    def test_every_provider_is_labelled_as_api_where_it_matters(self):
        self.assertEqual(cite.PROVIDERS["openai"]["title"], "ChatGPT (API)")
        self.assertEqual(cite.PROVIDERS["gemini"]["title"], "Gemini (API)")

    def test_keys_are_read_from_the_environment_and_never_stored(self):
        """Ключ не должен попадать ни в конфиг, ни в отчёт."""
        with mock.patch.dict(os.environ, {**NO_KEYS, "XAI_API_KEY": "секрет"}):
            with mock.patch.object(cite, "ask", return_value={
                    "urls": [], "text": ""}):
                got = cite.measure(["q"], "example.com", providers=["xai"],
                                   runs=1, pause=0)
        self.assertNotIn("секрет", json.dumps(got, ensure_ascii=False))


class TestPromptsFromKeywords(unittest.TestCase):
    def test_questions_come_from_the_keyword_column(self):
        rows = [{"keyword": "виза в сингапур"}, {"keyword": "виза в сингапур"},
                {"keyword": "sg arrival card"}]
        self.assertEqual(cite.prompts_from_keywords(rows, "keyword"),
                         ["виза в сингапур", "sg arrival card"])

    def test_the_limit_is_respected(self):
        rows = [{"keyword": f"ключ {i}"} for i in range(50)]
        self.assertEqual(len(cite.prompts_from_keywords(rows, "keyword", 5)), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
