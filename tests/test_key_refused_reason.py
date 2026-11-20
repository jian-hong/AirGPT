"""A refused key must read as refused on EVERY browser, not only the one that saw it.

The server used to say only "(cooldown)" after a provider refused a key, and the page
remembered "refused" in one browser's localStorage. The phone then told the owner to
"wait a minute" while the key stayed wrong. Now the server records why, says it in the
error text, keeps it inside the chat error's length cut, and forgets it when a new key is
saved for that provider.
"""
from __future__ import annotations

import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import ai_engine  # noqa: E402


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, {401: "Unauthorized", 429: "Too Many Requests"}.get(code, "err"), {}, None)


class KeyRefusedReasonTest(unittest.TestCase):
    def setUp(self):
        ai_engine._provider_cooldown.clear()
        ai_engine._provider_reason.clear()
        self.env = {"GROQ_API_KEY": "gsk_bad"}
        p = mock.patch.object(ai_engine, "load_env", lambda: dict(self.env))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(ai_engine._provider_cooldown.clear)
        self.addCleanup(ai_engine._provider_reason.clear)

    def _fail(self, code):
        def post(url, headers, body, timeout=12):
            raise _http_error(code)
        return mock.patch.object(ai_engine, "_http_post", post)

    def _err(self):
        with self.assertRaises(RuntimeError) as cm:
            ai_engine._standard_llm("hi", "")
        return str(cm.exception)

    def test_second_call_still_says_key_refused(self):
        with self._fail(401):
            first = self._err()
            second = self._err()  # the provider is cooling down now
        self.assertIn("HTTP Error 401", first)
        self.assertIn("groq-oss-120b(key refused)", second)
        self.assertNotIn("(cooldown)", second.split("Groq")[0])

    def test_rate_limit_says_why_and_is_not_a_refused_key(self):
        with self._fail(429):
            self._err()
            second = self._err()
        self.assertIn("groq-oss-120b(cooldown, rate limited)", second)
        self.assertNotIn("key refused", second)

    def test_refusal_survives_the_error_cut(self):
        # many providers, a long chain: the refusal must sit inside the first 280 chars
        self.env.update({k: "x" for k in ("OPENROUTER_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY",
                                          "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SEA_LION_API_KEY")})
        def post(url, headers, body, timeout=12):
            raise _http_error(401 if "groq" in url else 500)
        with mock.patch.object(ai_engine, "_http_post", post):
            self._err()
            second = self._err()
        self.assertIn("key refused", second[:280])

    def test_saving_a_key_clears_that_providers_cooldown_only(self):
        with self._fail(401):
            self._err()
        ai_engine._provider_cooldown["google"] = ai_engine._provider_cooldown["groq-oss-120b"]
        cleared = ai_engine.clear_cooldown_for_keys({"GROQ_API_KEY": "gsk_new"})
        self.assertIn("groq-oss-120b", cleared)
        self.assertFalse(ai_engine._provider_hot("groq-oss-120b"))
        self.assertTrue(ai_engine._provider_hot("google"))
        calls = []
        def post(url, headers, body, timeout=12):
            calls.append(headers.get("Authorization"))
            return {"choices": [{"message": {"content": "hello"}}]}
        self.env["GROQ_API_KEY"] = "gsk_new"
        with mock.patch.object(ai_engine, "_http_post", post):
            text, model = ai_engine._standard_llm("hi", "")
        self.assertEqual(text, "hello")
        self.assertEqual(calls, ["Bearer gsk_new"])


if __name__ == "__main__":
    unittest.main()
