import unittest
from datetime import datetime, timedelta

from crush_analyzer.auto_reply import AutoReplyService
from crush_analyzer.config import AppConfig
from crush_analyzer.models import Message


def run_tick_after_quiet(service, client, known):
    service._tick(client, known)
    service._pending_last_at = datetime.now() - timedelta(seconds=10)
    service._tick(client, known)


class FakeBackend:
    connected = True

    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    def fetch_messages(self, chat="", limit=200):
        return list(self.messages)

    def send_message(self, chat, text):
        self.sent.append((chat, text))


class FakeClient:
    def auto_reply(self, session, incoming=None, persona="", style=""):
        return "好呀，周末一起？"


class AutoReplyTests(unittest.TestCase):
    def test_tick_sends_when_not_dry_run(self):
        config = AppConfig(
            api_key="sk-test",
            wechat_self_name="我",
            auto_reply_dry_run=False,
            auto_reply_skip_keywords="验证码,转账",
        )
        backend = FakeBackend([Message("对方", "周末有空吗？", is_self=False)])
        service = AutoReplyService(config, backend=backend, client_factory=lambda cfg: FakeClient())
        service.chat = "小李"
        run_tick_after_quiet(service, FakeClient(), {})
        self.assertEqual(backend.sent, [("小李", "好呀，周末一起？")])

    def test_tick_skips_dry_run(self):
        config = AppConfig(
            api_key="sk-test",
            wechat_self_name="我",
            auto_reply_dry_run=True,
        )
        backend = FakeBackend([Message("对方", "在吗", is_self=False)])
        service = AutoReplyService(config, backend=backend, client_factory=lambda cfg: FakeClient())
        service.chat = "小李"
        run_tick_after_quiet(service, FakeClient(), {})
        self.assertEqual(backend.sent, [])

    def test_tick_skips_keyword(self):
        config = AppConfig(
            api_key="sk-test",
            wechat_self_name="我",
            auto_reply_dry_run=False,
            auto_reply_skip_keywords="验证码,转账",
        )
        backend = FakeBackend([Message("对方", "帮我收一下验证码", is_self=False)])
        service = AutoReplyService(config, backend=backend, client_factory=lambda cfg: FakeClient())
        service.chat = "小李"
        run_tick_after_quiet(service, FakeClient(), {})
        self.assertEqual(backend.sent, [])


if __name__ == "__main__":
    unittest.main()
