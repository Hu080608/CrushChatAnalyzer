import json
import tempfile
import unittest
from pathlib import Path

from crush_analyzer.importers import import_file, import_csv, import_json, import_txt


class ImporterTests(unittest.TestCase):
    def test_txt_import_with_self_name(self):
        content = (
            "张三 2023-10-01 12:00:00\n"
            "你好呀\n"
            "李四 2023-10-01 12:01:00\n"
            "刚看到，嘿嘿\n"
            "张三 2023-10-01 12:02:00\n"
            "[\u5fae\u7b11]\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.txt"
            path.write_text(content, encoding="utf-8")
            result = import_file(path, self_name="张三", session_name="测试会话")
            self.assertEqual(result.detected_format, "txt")
            self.assertEqual(result.session.name, "测试会话")
            self.assertEqual(len(result.session.messages), 3)
            self.assertEqual(result.session.self_sender, "张三")
            self.assertTrue(result.session.messages[0].is_self)
            self.assertFalse(result.session.messages[1].is_self)
            self.assertIsNotNone(result.session.messages[0].timestamp)

    def test_csv_import(self):
        content = (
            "StrTime,NickName,StrContent,IsSender\n"
            "2023-10-01 12:00:00,张三,你好,0\n"
            "2023-10-01 12:01:00,李四,你也好,1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.csv"
            path.write_text(content, encoding="utf-8")
            messages, warnings = import_csv(path, self_name="李四")
            self.assertEqual(len(messages), 2)
            self.assertTrue(messages[1].is_self)
            self.assertFalse(messages[0].is_self)
            self.assertEqual(messages[0].content, "你好")

    def test_json_import_messages(self):
        payload = {
            "session": "小王",
            "messages": [
                {"sender": "小王", "content": "在干嘛", "time": "2023-10-01 20:00:00", "is_self": True},
                {"sender": "小李", "content": "刚下班，你呢", "time": "2023-10-01 20:05:00", "is_self": False},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = import_file(path, self_name="小王")
            self.assertEqual(len(result.session.messages), 2)
            self.assertEqual(result.session.self_sender, "小王")
            self.assertTrue(result.session.messages[0].is_self)
            self.assertFalse(result.session.messages[1].is_self)

    def test_txt_exported_with_time_first(self):
        content = "2023-10-01 20:00:00 小王\n晚好啊\n小王: 在忙吗\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.txt"
            path.write_text(content, encoding="utf-8")
            messages, warnings = import_txt(path, self_name="小王")
            self.assertGreaterEqual(len(messages), 2)
            self.assertTrue(all(m.sender == "小王" for m in messages))

    def test_txt_time_and_sender_inline(self):
        content = "2023-10-01 20:00:00 小王: 你好\n2023-10-01 20:01:00 小李: 你也好\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.txt"
            path.write_text(content, encoding="utf-8")
            messages, warnings = import_txt(path, self_name="小王")
            self.assertEqual([(m.sender, m.content) for m in messages], [("小王", "你好"), ("小李", "你也好")])

    def test_txt_three_line_header(self):
        content = "2023-10-01 20:00:00\n小王\n你好呀\n2023-10-01 20:01:00\n小李\n你也好\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.txt"
            path.write_text(content, encoding="utf-8")
            messages, warnings = import_txt(path, self_name="小王")
            self.assertEqual([(m.sender, m.content) for m in messages], [("小王", "你好呀"), ("小李", "你也好")])


if __name__ == "__main__":
    unittest.main()
