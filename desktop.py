from __future__ import annotations

import socket
import sys
import threading
import time
import traceback
from pathlib import Path

from ja2zh_subtitle.runtime import configure_bundled_environment, state_root


configure_bundled_environment()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_until_ready(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.08)
    raise RuntimeError("桌面服务启动超时")


def run_desktop() -> int:
    import uvicorn
    import webview

    import webui

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            webui.app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    server_thread = threading.Thread(target=server.run, name="webui-server", daemon=True)
    server_thread.start()
    _wait_until_ready(port)

    storage = state_root() / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.create_window(
        "字幕工作台 · JA → ZH",
        f"http://127.0.0.1:{port}",
        width=1360,
        height=860,
        min_size=(960, 640),
        background_color="#eef2f1",
        text_select=True,
    )
    try:
        webview.start(
            debug=False,
            private_mode=False,
            storage_path=str(storage),
        )
    finally:
        webui.shutdown_jobs()
        server.should_exit = True
        server_thread.join(timeout=5)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        from main import main as cli_main

        return cli_main(sys.argv[2:])
    return run_desktop()


def report_fatal_error(error: BaseException) -> None:
    log_dir = state_root()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "desktop-error.log"
    detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    log_path.write_text(detail, encoding="utf-8")
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                f"字幕工作台启动失败。\n\n诊断日志：{log_path}",
                "字幕工作台",
                0x10,
            )
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        report_fatal_error(exc)
        raise SystemExit(1)
