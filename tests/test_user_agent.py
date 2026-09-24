# -*- coding: utf-8 -*-
"""
Каждый сетевой запрос пакета представляется своим именем.

Без заголовка urllib шлёт `Python-urllib/3.x`, и многие WAF режут такой агент
по умолчанию. На rumors.app sitemap по адресу отдавал 403 — а `curl` и честный
`indexgap/1.7.0 (+ссылка)` получали 200. Пакет сообщал «sitemap не прочитан»,
и человек думал, что сломан сайт.

Под браузер пакет не маскируется: сайт вправе знать, кто пришёл, и вправе
отказать. Представиться — это и вежливо, и проходит.
"""

import io
import json
import unittest
from unittest import mock

import language  # noqa: F401  — закрепляет русский язык вывода
from indexgap import cite, core, doctor, engines, publish, __version__


class Capture:
    """Подменяет urlopen и запоминает, с каким заголовком пришли."""

    def __init__(self, body=b""):
        self.agents, self.body = [], body

    def __call__(self, request, timeout=None):
        agent = (request.get_header("User-agent") if hasattr(request, "get_header")
                 else None)
        self.agents.append(agent)
        response = mock.MagicMock()
        response.read.return_value = self.body
        response.status = 200
        response.__enter__.return_value = response
        return response


class TestUserAgent(unittest.TestCase):
    def assert_named(self, capture):
        self.assertTrue(capture.agents, "запрос не ушёл")
        for agent in capture.agents:
            self.assertTrue(agent and agent.startswith(f"indexgap/{__version__}"), agent)
            self.assertNotIn("Python-urllib", agent)

    def test_the_agent_names_the_package_and_where_to_find_it(self):
        self.assertIn(__version__, core.USER_AGENT)
        self.assertIn("github.com", core.USER_AGENT)

    def test_sitemap(self):
        capture = Capture(b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                          b'<url><loc>https://example.com/a</loc></url></urlset>')
        with mock.patch("urllib.request.urlopen", capture):
            doctor.read_sitemap("https://example.com/sitemap.xml")
        self.assert_named(capture)

    def test_indexnow_registry(self):
        capture = Capture(json.dumps({"bing": {"url": "https://www.bing.com/indexnow"}}).encode())
        import tempfile
        with tempfile.TemporaryDirectory() as empty, \
                mock.patch("urllib.request.urlopen", capture):
            engines.fetch_participants(cache_path_dir=empty)
        self.assert_named(capture)

    def test_indexnow_submission(self):
        capture = Capture(b"")
        with mock.patch("urllib.request.urlopen", capture):
            publish.submit_indexnow(["https://example.com/a"], "https://example.com",
                                    "k" * 32, dry_run=False)
        self.assert_named(capture)

    def test_ai_apis(self):
        capture = Capture(b"{}")
        with mock.patch("urllib.request.urlopen", capture):
            cite._post("https://api.example.com/v1", {"q": 1}, {"Authorization": "Bearer x"})
        self.assert_named(capture)


if __name__ == "__main__":
    unittest.main()
