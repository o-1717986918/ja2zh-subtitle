from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

import webui


class WebUiTests(unittest.TestCase):
    def test_index_is_served(self) -> None:
        response = TestClient(webui.app).get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("字幕工作台", response.text)

    def test_job_config_contains_no_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = webui.JobRequest(
                source_path=str(root / "sample.mp4"),
                output_dir=str(root / "out"),
                model="deepseek-v4-pro",
                vad_threshold=0.4,
                quality_mode="warn",
            )
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-secret-must-not-be-written"}):
                path = webui.build_job_config(request, root / "job")
            raw = path.read_text(encoding="utf-8")
            config = yaml.safe_load(raw)
            self.assertNotIn("sk-secret-must-not-be-written", raw)
            self.assertEqual(config["polish"]["api_key_env"], "DEEPSEEK_API_KEY")
            self.assertEqual(config["polish"]["model"], "deepseek-v4-pro")
            self.assertEqual(config["asr"]["vad_parameters"]["threshold"], 0.4)

    def test_chinese_job_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "sample.mp4"
            source.write_bytes(b"video")
            original = webui.current_api_key
            webui.current_api_key = lambda: ("", "none")
            try:
                response = TestClient(webui.app).post(
                    "/api/jobs",
                    json={"source_path": str(source), "output_dir": str(Path(temp) / "out")},
                )
            finally:
                webui.current_api_key = original
            self.assertEqual(response.status_code, 400)
            self.assertIn("API Key", response.json()["detail"])

    def test_log_stage_progress(self) -> None:
        self.assertEqual(webui.stage_from_log("INFO [4/6] 上下文翻译"), ("翻译与润色", 66))


if __name__ == "__main__":
    unittest.main()
