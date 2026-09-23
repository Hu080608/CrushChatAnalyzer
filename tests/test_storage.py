import tempfile
import unittest
from pathlib import Path

from crush_analyzer.models import ChatSession, Message
from crush_analyzer.storage import Database


class StorageTests(unittest.TestCase):
    def test_session_roundtrip_and_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.db")
            session = ChatSession(name="小李", self_sender="我", other_sender="小李")
            session.messages = [
                Message("我", "在吗", is_self=True),
                Message("小李", "在的", is_self=False),
            ]
            db.save_session(session)
            loaded = db.get_session(session.id)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded.messages), 2)
            self.assertTrue(loaded.messages[0].is_self)
            self.assertEqual(len(db.list_sessions()), 1)
            self.assertEqual(db.message_count(session.id), 2)

            record_id = db.add_analysis(session.id, "local", "测试报告", model="local")
            self.assertGreater(record_id, 0)
            record = db.get_latest_analysis(session.id, "local")
            self.assertIsNotNone(record)
            self.assertEqual(record.content, "测试报告")

            db.delete_session(session.id)
            self.assertIsNone(db.get_session(session.id))
            self.assertEqual(db.message_count(session.id), 0)
            db.close()


if __name__ == "__main__":
    unittest.main()
