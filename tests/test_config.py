from __future__ import annotations

import unittest

from ja2zh_subtitle.config import DEFAULT_CONFIG, deep_merge, load_config


class ConfigTests(unittest.TestCase):
    def test_deep_merge_does_not_mutate_source(self) -> None:
        merged = deep_merge(DEFAULT_CONFIG, {"asr": {"beam_size": 9}})
        self.assertEqual(merged["asr"]["beam_size"], 9)
        self.assertEqual(DEFAULT_CONFIG["asr"]["beam_size"], 5)

    def test_lite_preset(self) -> None:
        config = load_config(None, "lite")
        self.assertEqual(config["asr"]["model"], "small")
        self.assertEqual(config["translation"]["backend"], "deepseek")
        self.assertEqual(config["polish"]["model"], "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
