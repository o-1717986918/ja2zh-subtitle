from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


_DLL_HANDLES: list[object] = []


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Return the read-only application resource directory."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(str(bundled)).resolve()
    return Path(__file__).resolve().parents[1]


def state_root() -> Path:
    """Return a user-writable directory for WebUI state and uploads."""
    if not is_frozen():
        return resource_root() / ".webui"
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "JA2ZH Subtitle"


def default_output_dir() -> Path:
    if not is_frozen():
        return resource_root() / "output"
    videos = Path.home() / "Videos"
    return videos / "JA2ZH Subtitle"


def configure_bundled_environment() -> None:
    """Expose bundled media and CUDA DLLs before native modules are loaded."""
    if not is_frozen():
        return
    root = resource_root()
    ffmpeg = root / "bin" / "ffmpeg.exe"
    ffprobe = root / "bin" / "ffprobe.exe"
    if ffmpeg.is_file():
        os.environ.setdefault("JA2ZH_FFMPEG", str(ffmpeg))
    if ffprobe.is_file():
        os.environ.setdefault("JA2ZH_FFPROBE", str(ffprobe))

    path_items = [str(root), str(root / "bin")]
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([*path_items, current])
    add_directory = getattr(os, "add_dll_directory", None)
    if add_directory is not None:
        for directory in (root, root / "bin"):
            if directory.is_dir():
                try:
                    _DLL_HANDLES.append(add_directory(str(directory)))
                except OSError:
                    pass


def worker_command(arguments: Iterable[str | Path]) -> list[str]:
    values = [str(value) for value in arguments]
    if is_frozen():
        return [sys.executable, "--worker", *values]
    return [sys.executable, str(resource_root() / "main.py"), *values]

