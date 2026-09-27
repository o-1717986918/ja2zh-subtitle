from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ja2zh_subtitle.runtime import (
    configure_bundled_environment,
    default_output_dir,
    is_frozen,
    resource_root,
    state_root,
    worker_command,
)


configure_bundled_environment()
ROOT = resource_root()
WEB_ROOT = ROOT / "webui"
STATE_ROOT = state_root()
UPLOAD_ROOT = STATE_ROOT / "uploads"
JOB_ROOT = STATE_ROOT / "jobs"
SETTINGS_FILE = STATE_ROOT / "settings.json"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"}
KEYRING_SERVICE = "ja2zh-subtitle-webui"
KEYRING_ACCOUNT = "deepseek-api-key"


DEFAULT_SETTINGS: dict[str, Any] = {
    "output_dir": str(default_output_dir()),
    "preset": "balanced" if is_frozen() else "auto",
    "device": "auto",
    "quality_mode": "warn",
    "japanese_only": False,
    "subtitle_only": False,
    "no_polish": False,
    "force": False,
    "vad_filter": True,
    "gap_recovery": True,
    "vad_threshold": 0.30,
    "min_gap_seconds": 1.5,
    "model": "deepseek-v4-flash",
    "batch_size": 12,
    "max_chars_per_line": 18,
    "font_size": 48,
    "video_codec": "h264",
    "video_crf": 18,
    "video_preset": "medium",
}


class ApiKeyRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)
    remember: bool = True


class JobRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)
    output_dir: str = Field(default="", max_length=4096)
    preset: Literal["auto", "lite", "balanced", "quality"] = "auto"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    quality_mode: Literal["off", "warn", "strict"] = "warn"
    japanese_only: bool = False
    subtitle_only: bool = False
    no_polish: bool = False
    force: bool = False
    vad_filter: bool = True
    gap_recovery: bool = True
    vad_threshold: float = Field(default=0.30, ge=0.05, le=0.95)
    min_gap_seconds: float = Field(default=1.5, ge=0.5, le=30.0)
    model: Literal["deepseek-v4-flash", "deepseek-v4-pro"] = "deepseek-v4-flash"
    batch_size: int = Field(default=12, ge=1, le=64)
    max_chars_per_line: int = Field(default=18, ge=8, le=40)
    font_size: int = Field(default=48, ge=20, le=96)
    video_codec: Literal["h264", "h265"] = "h264"
    video_crf: int = Field(default=18, ge=12, le=32)
    video_preset: Literal[
        "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"
    ] = "medium"


class JobState:
    def __init__(self, job_id: str, request: JobRequest, source: Path, output: Path) -> None:
        self.id = job_id
        self.request = request
        self.source = source
        self.output = output
        self.status = "queued"
        self.stage = "等待运行"
        self.progress = 0
        self.logs: list[str] = []
        self.error = ""
        self.files: list[dict[str, Any]] = []
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.process: subprocess.Popen[str] | None = None
        self.cancel_requested = False
        self.lock = threading.Lock()

    def add_log(self, line: str) -> None:
        with self.lock:
            self.logs.append(line.rstrip("\r\n"))
            if len(self.logs) > 1000:
                self.logs = self.logs[-1000:]
            stage = stage_from_log(line)
            if stage:
                self.stage, self.progress = stage

    def public(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "progress": self.progress,
                "logs": list(self.logs),
                "error": self.error,
                "files": copy.deepcopy(self.files),
                "source_name": self.source.name,
                "output_dir": str(self.output),
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


app = FastAPI(title="ja2zh-subtitle WebUI", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
app.mount("/fonts", StaticFiles(directory=ROOT / "assets" / "fonts"), name="fonts")

JOBS: dict[str, JobState] = {}
FILE_TOKENS: dict[str, Path] = {}
JOBS_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()
SESSION_API_KEY = ""


def load_settings() -> dict[str, Any]:
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for key in settings:
                    if key in saved:
                        settings[key] = saved[key]
        except (OSError, ValueError):
            pass
    return settings


def save_settings(request: JobRequest) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    values = request.model_dump(exclude={"source_path"})
    temporary = SETTINGS_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, SETTINGS_FILE)


def keyring_get() -> str:
    try:
        import keyring

        return (keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) or "").strip()
    except Exception:
        return ""


def current_api_key() -> tuple[str, str]:
    if SESSION_API_KEY:
        return SESSION_API_KEY, "session"
    environment = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if environment:
        return environment, "environment"
    stored = keyring_get()
    if stored:
        return stored, "credential_vault"
    return "", "none"


