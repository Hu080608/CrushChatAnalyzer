import json
import unittest

from crush_analyzer.config import AppConfig
from crush_analyzer.deepseek import DeepSeekClient, DeepSeekError, parse_usage
from crush_analyzer.prompts import extract_json_object, parse_reply_suggestions


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload, ensure_ascii=False)

    def json(self):
        return self._payload


class DeepSeekTests(unittest.TestCase):
    def test_endpoint_normalization(self):
        cfg = AppConfig(api_key="sk-test", base_url="https://api.deepseek.com")
        self.assertEqual(DeepSeekClient(cfg).endpoint(), "https://api.deepseek.com/chat/completions")
        cfg2 = AppConfig(api_key="sk-test", base_url="https://example.com/v1")
        self.assertEqual(DeepSeekClient(cfg2).endpoint(), "https://example.com/v1/chat/completions")

    def test_chat_response(self):
        payload = {
            "model": "deepseek-chat",
            "choices": [{"message": {"content": "连接成功"}}],
            "usage": {"total_tokens": 3},
        }
        captured = {}

        def fake_post(url, request_payload, timeout):
            captured["url"] = url
            captured["payload"] = request_payload
            captured["timeout"] = timeout
            return FakeResponse(200, payload)

        cfg = AppConfig(api_key="sk-test")
        client = DeepSeekClient(cfg)
        client._post_json = fake_post  # type: ignore[method-assign]
        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result, "连接成功")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["payload"]["model"], "deepseek-chat")
        self.assertTrue(client.last_usage_info.total_tokens >= 0)

    def test_error_401(self):
        payload = {"error": {"message": "bad key"}}

        def fake_post(url, request_payload, timeout):
            return FakeResponse(401, payload, text='{"error":{"message":"bad key"}}')

        client = DeepSeekClient(AppConfig(api_key="sk-bad"))
        client._post_json = fake_post  # type: ignore[method-assign]
        with self.assertRaises(DeepSeekError) as ctx:
            client.chat([{"role": "user", "content": "hi"}], retries=0)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("API Key", ctx.exception.user_message)

    def test_parse_reply_suggestions(self):
        text = """```json
        {"read_the_room":"对方有兴趣","replies":[
          {"style":"自然接话","text":"哈哈，那下次一起？","reason":"推进","risk":"低"}
        ]}
        ```"""
        read, replies = parse_reply_suggestions(text)
        self.assertEqual(read, "对方有兴趣")
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["text"], "哈哈，那下次一起？")

    def test_extract_json_object_bad(self):
        self.assertIsNone(extract_json_object("not json"))

    def test_parse_usage_cost(self):
        cfg = AppConfig(
            api_key="sk-test",
            price_input_cache_hit=0.5,
            price_input_cache_miss=2.0,
            price_output=8.0,
            price_unit=1_000_000,
        )
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "prompt_cache_hit_tokens": 200,
            "prompt_cache_miss_tokens": 800,
        }
        info = parse_usage(usage, cfg, model="deepseek-chat")
        self.assertEqual(info.input_tokens, 1000)
        self.assertEqual(info.total_tokens, 1500)
        expected = 200 / 1_000_000 * 0.5 + 800 / 1_000_000 * 2.0 + 500 / 1_000_000 * 8.0
        self.assertAlmostEqual(info.cost, expected, places=8)
        self.assertIn("tokens", info.format_short())


if __name__ == "__main__":
    unittest.main()
