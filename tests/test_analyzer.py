import unittest
from datetime import datetime, timedelta

from crush_analyzer.analyzer import compute_stats, local_analysis
from crush_analyzer.models import ChatSession, Message


class AnalyzerTests(unittest.TestCase):
    def test_compute_stats_and_local_report(self):
        base = datetime(2024, 1, 1, 20, 0, 0)
        messages = [
            Message("我", "今天过得怎么样呀？", base, is_self=True),
            Message("对方", "还不错，今天吃了好吃的哈哈", base + timedelta(minutes=5), is_self=False),
            Message("我", "那太好啦，是什么好吃的？", base + timedelta(minutes=7), is_self=True),
            Message("对方", "火锅，下次带你", base + timedelta(minutes=10), is_self=False),
            Message("对方", "想你", base + timedelta(minutes=11), is_self=False),
        ]
        session = ChatSession(name="测试", self_sender="我", other_sender="对方", messages=messages)
        stats = compute_stats(messages)
        self.assertEqual(stats.total, 5)
        self.assertEqual(stats.self_count, 2)
        self.assertEqual(stats.other_count, 3)
        self.assertGreaterEqual(stats.other_stats.positive, 2)
        self.assertGreaterEqual(len(stats.reply_other_minutes), 1)
        report = local_analysis(session)
        self.assertIn("本地速览", report)
        self.assertIn("关系信号", report)


if __name__ == "__main__":
    unittest.main()
