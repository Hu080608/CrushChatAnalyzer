import unittest

from crush_analyzer.update import is_newer, parse_version, pick_exe_asset


class UpdateTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("v1.1.10"), (1, 1, 10))
        self.assertEqual(parse_version("1.2.0"), (1, 2, 0))
        self.assertEqual(parse_version("bad"), (0,))

    def test_is_newer(self):
        self.assertTrue(is_newer("1.1.11", "1.1.10"))
        self.assertTrue(is_newer("1.2.0", "1.1.99"))
        self.assertFalse(is_newer("1.1.10", "1.1.10"))
        self.assertFalse(is_newer("1.1.9", "1.1.10"))

    def test_pick_exe_asset(self):
        release = {
            "tag_name": "v1.1.11",
            "assets": [
                {"name": "source.zip", "browser_download_url": "x"},
                {"name": "CrushChatAnalyzer_v1.1.11.exe", "browser_download_url": "y"},
            ],
        }
        asset = pick_exe_asset(release)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "CrushChatAnalyzer_v1.1.11.exe")


if __name__ == "__main__":
    unittest.main()
