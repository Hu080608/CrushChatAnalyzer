import unittest

from crush_analyzer.models import ChatSession, Message, clean_name


class CleanNameTests(unittest.TestCase):
    def test_leading_spaces_and_placeholders(self):
        self.assertEqual(clean_name("  张三  "), "张三")
        self.assertEqual(clean_name("\u200b李 四"), "李四")
        self.assertEqual(clean_name("\ufeff@王五"), "王五")
        self.assertEqual(clean_name("  # 赵六 "), "赵六")
        self.assertEqual(clean_name("A\u3000B"), "AB")

    def test_session_and_message_row_cleaning(self):
        msg = Message.from_row({
            "message_id": "1",
            "session_id": "s",
            "sender": " 张 三 ",
            "content": "hi",
            "timestamp": "",
            "is_self": 0,
            "raw": "{}",
        })
        self.assertEqual(msg.sender, "张三")
        session = ChatSession.from_row({
            "id": "s",
            "name": "\u200b 测试 会话 ",
            "platform": "wechat",
            "source": "",
            "self_sender": " 我 ",
            "other_sender": " 张 三 ",
            "created_at": "",
            "updated_at": "",
            "meta": "{}",
        })
        self.assertEqual(session.name, "测试会话")
        self.assertEqual(session.self_sender, "我")
        self.assertEqual(session.other_sender, "张三")


if __name__ == "__main__":
    unittest.main()
