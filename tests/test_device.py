from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ja2zh_subtitle import device


class DeviceRuntimeTests(unittest.TestCase):
    def test_conda_library_bin_is_added_to_windows_dll_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp)
            path_type = type(prefix)
            library_bin = prefix / "Library" / "bin"
            library_bin.mkdir(parents=True)
            handle = object()
            add_dll_directory = MagicMock(return_value=handle)

            with (
                patch.object(device.os, "name", "nt"),
                patch.object(device, "Path", path_type),
                patch.object(device.sys, "prefix", str(prefix)),
                patch.dict(
                    os.environ,
                    {"CONDA_PREFIX": str(prefix), "PATH": r"C:\Windows"},
                ),
                patch.object(
                    device.os,
                    "add_dll_directory",
                    add_dll_directory,
                    create=True,
                ),
                patch.object(device, "_DLL_DIRECTORIES", set()),
                patch.object(device, "_DLL_DIRECTORY_HANDLES", []),
            ):
                device.prepare_windows_dll_directories()
                add_dll_directory.assert_any_call(str(library_bin.resolve()))
                self.assertIn(handle, device._DLL_DIRECTORY_HANDLES)
                self.assertIn(str(library_bin.resolve()), os.environ["PATH"])