def set_api_key(value: str, remember: bool) -> tuple[str, str]:
    global SESSION_API_KEY
    SESSION_API_KEY = value.strip()
    if not remember:
        return "session", "密钥只在本次 WebUI 运行期间保留。"
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, SESSION_API_KEY)
        return "credential_vault", "密钥已保存到系统凭据库，页面不会回显。"
    except Exception:
        return "session", "系统凭据库不可用，密钥仅在本次运行期间保留。"


def clear_api_key() -> None:
    global SESSION_API_KEY
    SESSION_API_KEY = ""
    try:
        import keyring

        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        pass


def stage_from_log(line: str) -> tuple[str, int] | None:
    stages = {
        "[1/6]": ("提取音频", 10),
        "[2/6]": ("识别日语", 28),
        "[3/6]": ("准备翻译", 48),
        "[4/6]": ("翻译与润色", 66),
        "[5/6]": ("整理字幕", 82),
        "[6/6]": ("烧录成片", 93),
        "[3/4]": ("整理日语字幕", 72),
        "[4/4]": ("烧录成片", 93),
    }
    for marker, state in stages.items():
        if marker in line:
            return state
    return None


def build_job_config(request: JobRequest, job_dir: Path) -> Path:
    loaded = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    loaded.setdefault("runtime", {})["output_dir"] = request.output_dir
    asr = loaded.setdefault("asr", {})
    asr["vad_filter"] = request.vad_filter
    asr.setdefault("vad_parameters", {})["threshold"] = request.vad_threshold
    recovery = asr.setdefault("gap_recovery", {})
    recovery["enabled"] = request.gap_recovery
    recovery["min_gap_seconds"] = request.min_gap_seconds
    loaded.setdefault("translation", {})["backend"] = "deepseek"
    polish = loaded.setdefault("polish", {})
    polish["provider"] = "deepseek"
    polish["model"] = request.model
    polish["batch_size"] = request.batch_size
    subtitle = loaded.setdefault("subtitle", {})
    subtitle["max_chars_per_line"] = request.max_chars_per_line
    subtitle["font_size"] = request.font_size
    loaded.setdefault("quality_control", {})["mode"] = request.quality_mode
    video = loaded.setdefault("video", {})
    video["codec"] = request.video_codec
    video["crf"] = request.video_crf
    video["preset"] = request.video_preset

    job_dir.mkdir(parents=True, exist_ok=True)
    config_path = job_dir / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return config_path


def collect_output_files(job: JobState) -> list[dict[str, Any]]:
    if not job.output.is_dir():
        return []
    candidates = sorted(
        (
            path
            for path in job.output.iterdir()
            if path.is_file() and path.name.startswith(job.source.stem)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    files: list[dict[str, Any]] = []
    for path in candidates:
        token = uuid.uuid4().hex
        FILE_TOKENS[token] = path.resolve()
        suffix = path.suffix.lower()
        kind = "video" if suffix in {".mp4", ".mkv", ".webm"} else "subtitle"
        if path.name.endswith("_review.txt"):
            kind = "report"
        files.append(
            {
                "name": path.name,
                "kind": kind,
                "size": path.stat().st_size,
                "url": f"/api/files/{token}",
            }
        )
    return files


def job_command(job: JobState, config_path: Path) -> list[str]:
    request = job.request
    command = worker_command(
        [
        str(job.source),
        "--config",
        str(config_path),
        "--preset",
        request.preset,
        "--device",
        request.device,
        "--quality-mode",
        request.quality_mode,
        "--output-dir",
        str(job.output),
        ]
    )
    if request.japanese_only:
        command.append("--ja-only")
    if request.subtitle_only:
        command.append("--subtitle-only")
    if request.no_polish:
        command.append("--no-polish")
    if request.force:
        command.append("--force")
    return command


def run_job(job: JobState, api_key: str) -> None:
    with RUN_LOCK:
        if job.cancel_requested:
            with job.lock:
                job.status = "cancelled"
                job.stage = "已取消"
                job.finished_at = time.time()
            return
        job_dir = JOB_ROOT / job.id
        config_path = build_job_config(job.request, job_dir)
        command = job_command(job, config_path)
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        if api_key:
            environment["DEEPSEEK_API_KEY"] = api_key
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with job.lock:
            job.status = "running"
            job.stage = "启动流水线"
            job.progress = 3
            job.started_at = time.time()
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                creationflags=creationflags,
            )
            job.process = process
            assert process.stdout is not None
            for line in process.stdout:
                job.add_log(line)
            code = process.wait()
            with job.lock:
                job.finished_at = time.time()
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.stage = "已取消"
                elif code == 0:
                    job.status = "completed"
                    job.stage = "处理完成"
                    job.progress = 100
                    job.files = collect_output_files(job)
                else:
                    job.status = "failed"
                    job.stage = "处理失败"
                    job.error = next(
                        (
                            line.split("处理失败：", 1)[-1]
                            for line in reversed(job.logs)
                            if "处理失败：" in line
                        ),
                        f"流水线退出码：{code}",
                    )
        except Exception as exc:
            with job.lock:
                job.status = "failed"
                job.stage = "启动失败"
                job.error = str(exc)
                job.finished_at = time.time()
        finally:
            job.process = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/state")
def state() -> dict[str, Any]:
    key, source = current_api_key()
    return {
        "settings": load_settings(),
        "api_key": {"set": bool(key), "source": source},
        "project_root": str(ROOT),
        "supported_extensions": sorted(VIDEO_EXTENSIONS),
        "packaged": is_frozen(),
        "bundled_presets": ["balanced"] if is_frozen() else [],
    }


@app.post("/api/api-key")
def save_key(request: ApiKeyRequest) -> dict[str, Any]:
    storage, message = set_api_key(request.api_key, request.remember)
    return {"set": True, "source": storage, "message": message}


@app.delete("/api/api-key")
def delete_key() -> dict[str, Any]:
    clear_api_key()
    key, source = current_api_key()
    return {
        "set": bool(key),
        "source": source,
        "message": (
            "已清除 WebUI 保存的密钥。"
            if not key
            else "已清除凭据库密钥；环境变量中的密钥仍然有效。"
        ),
    }


@app.post("/api/uploads")
async def upload_video(file: UploadFile = File(...)) -> dict[str, Any]:
    original = Path(file.filename or "video.mp4").name
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original).strip(" .")
    if not safe_name or Path(safe_name).suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="请选择受支持的视频文件。")
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_ROOT / f"{uuid.uuid4().hex[:10]}-{safe_name}"
    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(4 * 1024 * 1024):
                handle.write(chunk)
                size += len(chunk)
    finally:
        await file.close()
    return {"path": str(target.resolve()), "name": safe_name, "size": size}


