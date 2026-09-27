from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from .models import DeviceProfile


_DLL_DIRECTORY_HANDLES: list[object] = []
_DLL_DIRECTORIES: set[str] = set()


def prepare_windows_dll_directories() -> None:
    """Expose Conda runtime DLLs to native extensions on Python 3.8+."""
    if os.name != "nt":
        return

    prefixes = [Path(sys.prefix)]
    conda_prefix = os.environ.get("CONDA_PREFIX", "").strip()
    if conda_prefix:
        prefixes.insert(0, Path(conda_prefix))

    for prefix in prefixes:
        for directory in (prefix, prefix / "Library" / "bin"):
            if not directory.is_dir():
                continue
            resolved = str(directory.resolve())
            key = os.path.normcase(resolved)
            if key in _DLL_DIRECTORIES:
                continue
            _DLL_DIRECTORIES.add(key)
            current_path = os.environ.get("PATH", "")
            path_items = {os.path.normcase(item) for item in current_path.split(os.pathsep)}
            if key not in path_items:
                os.environ["PATH"] = resolved + os.pathsep + current_path
            add_directory = getattr(os, "add_dll_directory", None)
            if add_directory is not None:
                try:
                    _DLL_DIRECTORY_HANDLES.append(add_directory(resolved))
                except OSError:
                    pass


def _ram_gb() -> float | None:
    try:
        if os.name == "posix" and Path("/proc/meminfo").exists():
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def detect_device(requested: str = "auto") -> DeviceProfile:
    prepare_windows_dll_directories()
    notes: list[str] = []
    runtime_available = False
    cuda_available = False
    vram_gb: float | None = None
    try:
        import ctranslate2

        runtime_available = True
        cuda_available = ctranslate2.get_cuda_device_count() > 0
    except (ImportError, RuntimeError) as exc:
        notes.append(f"CTranslate2/CUDA 检测不可用：{exc}")

    if cuda_available:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                name, memory = [item.strip() for item in result.stdout.splitlines()[0].rsplit(",", 1)]
                vram_gb = round(float(memory) / 1024, 1)
                notes.append(f"GPU: {name}")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        if vram_gb is None:
            notes.append("已检测到 CUDA；未能读取显存容量")

    if requested == "cuda" and not cuda_available:
        raise RuntimeError("配置要求 CUDA，但当前 PyTorch 未检测到可用 CUDA")
    device = "cuda" if (requested == "cuda" or requested == "auto" and cuda_available) else "cpu"

    ram = _ram_gb()
    if cuda_available and vram_gb is not None and vram_gb >= 10:
        recommended = "quality"
    elif cuda_available and vram_gb is not None and vram_gb >= 6:
        recommended = "balanced"
    else:
        recommended = "lite"
    notes.append(f"系统：{platform.system()} {platform.machine()}")
    return DeviceProfile(
        torch_available=runtime_available,
        cuda_available=cuda_available,
        device=device,
        vram_gb=vram_gb,
        ram_gb=ram,
        recommended_preset=recommended,
        notes=notes,
    )


def resolve_compute_type(configured: str, device: str) -> str:
    if configured != "auto":
        return configured
    return "float16" if device == "cuda" else "int8"


def release_accelerator_memory() -> None:
    import gc

    gc.collect()
