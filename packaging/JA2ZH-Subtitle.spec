# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata


ROOT = Path(os.environ["JA2ZH_PROJECT_ROOT"]).resolve()
MODEL_DIR = Path(os.environ["JA2ZH_WHISPER_MODEL_DIR"]).resolve()
FFMPEG = Path(os.environ["JA2ZH_FFMPEG_PATH"]).resolve()
FFPROBE = Path(os.environ["JA2ZH_FFPROBE_PATH"]).resolve()
WITH_CUDA = os.environ.get("JA2ZH_BUILD_WITH_CUDA", "1") == "1"
ICON = ROOT / "assets" / "app.ico"

datas = [
    (str(ROOT / "config.yaml"), "."),
    (str(ROOT / "prompts"), "prompts"),
    (str(ROOT / "webui"), "webui"),
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
    (str(MODEL_DIR), "models/whisper/medium"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE_MODELS.md"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
binaries = [
    (str(FFMPEG), "bin"),
    (str(FFPROBE), "bin"),
]
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "keyring.backends.Windows",
]

for package in ("webview", "keyring", "clr_loader", "pythonnet"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

datas += collect_data_files("faster_whisper")
for package in (
    "faster-whisper",
    "ctranslate2",
    "huggingface-hub",
    "keyring",
    "pywebview",
):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass

if WITH_CUDA:
    prefix_value = os.environ.get("CONDA_PREFIX", "") or os.environ.get("VIRTUAL_ENV", "")
    prefix = Path(prefix_value) if prefix_value else Path(sys.prefix)
    if not prefix.is_dir():
        prefix = Path(sys.prefix)
    cuda_sources = [prefix / "Library" / "bin", prefix / "Lib" / "site-packages" / "torch" / "lib"]
    cuda_names = {"cublas64_12.dll", "cublasLt64_12.dll", "zlibwapi.dll"}
    for source in cuda_sources:
        if not source.is_dir():
            continue
        for candidate in source.glob("cudnn*64_9.dll"):
            cuda_names.add(candidate.name)
    located = {}
    for name in sorted(cuda_names):
        for source in cuda_sources:
            candidate = source / name
            if candidate.is_file():
                located[name.lower()] = candidate
                break
    required = {"cublas64_12.dll", "cublaslt64_12.dll", "cudnn64_9.dll"}
    missing = sorted(required - set(located))
    if missing:
        raise SystemExit(f"缺少 CUDA 打包文件：{', '.join(missing)}")
    binaries += [(str(path), ".") for path in located.values()]

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "transformers",
        "tensorflow",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "cefpython3",
        "tkinter",
        "matplotlib",
        "pandas",
        "scipy",
        "sklearn",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JA2ZH Subtitle",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(ROOT / "packaging" / "windows_version_info.txt"),
    contents_directory="_internal",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JA2ZH Subtitle",
)