@app.post("/api/jobs")
def create_job(request: JobRequest) -> dict[str, Any]:
    if is_frozen() and request.preset != "balanced":
        raise HTTPException(
            status_code=400,
            detail="桌面安装包内置 Whisper-medium，请使用“均衡”识别档位。",
        )
    source = Path(request.source_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="视频路径不存在或格式不受支持。")
    output = Path(request.output_dir or DEFAULT_SETTINGS["output_dir"]).expanduser()
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    api_key, _ = current_api_key()
    if not request.japanese_only and not api_key:
        raise HTTPException(
            status_code=400,
            detail="生成中文字幕前，请先在左侧保存 DeepSeek API Key。",
        )
    request.output_dir = str(output)
    save_settings(request)
    job_id = uuid.uuid4().hex[:12]
    job = JobState(job_id, request, source, output)
    with JOBS_LOCK:
        JOBS[job_id] = job
    threading.Thread(target=run_job, args=(job, api_key), daemon=True).start()
    return job.public()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或 WebUI 已重启。")
    return job.public()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    with job.lock:
        terminal = job.status not in {"queued", "running"}
        if not terminal:
            job.cancel_requested = True
        process = job.process
    if terminal:
        return job.public()
    if process is not None and process.poll() is None:
        process.terminate()
    return job.public()


def shutdown_jobs() -> None:
    """Stop active worker processes before the desktop window exits."""
    with JOBS_LOCK:
        jobs = list(JOBS.values())
    for job in jobs:
        with job.lock:
            if job.status not in {"queued", "running"}:
                continue
            job.cancel_requested = True
            process = job.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass


@app.get("/api/files/{token}")
def get_file(token: str) -> FileResponse:
    path = FILE_TOKENS.get(token)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="输出文件不存在。")
    media_type, _ = mimetypes.guess_type(path.name)
    disposition = "inline" if path.suffix.lower() in {".mp4", ".mkv", ".webm"} else "attachment"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type=disposition,
    )


@app.post("/api/jobs/{job_id}/open-output")
def open_output(job_id: str) -> dict[str, bool]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    job.output.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(job.output)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(job.output)])
    else:
        subprocess.Popen(["xdg-open", str(job.output)])
    return {"opened": True}


@app.get("/api/doctor")
def doctor() -> dict[str, Any]:
    environment = os.environ.copy()
    key, _ = current_api_key()
    if key:
        environment["DEEPSEEK_API_KEY"] = key
    completed = subprocess.run(
        worker_command(["--doctor"]),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "output": (completed.stdout + completed.stderr).strip(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 ja2zh-subtitle 本地 WebUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("警告：WebUI 包含本机文件和 API Key 设置，建议只监听 127.0.0.1。")
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
